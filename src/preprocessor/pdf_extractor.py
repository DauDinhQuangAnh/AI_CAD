"""PDF Vector & Text Extractor using PyMuPDF.

Extracts clean vector line segments, curve/arc candidates, and positioned text blocks,
clusters them into distinct floor-plan regions, and flips Y into right-handed CAD coordinates.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pymupdf

from src.core.schema import BoundingBox, Point2D

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VectorSegment:
    """A 2D line segment extracted from a PDF vector path (in CAD Y-up PDF points)."""

    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 0.24
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    is_dashed: bool = False

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    @property
    def angle_deg(self) -> float:
        """Angle in [0, 180) degrees."""
        ang = math.degrees(math.atan2(self.y2 - self.y1, self.x2 - self.x1)) % 180.0
        return ang

    @property
    def midpoint(self) -> Point2D:
        return Point2D(x=(self.x1 + self.x2) / 2.0, y=(self.y1 + self.y2) / 2.0)

    @property
    def is_gray(self) -> bool:
        """True if stroke is light/medium gray (typically hatch, grid, or context)."""
        r, g, b = self.color
        return abs(r - g) < 0.05 and abs(g - b) < 0.05 and r > 0.35

    @property
    def is_primary_structure(self) -> bool:
        """True if stroke is black (architectural structure), excluding red fire-rating annotations."""
        r, g, b = self.color
        is_black = r < 0.25 and g < 0.25 and b < 0.25
        return is_black and not self.is_dashed


@dataclass(frozen=True)
class TextBlock:
    """A positioned text block extracted from the PDF text layer (CAD Y-up PDF points)."""

    text: str
    bbox: BoundingBox

    @property
    def center(self) -> Point2D:
        return Point2D(
            x=(self.bbox.x_min + self.bbox.x_max) / 2.0,
            y=(self.bbox.y_min + self.bbox.y_max) / 2.0,
        )


@dataclass
class ExtractedRegion:
    """A cropped floor-plan region on a PDF page."""

    region_id: str
    page_index: int
    pdf_rect: tuple[float, float, float, float]  # (x0, y0, x1, y1) in PyMuPDF Y-down coords
    cad_bbox: BoundingBox
    segments: list[VectorSegment] = field(default_factory=list)
    texts: list[TextBlock] = field(default_factory=list)
    suggested_floor_name: Optional[str] = None


@dataclass
class ExtractedPDF:
    """Full extraction result for a PDF document."""

    source_path: Path
    page_count: int
    page_sizes: list[tuple[float, float]]
    regions: list[ExtractedRegion] = field(default_factory=list)
    all_texts: list[TextBlock] = field(default_factory=list)


class PDFExtractor:
    """Extracts vector geometry, text blocks, and cropped floor regions from vector PDFs."""

    def __init__(
        self,
        min_segment_length_pt: float = 0.5,
        cluster_gap_pt: float = 35.0,
        min_region_segments: int = 300,
    ) -> None:
        if min_segment_length_pt < 0:
            raise ValueError("min_segment_length_pt must be non-negative")
        self.min_segment_length_pt = min_segment_length_pt
        self.cluster_gap_pt = cluster_gap_pt
        self.min_region_segments = min_region_segments

    def extract(self, pdf_path: str | Path) -> ExtractedPDF:
        """Extract all vector segments, text blocks, and floor regions from a PDF."""
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {path}")

        doc = pymupdf.open(str(path))
        result = ExtractedPDF(
            source_path=path,
            page_count=len(doc),
            page_sizes=[],
        )

        try:
            for page_idx, page in enumerate(doc):
                page_w = float(page.rect.width)
                page_h = float(page.rect.height)
                result.page_sizes.append((page_w, page_h))

                segments = self._extract_segments(page, page_h)
                texts = self._extract_texts(page, page_h)
                result.all_texts.extend(texts)

                regions = self._cluster_regions(page_idx, page_h, segments, texts)
                result.regions.extend(regions)
                logger.info(
                    "Page %d: extracted %d segments, %d texts, %d floor regions",
                    page_idx,
                    len(segments),
                    len(texts),
                    len(regions),
                )
        finally:
            doc.close()

        return result

    def render_region_png(
        self,
        pdf_path: str | Path,
        page_index: int,
        pdf_rect: tuple[float, float, float, float],
        output_path: str | Path,
        dpi: int = 200,
    ) -> Path:
        """Render a cropped floor-plan region to a high-resolution PNG for Vision LLM."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        doc = pymupdf.open(str(pdf_path))
        try:
            page = doc[page_index]
            clip = pymupdf.Rect(*pdf_rect)
            zoom = dpi / 72.0
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
            pix.save(str(out))
        finally:
            doc.close()
        return out

    def _extract_segments(self, page: pymupdf.Page, page_h: float) -> list[VectorSegment]:
        segments: list[VectorSegment] = []
        for drawing in page.get_drawings():
            raw_color = drawing.get("color")
            if raw_color is None:
                continue  # fill-only path with no stroke
            color = (
                float(raw_color[0]),
                float(raw_color[1]),
                float(raw_color[2]),
            )
            width = float(drawing.get("width") or 0.0)
            dashes = drawing.get("dashes") or ""
            is_dashed = bool(dashes and dashes != "[] 0")

            for item in drawing.get("items", []):
                kind = item[0]
                if kind == "l":
                    p1, p2 = item[1], item[2]
                    seg = VectorSegment(
                        x1=float(p1.x),
                        y1=page_h - float(p1.y),
                        x2=float(p2.x),
                        y2=page_h - float(p2.y),
                        width=width,
                        color=color,
                        is_dashed=is_dashed,
                    )
                    if seg.length >= self.min_segment_length_pt:
                        segments.append(seg)
                elif kind == "re":
                    rect = item[1]
                    corners = [
                        (float(rect.x0), page_h - float(rect.y0)),
                        (float(rect.x1), page_h - float(rect.y0)),
                        (float(rect.x1), page_h - float(rect.y1)),
                        (float(rect.x0), page_h - float(rect.y1)),
                    ]
                    for i in range(4):
                        x1, y1 = corners[i]
                        x2, y2 = corners[(i + 1) % 4]
                        seg = VectorSegment(
                            x1=x1,
                            y1=y1,
                            x2=x2,
                            y2=y2,
                            width=width,
                            color=color,
                            is_dashed=is_dashed,
                        )
                        if seg.length >= self.min_segment_length_pt:
                            segments.append(seg)
                elif kind == "c":
                    # Cubic Bezier (often used for door swing arcs in CAD PDFs):
                    # Approximate with 4 chord segments for arc/door detection.
                    pts = self._sample_cubic_bezier(item[1], item[2], item[3], item[4], steps=4)
                    for i in range(len(pts) - 1):
                        seg = VectorSegment(
                            x1=pts[i][0],
                            y1=page_h - pts[i][1],
                            x2=pts[i + 1][0],
                            y2=page_h - pts[i + 1][1],
                            width=width,
                            color=color,
                            is_dashed=is_dashed,
                        )
                        if seg.length >= self.min_segment_length_pt:
                            segments.append(seg)
        return segments

    @staticmethod
    def _sample_cubic_bezier(p0, p1, p2, p3, steps: int = 4) -> list[tuple[float, float]]:
        pts = []
        for s in range(steps + 1):
            t = s / steps
            mt = 1.0 - t
            x = (
                mt**3 * p0.x
                + 3 * mt**2 * t * p1.x
                + 3 * mt * t**2 * p2.x
                + t**3 * p3.x
            )
            y = (
                mt**3 * p0.y
                + 3 * mt**2 * t * p1.y
                + 3 * mt * t**2 * p2.y
                + t**3 * p3.y
            )
            pts.append((float(x), float(y)))
        return pts

    @staticmethod
    def _extract_texts(page: pymupdf.Page, page_h: float) -> list[TextBlock]:
        """Extract text lines with precise bounding boxes in CAD Y-up coordinates."""
        blocks: list[TextBlock] = []
        page_dict = page.get_text("dict")
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                if not spans_text:
                    continue
                x0, y0, x1, y1 = line["bbox"]
                cad_bbox = BoundingBox(
                    x_min=float(x0),
                    y_min=page_h - float(y1),
                    x_max=float(x1),
                    y_max=page_h - float(y0),
                )
                blocks.append(TextBlock(text=spans_text, bbox=cad_bbox))
        return blocks

    def _cluster_regions(
        self,
        page_index: int,
        page_h: float,
        segments: list[VectorSegment],
        texts: list[TextBlock],
    ) -> list[ExtractedRegion]:
        """Group primary structural segments into distinct floor-plan bounding boxes."""
        primary = [s for s in segments if s.is_primary_structure and s.length < 400.0]
        if not primary:
            primary = [s for s in segments if not s.is_gray and s.length < 400.0]
        if not primary:
            return []

        # Grid-based connected components clustering on segment midpoints
        cell = max(10.0, self.cluster_gap_pt)
        grid: dict[tuple[int, int], list[int]] = {}
        for idx, seg in enumerate(primary):
            mid = seg.midpoint
            gx, gy = int(mid.x // cell), int(mid.y // cell)
            grid.setdefault((gx, gy), []).append(idx)

        visited_cells: set[tuple[int, int]] = set()
        clusters: list[list[int]] = []

        for start_cell in grid:
            if start_cell in visited_cells:
                continue
            queue = [start_cell]
            visited_cells.add(start_cell)
            comp_indices: list[int] = []
            while queue:
                cx, cy = queue.pop()
                comp_indices.extend(grid[(cx, cy)])
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nb = (cx + dx, cy + dy)
                        if nb in grid and nb not in visited_cells:
                            visited_cells.add(nb)
                            queue.append(nb)
            if len(comp_indices) >= self.min_region_segments:
                clusters.append(comp_indices)

        # Sort clusters left-to-right, top-to-bottom (in CAD Y-up: higher y first, lower x first)
        def cluster_sort_key(indices: list[int]) -> tuple[float, float]:
            xs = [primary[i].midpoint.x for i in indices]
            ys = [primary[i].midpoint.y for i in indices]
            return (-round(sum(ys) / len(ys) / 100.0), sum(xs) / len(xs))

        clusters.sort(key=cluster_sort_key)

        regions: list[ExtractedRegion] = []
        margin = 45.0  # Include surrounding dimension lines and floor labels
        for idx, comp in enumerate(clusters):
            xs = [primary[i].x1 for i in comp] + [primary[i].x2 for i in comp]
            ys = [primary[i].y1 for i in comp] + [primary[i].y2 for i in comp]
            bbox = BoundingBox(
                x_min=min(xs) - margin,
                y_min=min(ys) - margin,
                x_max=max(xs) + margin,
                y_max=max(ys) + margin,
            )
            reg_segs = [
                s
                for s in segments
                if bbox.x_min <= s.midpoint.x <= bbox.x_max
                and bbox.y_min <= s.midpoint.y <= bbox.y_max
            ]
            reg_texts = [
                t
                for t in texts
                if bbox.x_min <= t.center.x <= bbox.x_max
                and bbox.y_min <= t.center.y <= bbox.y_max
            ]
            pdf_rect = (
                bbox.x_min,
                max(0.0, page_h - bbox.y_max),
                bbox.x_max,
                max(0.0, page_h - bbox.y_min),
            )
            floor_name = self._guess_floor_name(texts, bbox, idx)
            regions.append(
                ExtractedRegion(
                    region_id=f"floor_{page_index}_{idx + 1}",
                    page_index=page_index,
                    pdf_rect=pdf_rect,
                    cad_bbox=bbox,
                    segments=reg_segs,
                    texts=reg_texts,
                    suggested_floor_name=floor_name,
                )
            )
        return regions

    @staticmethod
    def _guess_floor_name(
        all_texts: list[TextBlock],
        bbox: BoundingBox,
        idx: int,
    ) -> str:
        """Guess floor name from architectural floor labels inside or just below the region."""
        floor_keywords = (
            "begane grond",
            "verdieping",
            "zolder",
            "kelder",
            "ground floor",
            "first floor",
            "second floor",
            "tầng trệt",
            "tầng 1",
            "tầng 2",
            "lầu",
        )
        # Search inside region or within 90pt below/above with X overlap
        nearby = [
            tb
            for tb in all_texts
            if (bbox.x_min - 50.0) <= tb.center.x <= (bbox.x_max + 50.0)
            and (bbox.y_min - 90.0) <= tb.center.y <= (bbox.y_max + 60.0)
        ]
        nearby.sort(key=lambda t: t.center.y)
        for tb in nearby:
            low = tb.text.lower()
            if any(kw in low for kw in floor_keywords) and len(tb.text) < 40:
                return tb.text.strip()
        return f"Floor {idx + 1}"
