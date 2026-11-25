"""Floorplanner-compatible JSON exporter for 2D/3D web & desktop rendering."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.core.schema import AICADDocument, FloorPlan

logger = logging.getLogger(__name__)


class FloorplannerExporter:
    """Exports an AICADDocument into Floorplanner-compatible JSON structure."""

    def to_dict(self, doc: AICADDocument) -> dict[str, Any]:
        """Convert AICADDocument to a Floorplanner-compatible dictionary."""
        return {
            "version": "1.0",
            "project": doc.project_metadata.model_dump(mode="json"),
            "floors": [self._convert_floor(f) for f in doc.floors],
        }

    def export(self, doc: AICADDocument, output_path: str | Path) -> Path:
        """Write Floorplanner JSON to disk."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict(doc)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Exported Floorplanner JSON to %s", out)
        return out

    @staticmethod
    def _convert_floor(floor: FloorPlan) -> dict[str, Any]:
        corner_map = {c.id: c for c in floor.corners}
        doors = [o for o in floor.openings if "door" in o.type or o.type == "opening"]
        windows = [o for o in floor.openings if o.type == "window"]

        rooms = []
        for sp in floor.spaces:
            poly_pts = [
                {"x": corner_map[cid].x, "y": corner_map[cid].y}
                for cid in sp.boundary_corner_ids
                if cid in corner_map
            ]
            rooms.append(
                {
                    "id": sp.id,
                    "name": sp.name,
                    "name_vn": sp.name_vn,
                    "category": sp.category,
                    "area_m2": sp.calculated_area_m2,
                    "nominal_area_m2": sp.nominal_area_m2,
                    "polygon": poly_pts,
                }
            )

        return {
            "floor_id": floor.floor_id,
            "name": floor.floor_name,
            "elevation_mm": floor.elevation_peil,
            "corners": [c.model_dump() for c in floor.corners],
            "walls": [
                {
                    "id": w.id,
                    "start_corner": w.corner_start_id,
                    "end_corner": w.corner_end_id,
                    "thickness_mm": w.thickness,
                    "height_mm": w.height,
                    "type": w.wall_type,
                }
                for w in floor.walls
            ],
            "doors": [d.model_dump() for d in doors],
            "windows": [win.model_dump() for win in windows],
            "rooms": rooms,
        }
