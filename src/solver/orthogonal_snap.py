"""Geometric Constraint Solver: Orthogonal Snapping, L/T-Junction Extension, and Vertex Clustering."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

from src.core.schema import Corner, Opening, Point2D, Wall
from src.vision.vector_geometry import RawOpeningCandidate, RawWallSegment

logger = logging.getLogger(__name__)


@dataclass
class SolvedGeometry:
    """Topologically clean wall-corner graph in millimeters."""

    corners: list[Corner]
    walls: list[Wall]
    openings: list[Opening]
    origin_offset_mm: tuple[float, float] = (0.0, 0.0)


class OrthogonalSnapSolver:
    """Solves wall-network topology to eliminate gaps and enforce clean junctions."""

    def __init__(
        self,
        angle_snap_deg: float = 1.5,
        axis_align_tol_mm: float = 70.0,
        junction_extend_tol_mm: float = 320.0,
        vertex_cluster_tol_mm: float = 85.0,
        normalize_origin: bool = True,
    ) -> None:
        self.angle_snap_deg = angle_snap_deg
        self.axis_align_tol_mm = axis_align_tol_mm
        self.junction_extend_tol_mm = junction_extend_tol_mm
        self.vertex_cluster_tol_mm = vertex_cluster_tol_mm
        self.normalize_origin = normalize_origin

    def solve(
        self,
        raw_walls: list[RawWallSegment],
        raw_openings: list[RawOpeningCandidate] | None = None,
    ) -> SolvedGeometry:
        """Snap angles, align axes, extend L/T junctions, cluster vertices, and attach openings."""
        if not raw_walls:
            return SolvedGeometry(corners=[], walls=[], openings=[])

        # 1. Conservative orthogonal snap around each wall's midpoint
        snapped: list[list[float]] = []  # [x1, y1, x2, y2, thickness, wall_type]
        for w in raw_walls:
            x1, y1, x2, y2 = self._snap_angle(w.start.x, w.start.y, w.end.x, w.end.y)
            snapped.append([x1, y1, x2, y2, w.thickness_mm, w.wall_type])

        # 2. Align near-collinear horizontal/vertical wall axes
        self._align_axes(snapped)

        # 3. Extend endpoints to nearby perpendicular/intersecting walls (L and T junctions)
        self._extend_to_junctions(snapped)

        # 4. Cluster nearby endpoints into canonical Corner vertices
        corners, walls = self._build_graph(snapped)

        # 5. Normalize origin to (0, 0) if requested
        if self.normalize_origin and corners:
            min_x = min(c.x for c in corners)
            min_y = min(c.y for c in corners)
            for c in corners:
                c.x = round(c.x - min_x, 1)
                c.y = round(c.y - min_y, 1)
        else:
            min_x, min_y = 0.0, 0.0

        # 6. Attach opening candidates to nearest walls
        openings = self._attach_openings(
            raw_openings or [],
            corners,
            walls,
            offset_x=min_x,
            offset_y=min_y,
        )

        logger.info(
            "OrthogonalSnapSolver: %d raw walls -> %d corners, %d walls, %d openings",
            len(raw_walls),
            len(corners),
            len(walls),
            len(openings),
        )
        return SolvedGeometry(
            corners=corners,
            walls=walls,
            openings=openings,
            origin_offset_mm=(min_x, min_y),
        )

    def _snap_angle(
        self, x1: float, y1: float, x2: float, y2: float
    ) -> tuple[float, float, float, float]:
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return x1, y1, x2, y2
        ang = math.degrees(math.atan2(dy, dx)) % 180.0
        mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0

        if ang <= self.angle_snap_deg or ang >= 180.0 - self.angle_snap_deg:
            # Snap to horizontal
            half = length / 2.0
            sx1, sx2 = (mx - half, mx + half) if x1 <= x2 else (mx + half, mx - half)
            return sx1, my, sx2, my
        if abs(ang - 90.0) <= self.angle_snap_deg:
            # Snap to vertical
            half = length / 2.0
            sy1, sy2 = (my - half, my + half) if y1 <= y2 else (my + half, my - half)
            return mx, sy1, mx, sy2
        return x1, y1, x2, y2

    def _align_axes(self, segs: list[list[float]]) -> None:
        """Snap near-collinear horizontal Ys and vertical Xs to shared grid lines."""
        horiz_ys: list[tuple[int, float]] = []
        vert_xs: list[tuple[int, float]] = []
        for idx, s in enumerate(segs):
            if abs(s[1] - s[3]) < 1e-3:
                horiz_ys.append((idx, s[1]))
            elif abs(s[0] - s[2]) < 1e-3:
                vert_xs.append((idx, s[0]))

        # Group horizontal Ys
        horiz_ys.sort(key=lambda item: item[1])
        self._cluster_1d(horiz_ys, self.axis_align_tol_mm, segs, coord_indices=(1, 3))

        # Group vertical Xs
        vert_xs.sort(key=lambda item: item[1])
        self._cluster_1d(vert_xs, self.axis_align_tol_mm, segs, coord_indices=(0, 2))

    @staticmethod
    def _cluster_1d(
        items: list[tuple[int, float]],
        tol: float,
        segs: list[list[float]],
        coord_indices: tuple[int, int],
    ) -> None:
        if not items:
            return
        group: list[tuple[int, float]] = [items[0]]
        for idx, val in items[1:]:
            if abs(val - group[-1][1]) <= tol:
                group.append((idx, val))
            else:
                mean_val = sum(v for _, v in group) / len(group)
                for g_idx, _ in group:
                    segs[g_idx][coord_indices[0]] = mean_val
                    segs[g_idx][coord_indices[1]] = mean_val
                group = [(idx, val)]
        mean_val = sum(v for _, v in group) / len(group)
        for g_idx, _ in group:
            segs[g_idx][coord_indices[0]] = mean_val
            segs[g_idx][coord_indices[1]] = mean_val

    def _extend_to_junctions(self, segs: list[list[float]]) -> None:
        """Extend wall endpoints slightly along their line to meet intersecting walls."""
        n = len(segs)
        tol = self.junction_extend_tol_mm
        for i in range(n):
            x1, y1, x2, y2 = segs[i][:4]
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 1e-3:
                continue
            ux, uy = dx / length, dy / length

            for end_idx in (0, 1):
                px, py = (x1, y1) if end_idx == 0 else (x2, y2)
                # Outward unit vector from this endpoint
                ox, oy = (-ux, -uy) if end_idx == 0 else (ux, uy)

                best_t = tol + 1.0
                best_pt: Optional[tuple[float, float]] = None

                for j in range(n):
                    if i == j:
                        continue
                    qx1, qy1, qx2, qy2 = segs[j][:4]
                    qdx, qdy = qx2 - qx1, qy2 - qy1
                    denom = ox * qdy - oy * qdx
                    if abs(denom) < 1e-6:
                        continue  # parallel
                    rx, ry = qx1 - px, qy1 - py
                    t = (rx * qdy - ry * qdx) / denom
                    u = (rx * oy - ry * ox) / denom
                    # Allow small overshoot on target segment u in [-0.05, 1.05] or tol
                    qlen = math.hypot(qdx, qdy)
                    u_margin = tol / max(qlen, 1.0)
                    if -self.vertex_cluster_tol_mm <= t <= tol and -u_margin <= u <= 1.0 + u_margin:
                        if abs(t) < best_t:
                            best_t = abs(t)
                            best_pt = (px + t * ox, py + t * oy)

                if best_pt is not None:
                    if end_idx == 0:
                        segs[i][0], segs[i][1] = best_pt
                    else:
                        segs[i][2], segs[i][3] = best_pt

    def _build_graph(self, segs: list[list[float]]) -> tuple[list[Corner], list[Wall]]:
        """Cluster endpoints into Corners, split T-junctions, and emit Walls."""
        raw_pts: list[tuple[float, float]] = []
        for s in segs:
            raw_pts.append((s[0], s[1]))
            raw_pts.append((s[2], s[3]))

        # Simple greedy clustering of points within vertex_cluster_tol_mm
        clusters: list[list[tuple[float, float]]] = []
        for pt in raw_pts:
            placed = False
            for cl in clusters:
                cx = sum(p[0] for p in cl) / len(cl)
                cy = sum(p[1] for p in cl) / len(cl)
                if math.hypot(pt[0] - cx, pt[1] - cy) <= self.vertex_cluster_tol_mm:
                    cl.append(pt)
                    placed = True
                    break
            if not placed:
                clusters.append([pt])

        corners: list[Corner] = []
        for idx, cl in enumerate(clusters):
            cx = round(sum(p[0] for p in cl) / len(cl), 1)
            cy = round(sum(p[1] for p in cl) / len(cl), 1)
            corners.append(Corner(id=f"c{idx + 1}", x=cx, y=cy, elevation=0.0))

        def nearest_corner(x: float, y: float) -> str:
            best_c = min(corners, key=lambda c: math.hypot(c.x - x, c.y - y))
            return best_c.id

        # Split walls at any interior T-junction corners
        corner_map = {c.id: c for c in corners}
        walls: list[Wall] = []
        w_counter = 1
        seen_edges: set[tuple[str, str]] = set()

        for s in segs:
            c_start = nearest_corner(s[0], s[1])
            c_end = nearest_corner(s[2], s[3])
            if c_start == c_end:
                continue

            cs, ce = corner_map[c_start], corner_map[c_end]
            dx, dy = ce.x - cs.x, ce.y - cs.y
            seg_len = math.hypot(dx, dy)
            if seg_len < 50.0:
                continue

            # Find any corners lying strictly inside this wall segment (T-junctions)
            interior: list[tuple[float, str]] = []
            for c in corners:
                if c.id in (c_start, c_end):
                    continue
                proj = ((c.x - cs.x) * dx + (c.y - cs.y) * dy) / (seg_len * seg_len)
                if 0.02 < proj < 0.98:
                    px = cs.x + proj * dx
                    py = cs.y + proj * dy
                    if math.hypot(c.x - px, c.y - py) <= self.vertex_cluster_tol_mm:
                        interior.append((proj, c.id))

            chain = [c_start] + [cid for _, cid in sorted(interior)] + [c_end]
            for k in range(len(chain) - 1):
                a, b = chain[k], chain[k + 1]
                if a == b:
                    continue
                edge_key = (min(a, b), max(a, b))
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                walls.append(
                    Wall(
                        id=f"w{w_counter}",
                        corner_start_id=a,
                        corner_end_id=b,
                        wall_type=s[5],
                        thickness=round(float(s[4]), 1),
                        height=2800.0,
                    )
                )
                w_counter += 1

        return corners, walls

    @staticmethod
    def _attach_openings(
        raw_openings: list[RawOpeningCandidate],
        corners: list[Corner],
        walls: list[Wall],
        offset_x: float,
        offset_y: float,
    ) -> list[Opening]:
        if not raw_openings or not walls:
            return []
        corner_map = {c.id: c for c in corners}
        openings: list[Opening] = []
        for idx, cand in enumerate(raw_openings):
            px = cand.center.x - offset_x
            py = cand.center.y - offset_y
            best_wall: Optional[Wall] = None
            best_dist = float("inf")
            best_pos = 0.0

            for w in walls:
                c1, c2 = corner_map[w.corner_start_id], corner_map[w.corner_end_id]
                dx, dy = c2.x - c1.x, c2.y - c1.y
                l2 = dx * dx + dy * dy
                if l2 < 1e-6:
                    continue
                wlen = math.sqrt(l2)
                t = max(0.0, min(1.0, ((px - c1.x) * dx + (py - c1.y) * dy) / l2))
                qx, qy = c1.x + t * dx, c1.y + t * dy
                dist = math.hypot(px - qx, py - qy)
                if dist < best_dist and dist <= w.thickness + 150.0:
                    best_dist = dist
                    best_wall = w
                    best_pos = max(0.0, min(wlen - cand.width_mm, t * wlen))

            if best_wall is not None:
                openings.append(
                    Opening(
                        id=f"opening_{idx + 1}",
                        type=cand.opening_type,
                        wall_id=best_wall.id,
                        position_along_wall_mm=round(best_pos, 1),
                        width=round(cand.width_mm, 1),
                        height=2100.0,
                    )
                )
        return openings
