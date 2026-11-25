"""End-to-end 5-Stage AI_CAD Pipeline Orchestrator (Sprints 1-3)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.room_polygonizer import RoomPolygonizer
from src.core.schema import AICADDocument, BoundingBox, Dimension, FloorPlan, Point2D
from src.exporters.dxf_exporter import DXFExporter
from src.exporters.floorplanner_exporter import FloorplannerExporter
from src.llm.gemini_provider import GeminiVisionProvider
from src.llm.heuristic_parser import HeuristicSemanticParser
from src.preprocessor.pdf_extractor import PDFExtractor
from src.solver.orthogonal_snap import OrthogonalSnapSolver
from src.solver.scale_calibrator import ScaleCalibrator
from src.vision.vector_geometry import VectorGeometryParser

logger = logging.getLogger(__name__)


@dataclass
class PipelineOutputs:
    """Paths and summary produced by running AICADPipeline."""

    document: AICADDocument
    schema_json_path: Path
    dxf_path: Path
    floorplanner_json_path: Path


class AICADPipeline:
    """Orchestrates Stage 1 (Ingestion) -> Stage 5 (DXF & Floorplanner Export)."""

    def __init__(
        self,
        use_llm: bool = False,
        gemini_api_key: Optional[str] = None,
    ) -> None:
        self.extractor = PDFExtractor()
        self.semantic_parser = HeuristicSemanticParser()
        self.scale_calibrator = ScaleCalibrator()
        self.vector_parser = VectorGeometryParser()
        self.snap_solver = OrthogonalSnapSolver()
        self.polygonizer = RoomPolygonizer()
        self.dxf_exporter = DXFExporter()
        self.floorplanner_exporter = FloorplannerExporter()

        self.use_llm = use_llm
        self.llm_provider = (
            GeminiVisionProvider(api_key=gemini_api_key) if use_llm else None
        )

    def run(
        self,
        pdf_path: str | Path,
        output_dir: str | Path = "data/outputs",
        stem: Optional[str] = None,
    ) -> PipelineOutputs:
        """Execute the full 5-stage pipeline on a vector PDF floor plan."""
        in_path = Path(pdf_path)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        base_name = stem or in_path.stem

        # Stage 1: Ingestion & Region Cropping
        extracted = self.extractor.extract(in_path)
        metadata = self.semantic_parser.parse_project_metadata(extracted.all_texts)

        floors: list[FloorPlan] = []
        for idx, region in enumerate(extracted.regions):
            # Stage 2B: Semantic Parsing (Vector Text + Optional Vision LLM)
            sem = self.semantic_parser.parse_region(region.texts)

            if self.llm_provider and self.llm_provider.is_available:
                crop_png = out_dir / f"{base_name}_{region.region_id}_crop.png"
                self.extractor.render_region_png(
                    in_path, region.page_index, region.pdf_rect, crop_png, dpi=200
                )
                context_txt = "\n".join(t.text for t in region.texts)
                try:
                    llm_res = self.llm_provider.analyze_floor_plan(str(crop_png), context_txt)
                    if llm_res.floor_name:
                        region.suggested_floor_name = llm_res.floor_name
                    if llm_res.elevation_peil_mm is not None and sem.elevation_peil_mm is None:
                        sem.elevation_peil_mm = llm_res.elevation_peil_mm
                except Exception as exc:
                    logger.warning("Vision LLM enrichment skipped for %s: %s", region.region_id, exc)

            # Stage 3A: Scale Calibration (Prior + Median/RANSAC)
            scale_res = self.scale_calibrator.calibrate(
                sem.dimensions,
                region.segments,
                scale_ratio=metadata.scale_ratio,
            )

            # Stage 2A: Vector Geometry Extraction (Walls & Openings)
            raw_walls, raw_openings = self.vector_parser.parse(
                region.segments,
                mm_per_pt=scale_res.mm_per_pt,
            )

            # Stage 3B: Orthogonal Snapping, Junction Extension & Vertex Clustering
            solved = self.snap_solver.solve(raw_walls, raw_openings)

            # Stage 3C: Room Polygonization & Area Cross-Validation
            spaces = self.polygonizer.extract_spaces(
                corners=solved.corners,
                walls=solved.walls,
                room_hints=sem.rooms,
                mm_per_pt=scale_res.mm_per_pt,
                origin_offset_mm=solved.origin_offset_mm,
            )

            # Scale dimensions to solved mm space
            ox, oy = solved.origin_offset_mm
            scaled_dims = [
                Dimension(
                    id=d.id,
                    text=d.text,
                    value_mm=d.value_mm,
                    orientation=d.orientation,
                    start_point=Point2D(
                        x=round(d.start_point.x * scale_res.mm_per_pt - ox, 1),
                        y=round(d.start_point.y * scale_res.mm_per_pt - oy, 1),
                    ),
                    end_point=Point2D(
                        x=round(d.end_point.x * scale_res.mm_per_pt - ox, 1),
                        y=round(d.end_point.y * scale_res.mm_per_pt - oy, 1),
                    ),
                )
                for d in sem.dimensions
            ]

            if solved.corners:
                bbox = BoundingBox(
                    x_min=min(c.x for c in solved.corners),
                    y_min=min(c.y for c in solved.corners),
                    x_max=max(c.x for c in solved.corners),
                    y_max=max(c.y for c in solved.corners),
                )
            else:
                bbox = BoundingBox(x_min=0.0, y_min=0.0, x_max=0.0, y_max=0.0)

            floors.append(
                FloorPlan(
                    floor_id=region.region_id,
                    floor_name=region.suggested_floor_name or f"Floor {idx + 1}",
                    elevation_peil=sem.elevation_peil_mm,
                    bounding_box=bbox,
                    corners=solved.corners,
                    walls=solved.walls,
                    openings=solved.openings,
                    spaces=spaces,
                    dimensions=scaled_dims,
                )
            )

        # Stage 4: Unified Intermediate Schema
        doc = AICADDocument(project_metadata=metadata, floors=floors)
        schema_path = out_dir / f"{base_name}_schema.json"
        schema_path.write_text(
            json.dumps(doc.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Stage 5: Exporters
        dxf_path = self.dxf_exporter.export(doc, out_dir / f"{base_name}.dxf")
        fp_path = self.floorplanner_exporter.export(doc, out_dir / f"{base_name}_floorplanner.json")

        return PipelineOutputs(
            document=doc,
            schema_json_path=schema_path,
            dxf_path=dxf_path,
            floorplanner_json_path=fp_path,
        )
