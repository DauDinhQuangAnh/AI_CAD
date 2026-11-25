"""Vector Geometry Parser for clean CAD-generated PDFs.

Extracts wall centerlines (with thickness) from parallel line pairs after
collinear segment merging, and detects swing doors / window openings.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Literal, Optional

from src.core.schema import Point2D
from src.preprocessor.pdf_extractor import VectorSegment

logger = logging.getLogger(__name__)


@dataclass
class RawWallSegment:
    """Extracted wall centerline in millimeters prior to topological snapping."""

    start: Point2D
    end: Point2D
    thickness_mm: float
    wall_type: Literal["exterior", "interior", "bearing"] = "interior"

    @property
    def length_mm(self) -> float:
        return math.hypot(self.end.x - self.start.x, self.end.y - self.start.y)


@dataclass
class RawOpeningCandidate:
    """Detected door or window candidate in millimeters."""

    opening_type: Literal["swing_door", "sliding_door", "window", "opening"]
    center: Point2D
    width_mm: float


class VectorGeometryParser:
    """Parses scaled PDF vector segments into wall centerlines and opening candidates."""

    def __init__(
        self,
        min_wall_thickness_mm: float = 60.0,
        max_wall_thickness_mm: float = 450.0,
        min_wall_length_mm: float = 250.0,
        collinear_angle_tol_deg: float = 1.5,
        collinear_offset_tol_mm: float = 10.0,
        collinear_gap_tol_mm: float = 25.0,
    ) -> None:
        self.min_wall_thickness_mm = min_wall_thickness_mm
        self.max_wall_thickness_mm = max_wall_thickness_mm
        self.min_wall_length_mm = min_wall_length_mm
        self.collinear_angle_tol_deg = collinear_angle_tol_deg
        self.collinear_offset_tol_mm = collinear_offset_tol_mm
        self.collinear_gap_tol_mm = collinear_gap_tol_mm

    def parse(
        self,
        segments_pt: list[VectorSegment],
        mm_per_pt: float,
    ) -> tuple[list[RawWallSegment], list[RawOpeningCandidate]]:
        """Convert PDF-point segments into millimeter wall centerlines and openings."""
        if mm_per_pt <= 0:
            raise ValueError("mm_per_pt must be positive")

        # Scale primary structural segments to millimeters
        scaled_struct: list[tuple[float, float, float, float, bool]] = []
        scaled_all: list[tuple[float, float, float, float, float]] = []

        for seg in segments_pt:
            x1, y1 = seg.x1 * mm_per_pt, seg.y1 * mm_per_pt
            x2, y2 = seg.x2 * mm_per_pt, seg.y2 * mm_per_pt
            length_mm = math.hypot(x2 - x1, y2 - y1)
            if length_mm < 15.0:
                continue
            scaled_all.append((x1, y1, x2, y2, seg.width))
            if seg.is_primary_structure:
                is_red = seg.color[0] > 0.7 and seg.color[1] < 0.25
                scaled_struct.append((x1, y1, x2, y2, is_red))

        merged = self._merge_collinear(scaled_struct)
        walls = self._extract_parallel_walls(merged)
        walls = self._deduplicate_walls(walls)
        walls = self._filter_stair_treads(walls)
        openings = self._detect_openings(scaled_all, walls)

        logger.info(
            "VectorGeometryParser: %d struct segs -> %d merged -> %d walls, %d openings",
            len(scaled_struct),
            len(merged),
            len(walls),
            len(openings),
        )
        return walls, openings

    def _merge_collinear(
        self,
        segs: list[tuple[float, float, float, float, bool]],
    ) -> list[tuple[float, float, float, float, bool]]:
        """Merge collinear touching/overlapping segments into continuous lines."""
        # Represent each line by unit direction (ux, uy) in [0, 180) and signed normal offset d
        buckets: list[tuple[float, float, float, list[tuple[float, float, bool]]]] = []

        for x1, y1, x2, y2, is_red in segs:
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 1e-6:
                continue
            ux, uy = dx / length, dy / length
            # Canonicalize direction to [0, pi)
            if uy < -1e-6 or (abs(uy) <= 1e-6 and ux < 0):
                ux, uy = -ux, -uy
            # Normal vector (-uy, ux)
            nx, ny = -uy, ux
            offset = x1 * nx + y1 * ny
            t1 = x1 * ux + y1 * uy
            t2 = x2 * ux + y2 * uy
            t_min, t_max = min(t1, t2), max(t1, t2)

            placed = False
            for bux, buy, boff, intervals in buckets:
                dot = max(-1.0, min(1.0, bux * ux + buy * uy))
                ang_diff = math.degrees(math.acos(abs(dot)))
                if ang_diff <= self.collinear_angle_tol_deg and abs(offset - boff) <= self.collinear_offset_tol_mm:
                    intervals.append((t_min, t_max, is_red))
                    placed = True
                    break
            if not placed:
                buckets.append((ux, uy, offset, [(t_min, t_max, is_red)]))

        merged: list[tuple[float, float, float, float, bool]] = []
        for ux, uy, offset, intervals in buckets:
            nx, ny = -uy, ux
            intervals.sort(key=lambda item: item[0])
            cur_s, cur_e, cur_red = intervals[0]
            for s, e, r in intervals[1:]:
                if s <= cur_e + self.collinear_gap_tol_mm:
                    cur_e = max(cur_e, e)
                    cur_red = cur_red or r
                else:
                    if cur_e - cur_s >= 40.0:
                        merged.append(
                            (
                                ux * cur_s + nx * offset,
                                uy * cur_s + ny * offset,
                                ux * cur_e + nx * offset,
                                uy * cur_e + ny * offset,
                                cur_red,
                            )
                        )
                    cur_s, cur_e, cur_red = s, e, r
            if cur_e - cur_s >= 40.0:
                merged.append(
                    (
                        ux * cur_s + nx * offset,
                        uy * cur_s + ny * offset,
                        ux * cur_e + nx * offset,
                        uy * cur_e + ny * offset,
                        cur_red,
                    )
                )
        return merged

    def _extract_parallel_walls(
        self,
        merged: list[tuple[float, float, float, float, bool]],
    ) -> list[RawWallSegment]:
        """Pair parallel wall faces separated by architectural wall thickness."""
        walls: list[RawWallSegment] = []
        n = len(merged)
        # Precompute unit vectors, offsets, and parameter ranges
        meta = []
        for x1, y1, x2, y2, is_red in merged:
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            ux, uy = dx / length, dy / length
            if uy < -1e-6 or (abs(uy) <= 1e-6 and ux < 0):
                ux, uy = -ux, -uy
            nx, ny = -uy, ux
            off = x1 * nx + y1 * ny
            t1, t2 = x1 * ux + y1 * uy, x2 * ux + y2 * uy
            meta.append((ux, uy, nx, ny, off, min(t1, t2), max(t1, t2), is_red))

        for i in range(n):
            ux1, uy1, nx1, ny1, off1, s1, e1, red1 = meta[i]
            if e1 - s1 < self.min_wall_length_mm * 0.6:
                continue
            for j in range(i + 1, n):
                ux2, uy2, _, _, off2, s2, e2, red2 = meta[j]
                dot = max(-1.0, min(1.0, ux1 * ux2 + uy1 * uy2))
                ang_diff = math.degrees(math.acos(abs(dot)))
                if ang_diff > self.collinear_angle_tol_deg:
                    continue

                # Signed distance along normal
                # Re-project midpoint of j onto normal 1 for accuracy
                mid_x = (merged[j][0] + merged[j][2]) / 2.0
                mid_y = (merged[j][1] + merged[j][3]) / 2.0
                off2_in_1 = mid_x * nx1 + mid_y * ny1
                thickness = abs(off2_in_1 - off1)

                if not (self.min_wall_thickness_mm <= thickness <= self.max_wall_thickness_mm):
                    continue

                ov_s = max(s1, s2)
                ov_e = min(e1, e2)
                if ov_e - ov_s < self.min_wall_length_mm:
                    continue

                mid_off = (off1 + off2_in_1) / 2.0
                cx1 = ux1 * ov_s + nx1 * mid_off
                cy1 = uy1 * ov_s + ny1 * mid_off
                cx2 = ux1 * ov_e + nx1 * mid_off
                cy2 = uy1 * ov_e + ny1 * mid_off

                wall_type: Literal["exterior", "interior", "bearing"] = (
                    "exterior" if thickness >= 220.0 else "interior"
                )
                walls.append(
                    RawWallSegment(
                        start=Point2D(x=cx1, y=cy1),
                        end=Point2D(x=cx2, y=cy2),
                        thickness_mm=round(thickness, 1),
                        wall_type=wall_type,
                    )
                )
        return walls

    def _deduplicate_walls(self, walls: list[RawWallSegment]) -> list[RawWallSegment]:
        """Remove duplicate/overlapping centerlines (e.g., from multi-layer cavity walls)."""
        if not walls:
            return []
        # Sort longest first so major walls win
        ordered = sorted(walls, key=lambda w: w.length_mm, reverse=True)
        kept: list[RawWallSegment] = []

        for cand in ordered:
            cdx = cand.end.x - cand.start.x
            cdy = cand.end.y - cand.start.y
            clen = math.hypot(cdx, cdy)
            if clen < self.min_wall_length_mm:
                continue
            cux, cuy = cdx / clen, cdy / clen
            cmid_x = (cand.start.x + cand.end.x) / 2.0
            cmid_y = (cand.start.y + cand.end.y) / 2.0

            duplicate = False
            for k in kept:
                kdx = k.end.x - k.start.x
                kdy = k.end.y - k.start.y
                klen = math.hypot(kdx, kdy)
                kux, kuy = kdx / klen, kdy / klen
                dot = abs(cux * kux + cuy * kuy)
                if dot < 0.995:
                    continue
                # Perpendicular distance between midpoints
                knx, kny = -kuy, kux
                perp = abs((cmid_x - k.start.x) * knx + (cmid_y - k.start.y) * kny)
                if perp > 220.0:
                    continue
                # Check longitudinal overlap
                ks, ke = 0.0, klen
                cs = (cand.start.x - k.start.x) * kux + (cand.start.y - k.start.y) * kuy
                ce = (cand.end.x - k.start.x) * kux + (cand.end.y - k.start.y) * kuy
                cs, ce = min(cs, ce), max(cs, ce)
                overlap = min(ke, ce) - max(ks, cs)
                if overlap > 0.65 * clen:
                    duplicate = True
                    break

            if not duplicate:
                kept.append(cand)
        return kept

    @staticmethod
    def _filter_stair_treads(walls: list[RawWallSegment]) -> list[RawWallSegment]:
        """Remove repeating parallel stair-tread lines misclassified as thin walls."""
        if len(walls) < 4:
            return walls
        to_remove: set[int] = set()
        for i, wi in enumerate(walls):
            if i in to_remove:
                continue
            li = wi.length_mm
            if li > 1800.0:
                continue
            dxi, dyi = (wi.end.x - wi.start.x) / li, (wi.end.y - wi.start.y) / li
            nxi, nyi = -dyi, dxi
            mi_x, mi_y = (wi.start.x + wi.end.x) / 2.0, (wi.start.y + wi.end.y) / 2.0

            group = [i]
            for j, wj in enumerate(walls):
                if j == i or j in to_remove:
                    continue
                lj = wj.length_mm
                if abs(lj - li) > 80.0:
                    continue
                dxj, dyj = (wj.end.x - wj.start.x) / lj, (wj.end.y - wj.start.y) / lj
                if abs(dxi * dxj + dyi * dyj) < 0.995:
                    continue
                mj_x, mj_y = (wj.start.x + wj.end.x) / 2.0, (wj.start.y + wj.end.y) / 2.0
                # Longitudinal shift should be small, perpendicular shift <= 1500 mm
                along = abs((mj_x - mi_x) * dxi + (mj_y - mi_y) * dyi)
                perp = abs((mj_x - mi_x) * nxi + (mj_y - mi_y) * nyi)
                if along < 120.0 and 120.0 <= perp <= 1800.0:
                    group.append(j)

            if len(group) >= 4:
                to_remove.update(group)

        if to_remove:
            logger.info("Filtered %d stair-tread false wall segments", len(to_remove))
        return [w for idx, w in enumerate(walls) if idx not in to_remove]

    def _detect_openings(
        self,
        scaled_all: list[tuple[float, float, float, float, float]],
        walls: list[RawWallSegment],
    ) -> list[RawOpeningCandidate]:
        """Detect swing doors / windows near walls (heuristic chord & thin-line detection)."""
        # Look for thin (width < 0.4) segments of typical door-leaf length (650-1150 mm)
        # that touch or lie close to a wall centerline at a ~45-90 deg angle.
        openings: list[RawOpeningCandidate] = []
        used_centers: list[Point2D] = []

        for x1, y1, x2, y2, width in scaled_all:
            if width >= 0.45:
                continue
            length = math.hypot(x2 - x1, y2 - y1)
            if not (650.0 <= length <= 1150.0):
                continue

            # Check if one endpoint is close to any wall centerline and angle is >= 35 deg
            dx, dy = (x2 - x1) / length, (y2 - y1) / length
            for w in walls:
                wdx = w.end.x - w.start.x
                wdy = w.end.y - w.start.y
                wlen = math.hypot(wdx, wdy)
                if wlen < 1e-6:
                    continue
                wux, wuy = wdx / wlen, wdy / wlen
                dot = abs(dx * wux + dy * wuy)
                if dot > 0.35:  # Must be roughly perpendicular/angled to wall, not parallel
                    continue

                d1 = self._point_to_seg_dist(x1, y1, w.start.x, w.start.y, w.end.x, w.end.y)
                d2 = self._point_to_seg_dist(x2, y2, w.start.x, w.start.y, w.end.x, w.end.y)
                min_d = min(d1, d2)
                if min_d <= w.thickness_mm + 80.0:
                    hinge = Point2D(x=x1, y=y1) if d1 <= d2 else Point2D(x=x2, y=y2)
                    # Project hinge + half door width along wall
                    if any(math.hypot(hinge.x - u.x, hinge.y - u.y) < 350.0 for u in used_centers):
                        break
                    used_centers.append(hinge)
                    openings.append(
                        RawOpeningCandidate(
                            opening_type="swing_door",
                            center=hinge,
                            width_mm=round(length, 1),
                        )
                    )
                    break

        return openings

    @staticmethod
    def _point_to_seg_dist(
        px: float, py: float, x1: float, y1: float, x2: float, y2: float
    ) -> float:
        dx, dy = x2 - x1, y2 - y1
        l2 = dx * dx + dy * dy
        if l2 < 1e-9:
            return math.hypot(px - x1, py - y1)
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return math.hypot(px - proj_x, py - proj_y)
