"""AutoCAD DXF Exporter using ezdxf with standard architectural CAD layers."""

from __future__ import annotations

import logging
import math
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

from src.core.schema import AICADDocument, Corner, FloorPlan, Opening, Wall

logger = logging.getLogger(__name__)

_LAYERS: list[tuple[str, int]] = [
    ("A-WALL-CORE", 7),   # White/Black
    ("A-WALL-OUTL", 8),   # Dark gray wall thickness outline
    ("A-DOOR", 1),        # Red
    ("A-GLAZ", 4),        # Cyan
    ("A-AREA", 3),        # Green room polygons
    ("A-ANNO-TEXT", 2),   # Yellow annotations
    ("A-ANNO-DIMS", 5),   # Blue dimensions
]


class DXFExporter:
    """Exports an AICADDocument into a layered AutoCAD R2010 DXF file in millimeters."""

    def export(self, doc: AICADDocument, output_path: str | Path) -> Path:
        """Write all floors of AICADDocument to a .dxf file."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        dxf_doc = ezdxf.new("R2010")
        dxf_doc.units = ezdxf.units.MM
        dxf_doc.header["$INSUNITS"] = 4  # Millimeters

        for layer_name, color in _LAYERS:
            if layer_name not in dxf_doc.layers:
                dxf_doc.layers.add(layer_name, color=color)

        msp = dxf_doc.modelspace()
        x_cursor = 0.0
        floor_gap_mm = 2500.0

        for floor in doc.floors:
            self._draw_floor(msp, floor, x_offset=x_cursor)
            floor_w = floor.bounding_box.width or 8000.0
            x_cursor += floor_w + floor_gap_mm

        dxf_doc.saveas(str(out))
        logger.info("Exported DXF to %s (%d floors)", out, len(doc.floors))
        return out

    def _draw_floor(self, msp, floor: FloorPlan, x_offset: float) -> None:
        corner_map: dict[str, Corner] = {c.id: c for c in floor.corners}

        # Floor title
        msp.add_text(
            floor.floor_name,
            height=250.0,
            dxfattribs={"layer": "A-ANNO-TEXT"},
        ).set_placement((x_offset, -600.0), align=TextEntityAlignment.LEFT)

        # Walls: centerline + parallel thickness outline
        wall_map: dict[str, Wall] = {}
        for w in floor.walls:
            wall_map[w.id] = w
            c1, c2 = corner_map.get(w.corner_start_id), corner_map.get(w.corner_end_id)
            if not c1 or not c2:
                continue
            p1 = (c1.x + x_offset, c1.y)
            p2 = (c2.x + x_offset, c2.y)
            msp.add_line(p1, p2, dxfattribs={"layer": "A-WALL-CORE"})

            dx, dy = c2.x - c1.x, c2.y - c1.y
            length = math.hypot(dx, dy)
            if length > 1e-3:
                nx, ny = (-dy / length) * (w.thickness / 2.0), (dx / length) * (w.thickness / 2.0)
                msp.add_line(
                    (p1[0] + nx, p1[1] + ny),
                    (p2[0] + nx, p2[1] + ny),
                    dxfattribs={"layer": "A-WALL-OUTL"},
                )
                msp.add_line(
                    (p1[0] - nx, p1[1] - ny),
                    (p2[0] - nx, p2[1] - ny),
                    dxfattribs={"layer": "A-WALL-OUTL"},
                )

        # Openings (doors & windows)
        for op in floor.openings:
            w = wall_map.get(op.wall_id)
            if not w:
                continue
            self._draw_opening(msp, op, w, corner_map, x_offset)

        # Room polygons & labels
        for sp in floor.spaces:
            pts = [
                (corner_map[cid].x + x_offset, corner_map[cid].y)
                for cid in sp.boundary_corner_ids
                if cid in corner_map
            ]
            if len(pts) >= 3:
                msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "A-AREA"})
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
                area_str = (
                    f"{sp.calculated_area_m2:.2f} m2"
                    if sp.calculated_area_m2 is not None
                    else ""
                )
                label = f"{sp.name} ({area_str})" if area_str else sp.name
                msp.add_text(
                    label,
                    height=150.0,
                    dxfattribs={"layer": "A-ANNO-TEXT"},
                ).set_placement((cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)

    @staticmethod
    def _draw_opening(
        msp,
        op: Opening,
        wall: Wall,
        corner_map: dict[str, Corner],
        x_offset: float,
    ) -> None:
        c1, c2 = corner_map.get(wall.corner_start_id), corner_map.get(wall.corner_end_id)
        if not c1 or not c2:
            return
        dx, dy = c2.x - c1.x, c2.y - c1.y
        wlen = math.hypot(dx, dy)
        if wlen < 1e-3:
            return
        ux, uy = dx / wlen, dy / wlen
        s_x = c1.x + x_offset + ux * op.position_along_wall_mm
        s_y = c1.y + uy * op.position_along_wall_mm
        e_x = s_x + ux * op.width
        e_y = s_y + uy * op.width
        layer = "A-GLAZ" if op.type == "window" else "A-DOOR"
        msp.add_line((s_x, s_y), (e_x, e_y), dxfattribs={"layer": layer})

        if op.type == "swing_door":
            # Draw 90-degree door leaf perpendicular to wall
            nx, ny = -uy, ux
            leaf_end = (s_x + nx * op.width, s_y + ny * op.width)
            msp.add_line((s_x, s_y), leaf_end, dxfattribs={"layer": "A-DOOR"})
            ang_start = math.degrees(math.atan2(uy, ux))
            msp.add_arc(
                center=(s_x, s_y),
                radius=op.width,
                start_angle=ang_start,
                end_angle=ang_start + 90.0,
                dxfattribs={"layer": "A-DOOR"},
            )
