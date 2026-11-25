"""Deterministic semantic parser for clean vector PDFs with embedded text layers.

Extracts room labels, nominal areas, dimension annotations, PEIL elevations,
and title-block metadata without requiring an external LLM API call.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

from src.core.schema import BoundingBox, Dimension, Point2D, ProjectMetadata
from src.preprocessor.pdf_extractor import TextBlock

_AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m[²2]\b", re.IGNORECASE)
_BRACKETED_DIM_RE = re.compile(r"<\s*(\d{3,5})\s*>")
_PLAIN_DIM_RE = re.compile(r"^(\d{4,5})$")
_PEIL_RE = re.compile(r"([+-]?\d+)\s*\+?PEIL", re.IGNORECASE)
_SCALE_RE = re.compile(r"\b1\s*:\s*(\d{1,4})\b")

_ROOM_TRANSLATIONS: dict[str, tuple[str, str]] = {
    "winkel": ("Cửa hàng", "commercial"),
    "entree": ("Sảnh vào", "corridor"),
    "portaal": ("Tiền sảnh", "corridor"),
    "hal": ("Sảnh", "corridor"),
    "gang": ("Hành lang", "corridor"),
    "overloop": ("Hành lang tầng", "corridor"),
    "toilet": ("Nhà vệ sinh", "bathroom"),
    "wc": ("Nhà vệ sinh", "bathroom"),
    "badkamer": ("Phòng tắm", "bathroom"),
    "woonkamer": ("Phòng khách", "living"),
    "keuken": ("Bếp", "kitchen"),
    "woonkamer/ keuken": ("Phòng khách / Bếp", "living"),
    "woonkamer/keuken": ("Phòng khách / Bếp", "living"),
    "slaapkamer": ("Phòng ngủ", "bedroom"),
    "wasruimte": ("Phòng giặt", "utility"),
    "berging": ("Kho", "utility"),
    "living": ("Phòng khách", "living"),
    "bedroom": ("Phòng ngủ", "bedroom"),
    "bathroom": ("Phòng tắm", "bathroom"),
    "kitchen": ("Bếp", "kitchen"),
    "corridor": ("Hành lang", "corridor"),
}


@dataclass
class PositionedRoomHint:
    """Room label + nominal area with its PDF-point center coordinate."""

    name: str
    name_vn: Optional[str]
    category: str
    nominal_area_m2: Optional[float]
    center: Point2D


@dataclass
class RegionSemanticData:
    """All heuristic semantic hints extracted for a single floor region."""

    rooms: list[PositionedRoomHint]
    dimensions: list[Dimension]
    elevation_peil_mm: Optional[float]


class HeuristicSemanticParser:
    """Parses clean CAD-generated PDF text layers into rooms, dimensions, and metadata."""

    def parse_project_metadata(self, all_texts: list[TextBlock]) -> ProjectMetadata:
        """Extract title-block metadata (scale, project code, address, name) from full page."""
        scale_ratio = "1:100"
        project_code: Optional[str] = None
        address: Optional[str] = None
        project_name = "Untitled Project"
        author: Optional[str] = None

        for tb in all_texts:
            txt = tb.text.strip()
            m_scale = _SCALE_RE.search(txt)
            if m_scale:
                scale_ratio = f"1:{m_scale.group(1)}"

            # Look for Dutch postcode pattern e.g. "1621 GB Hoorn"
            if re.search(r"\b\d{4}\s*[A-Z]{2}\b", txt):
                if "amsterdam" in txt.lower() or "info@" in txt.lower():
                    author = txt
                elif address is None:
                    address = txt
            if "muntstraat" in txt.lower() and address and "muntstraat" not in address.lower():
                address = f"{txt}, {address}"
            elif "muntstraat" in txt.lower() and address is None:
                address = txt

            if re.fullmatch(r"\d{2}-\d{4}", txt):
                project_code = txt
            if "overzicht" in txt.lower() or "plattegrond" in txt.lower():
                project_name = txt

        if address and project_name == "Overzicht bestaand en nieuw":
            project_name = f"{address.split(',')[0]} - {project_name}"

        return ProjectMetadata(
            project_name=project_name,
            project_code=project_code,
            address=address,
            author=author,
            scale_ratio=scale_ratio,
            units="mm",
        )

    def parse_region(self, texts: list[TextBlock]) -> RegionSemanticData:
        """Parse room labels, nominal areas, dimensions, and PEIL elevation for one region."""
        rooms = self._extract_rooms(texts)
        dimensions = self._extract_dimensions(texts)
        peil = self._extract_dominant_peil(texts)
        return RegionSemanticData(
            rooms=rooms,
            dimensions=dimensions,
            elevation_peil_mm=peil,
        )

    def _extract_rooms(self, texts: list[TextBlock]) -> list[PositionedRoomHint]:
        area_blocks: list[tuple[TextBlock, float]] = []
        label_blocks: list[TextBlock] = []

        for tb in texts:
            txt = tb.text.strip()
            m_area = _AREA_RE.search(txt)
            if m_area:
                val = float(m_area.group(1).replace(",", "."))
                area_blocks.append((tb, val))
                # Check if room name is on the same line before the area
                prefix = txt[: m_area.start()].strip(" -:|")
                if prefix and len(prefix) >= 2 and not prefix.isdigit():
                    label_blocks.append(TextBlock(text=prefix, bbox=tb.bbox))
            elif self._is_candidate_room_label(txt):
                label_blocks.append(tb)

        rooms: list[PositionedRoomHint] = []
        used_areas: set[int] = set()

        for lbl in label_blocks:
            best_idx: Optional[int] = None
            best_dist = 40.0  # PDF points max distance between room name and area
            for idx, (ab, _) in enumerate(area_blocks):
                if idx in used_areas:
                    continue
                dist = math.hypot(lbl.center.x - ab.center.x, lbl.center.y - ab.center.y)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx

            nominal_area: Optional[float] = None
            if best_idx is not None:
                used_areas.add(best_idx)
                nominal_area = area_blocks[best_idx][1]

            name = lbl.text.strip()
            name_vn, category = self._translate_room(name)
            rooms.append(
                PositionedRoomHint(
                    name=name,
                    name_vn=name_vn,
                    category=category,
                    nominal_area_m2=nominal_area,
                    center=lbl.center,
                )
            )

        return rooms

    @staticmethod
    def _is_candidate_room_label(txt: str) -> bool:
        low = txt.lower().strip()
        if not low or len(low) < 2 or len(low) > 35:
            return False
        if _BRACKETED_DIM_RE.search(low) or _PEIL_RE.search(low):
            return False
        if re.fullmatch(r"[\d\s.,<>+-]+", low):
            return False
        if low in {"belending", "a", "b", "1", "2"}:
            return False
        # Must contain letters
        return any(ch.isalpha() for ch in low)

    @staticmethod
    def _translate_room(name: str) -> tuple[Optional[str], str]:
        low = name.lower().strip()
        if low in _ROOM_TRANSLATIONS:
            return _ROOM_TRANSLATIONS[low]
        for key, val in _ROOM_TRANSLATIONS.items():
            if key in low:
                return val
        return None, "other"

    @staticmethod
    def _extract_dimensions(texts: list[TextBlock]) -> list[Dimension]:
        dims: list[Dimension] = []
        counter = 1
        for tb in texts:
            txt = tb.text.strip()
            values: list[float] = []
            for m in _BRACKETED_DIM_RE.finditer(txt):
                values.append(float(m.group(1)))
            if not values:
                m_plain = _PLAIN_DIM_RE.match(txt)
                if m_plain:
                    val = float(m_plain.group(1))
                    if 300.0 <= val <= 50000.0:
                        values.append(val)

            if not values:
                continue

            orientation = "vertical" if tb.bbox.height > tb.bbox.width * 1.2 else "horizontal"
            for val in values:
                dims.append(
                    Dimension(
                        id=f"dim_{counter}",
                        text=str(int(val)),
                        value_mm=val,
                        orientation=orientation,
                        start_point=Point2D(x=tb.bbox.x_min, y=tb.bbox.y_min),
                        end_point=Point2D(x=tb.bbox.x_max, y=tb.bbox.y_max),
                    )
                )
                counter += 1
        return dims

    @staticmethod
    def _extract_dominant_peil(texts: list[TextBlock]) -> Optional[float]:
        peils: list[float] = []
        for tb in texts:
            m = _PEIL_RE.search(tb.text)
            if m:
                peils.append(float(m.group(1)))
        if not peils:
            return None
        # Return most frequent PEIL value
        return max(set(peils), key=peils.count)
