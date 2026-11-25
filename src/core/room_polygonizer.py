"""Room Polygonizer using Shapely planar subdivision & semantic label matching."""

from __future__ import annotations

import logging
import math
from typing import Optional

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

from src.core.schema import Corner, Space, Wall
from src.llm.heuristic_parser import PositionedRoomHint

logger = logging.getLogger(__name__)


class RoomPolygonizer:
    """Converts a solved wall-corner graph into closed Room Polygons with area cross-validation."""

    def __init__(
        self,
        min_room_area_m2: float = 0.85,
        label_fallback_dist_mm: float = 600.0,
    ) -> None:
        self.min_room_area_m2 = min_room_area_m2
        self.label_fallback_dist_mm = label_fallback_dist_mm

    def extract_spaces(
        self,
        corners: list[Corner],
        walls: list[Wall],
        room_hints: list[PositionedRoomHint] | None = None,
        mm_per_pt: float = 1.0,
        origin_offset_mm: tuple[float, float] = (0.0, 0.0),
    ) -> list[Space]:
        """Polygonize wall graph into closed Spaces and match semantic room hints."""
        if not corners or not walls:
            return []

        corner_map = {c.id: c for c in corners}
        lines = []
        for w in walls:
            c1, c2 = corner_map.get(w.corner_start_id), corner_map.get(w.corner_end_id)
            if c1 and c2 and (c1.x != c2.x or c1.y != c2.y):
                lines.append(LineString([(c1.x, c1.y), (c2.x, c2.y)]))

        if not lines:
            return []

        # Bridge dangling endpoints (door/window gaps) with virtual closure edges
        # so polygonize() produces watertight rooms without altering real walls.
        closures = self._bridge_openings(corners, walls, max_gap_mm=2600.0)
        merged_lines = unary_union(lines + closures)
        raw_polys = list(polygonize(merged_lines))
        valid_polys: list[Polygon] = [
            p for p in raw_polys if (p.area / 1_000_000.0) >= self.min_room_area_m2
        ]

        # Scale room hints to solved mm coordinate space
        ox, oy = origin_offset_mm
        scaled_hints: list[tuple[PositionedRoomHint, Point]] = []
        for hint in room_hints or []:
            pt = Point(hint.center.x * mm_per_pt - ox, hint.center.y * mm_per_pt - oy)
            scaled_hints.append((hint, pt))

        used_hints: set[int] = set()
        poly_to_hint: dict[int, int] = {}

        # Pass 1: Strict Point-in-Polygon across all polygons first
        for idx, poly in enumerate(valid_polys):
            for h_idx, (_, pt) in enumerate(scaled_hints):
                if h_idx in used_hints:
                    continue
                if poly.contains(pt) or poly.buffer(20.0).contains(pt):
                    poly_to_hint[idx] = h_idx
                    used_hints.add(h_idx)
                    break

        # Pass 2: Nearest-polygon fallback only for unmatched hints & unmatched polygons
        for idx, poly in enumerate(valid_polys):
            if idx in poly_to_hint:
                continue
            best_h: Optional[int] = None
            best_d = self.label_fallback_dist_mm
            for h_idx, (_, pt) in enumerate(scaled_hints):
                if h_idx in used_hints:
                    continue
                d = poly.exterior.distance(pt)
                if d < best_d:
                    best_d = d
                    best_h = h_idx
            if best_h is not None:
                poly_to_hint[idx] = best_h
                used_hints.add(best_h)

        spaces: list[Space] = []
        for idx, poly in enumerate(valid_polys):
            calc_area_m2 = round(poly.area / 1_000_000.0, 2)
            boundary_ids = self._match_polygon_corners(poly, corners)
            matched_idx = poly_to_hint.get(idx)

            if matched_idx is not None:
                hint = scaled_hints[matched_idx][0]
                name = hint.name
                name_vn = hint.name_vn
                category = hint.category
                nom_area = hint.nominal_area_m2
            else:
                name = f"Room {idx + 1}"
                name_vn = f"Phòng {idx + 1}"
                category = "other"
                nom_area = None

            err_pct: Optional[float] = None
            if nom_area and nom_area > 0:
                err_pct = round(abs(calc_area_m2 - nom_area) / nom_area * 100.0, 2)

            spaces.append(
                Space(
                    id=f"space_{idx + 1}",
                    name=name,
                    name_vn=name_vn,
                    category=category,
                    nominal_area_m2=nom_area,
                    calculated_area_m2=calc_area_m2,
                    boundary_corner_ids=boundary_ids,
                    area_error_pct=err_pct,
                )
            )

        logger.info("RoomPolygonizer: extracted %d closed spaces", len(spaces))
        return spaces

    @staticmethod
    def _bridge_openings(
        corners: list[Corner],
        walls: list[Wall],
        max_gap_mm: float = 2600.0,
    ) -> list[LineString]:
        """Create virtual closure segments across door/window gaps.

        Prioritizes extending each dangling endpoint along its own wall direction
        so doorways/windows close straight across rather than cutting diagonally.
        """
        adj: dict[str, list[Wall]] = {c.id: [] for c in corners}
        for w in walls:
            adj.setdefault(w.corner_start_id, []).append(w)
            adj.setdefault(w.corner_end_id, []).append(w)

        corner_map = {c.id: c for c in corners}
        dangling = [
            corner_map[cid]
            for cid, wlist in adj.items()
            if len(wlist) == 1 and cid in corner_map
        ]
        if not dangling:
            return []

        closures: list[LineString] = []
        used: set[str] = set()

        # Pass 1: Extend dangling endpoint along its own wall outward direction
        for c in dangling:
            w = adj[c.id][0]
            other_id = w.corner_end_id if w.corner_start_id == c.id else w.corner_start_id
            other = corner_map.get(other_id)
            if not other:
                continue
            dx, dy = c.x - other.x, c.y - other.y
            wlen = math.hypot(dx, dy)
            if wlen < 1e-6:
                continue
            ox, oy = dx / wlen, dy / wlen  # Outward unit vector

            best_t = max_gap_mm + 1.0
            best_hit: Optional[tuple[float, float]] = None

            # Raycast against all other walls
            for tw in walls:
                if tw.id == w.id:
                    continue
                a, b = corner_map[tw.corner_start_id], corner_map[tw.corner_end_id]
                qdx, qdy = b.x - a.x, b.y - a.y
                denom = ox * qdy - oy * qdx
                if abs(denom) < 1e-6:
                    continue
                rx, ry = a.x - c.x, a.y - c.y
                t = (rx * qdy - ry * qdx) / denom
                u = (rx * oy - ry * ox) / denom
                if 20.0 <= t <= max_gap_mm and -0.05 <= u <= 1.05:
                    if t < best_t:
                        best_t = t
                        best_hit = (c.x + t * ox, c.y + t * oy)

            # Also check collinear dangling endpoints directly ahead
            for c2 in dangling:
                if c2.id == c.id:
                    continue
                vx, vy = c2.x - c.x, c2.y - c.y
                dist = math.hypot(vx, vy)
                if 20.0 <= dist <= max_gap_mm:
                    proj = vx * ox + vy * oy
                    perp = abs(vx * (-oy) + vy * ox)
                    if proj > 0 and perp <= 120.0 and dist < best_t:
                        best_t = dist
                        best_hit = (c2.x, c2.y)

            if best_hit is not None:
                closures.append(LineString([(c.x, c.y), best_hit]))
                used.add(c.id)

        # Pass 2: Fallback nearest-pair for any remaining dangling endpoints (e.g. corner windows)
        remaining = [c for c in dangling if c.id not in used]
        pairs: list[tuple[float, Corner, Corner]] = []
        for i in range(len(remaining)):
            for j in range(i + 1, len(remaining)):
                c1, c2 = remaining[i], remaining[j]
                dist = math.hypot(c2.x - c1.x, c2.y - c1.y)
                if 20.0 <= dist <= max_gap_mm:
                    pairs.append((dist, c1, c2))
        pairs.sort(key=lambda item: item[0])

        for _, c1, c2 in pairs:
            if c1.id in used or c2.id in used:
                continue
            closures.append(LineString([(c1.x, c1.y), (c2.x, c2.y)]))
            used.add(c1.id)
            used.add(c2.id)

        return closures

    @staticmethod
    def _match_polygon_corners(poly: Polygon, corners: list[Corner]) -> list[str]:
        """Map exterior ring vertices back to Corner IDs."""
        coords = list(poly.exterior.coords)[:-1]
        ids: list[str] = []
        for x, y in coords:
            best_c = min(corners, key=lambda c: math.hypot(c.x - x, c.y - y))
            if math.hypot(best_c.x - x, best_c.y - y) <= 50.0:
                if not ids or ids[-1] != best_c.id:
                    ids.append(best_c.id)
        return ids
