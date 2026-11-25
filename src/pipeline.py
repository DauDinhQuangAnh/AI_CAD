"""End-to-end 5-Stage AI_CAD Pipeline Orchestrator (Sprints 1-3)."""

from __future__ import annotations

import json
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.room_polygonizer import RoomPolygonizer
from src.core.schema import AICADDocument, BoundingBox, Dimension, FloorPlan, Point2D, Space
from src.exporters.dxf_exporter import DXFExporter
from src.exporters.floorplanner_exporter import FloorplannerExporter
from src.llm.base import LLMSemanticResult
from src.llm.gemini_provider import GeminiVisionProvider
from src.llm.heuristic_parser import HeuristicSemanticParser, PositionedRoomHint, RegionSemanticData
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


def reconcile_semantics(
    sem: RegionSemanticData,
    llm_res: LLMSemanticResult,
    suggested_floor_name: str,
    fallback_center: Point2D,
) -> tuple[str, list[PositionedRoomHint]]:
    """Cross-check and fuse deterministic PDF text semantics with Vision LLM output.

    Returns updated (floor_name, unmatched_llm_rooms_for_area_matching).
    """
    floor_name = suggested_floor_name
    if llm_res.floor_name and (
        floor_name.startswith("Floor ") or len(llm_res.floor_name) > len(floor_name)
    ):
        floor_name = llm_res.floor_name.strip()

    if llm_res.elevation_peil_mm is not None and sem.elevation_peil_mm is None:
        sem.elevation_peil_mm = llm_res.elevation_peil_mm

    # Enrich existing positioned rooms from LLM (better VN translation, category, nominal area)
    llm_by_name = {r.name.strip().lower(): r for r in llm_res.rooms}
    matched_llm_names: set[str] = set()

    for hint in sem.rooms:
        key = hint.name.strip().lower()
        llm_match = llm_by_name.get(key)
        if llm_match is None:
            # Partial substring match
            for lkey, lval in llm_by_name.items():
                if lkey in key or key in lkey:
                    llm_match = lval
                    break
        if llm_match is not None:
            matched_llm_names.add(llm_match.name.strip().lower())
            if not hint.name_vn and llm_match.name_vn:
                hint.name_vn = llm_match.name_vn
            if hint.category == "other" and llm_match.category != "other":
                hint.category = llm_match.category
            if hint.nominal_area_m2 is None and llm_match.nominal_area_m2 is not None:
                hint.nominal_area_m2 = llm_match.nominal_area_m2

    # Collect LLM-discovered rooms not found in PDF text layer
    extra_llm_rooms = [
        PositionedRoomHint(
            name=r.name,
            name_vn=r.name_vn,
            category=r.category,
            nominal_area_m2=r.nominal_area_m2,
            center=fallback_center,
        )
        for r in llm_res.rooms
        if r.name.strip().lower() not in matched_llm_names
    ]

    # If PDF text layer had no dimensions (e.g. outlined text), supplement from LLM
    if not sem.dimensions and llm_res.dimensions:
        for idx, d in enumerate(llm_res.dimensions, start=1):
            if d.value_mm > 0:
                sem.dimensions.append(
                    Dimension(
                        id=f"llm_dim_{idx}",
                        text=d.text,
                        value_mm=d.value_mm,
                        orientation=(
                            d.orientation
                            if d.orientation in ("horizontal", "vertical", "diagonal")
                            else "horizontal"
                        ),
                        start_point=fallback_center,
                        end_point=fallback_center,
                    )
                )

    return floor_name, extra_llm_rooms


def assign_unmatched_rooms_by_area(
    spaces: list[Space],
    extra_rooms: list[PositionedRoomHint],
    max_rel_error: float = 0.25,
) -> None:
    """Match remaining LLM-discovered rooms to unlabeled polygons by closest area."""
    if not extra_rooms or not spaces:
        return
    used_extra: set[int] = set()
    for sp in spaces:
        if not sp.name.startswith("Room ") or sp.calculated_area_m2 is None:
            continue
        best_idx: Optional[int] = None
        best_err = max_rel_error
        for idx, er in enumerate(extra_rooms):
            if idx in used_extra or not er.nominal_area_m2 or er.nominal_area_m2 <= 0:
                continue
            rel = abs(sp.calculated_area_m2 - er.nominal_area_m2) / er.nominal_area_m2
            if rel < best_err:
                best_err = rel
                best_idx = idx
        if best_idx is not None:
            used_extra.add(best_idx)
            chosen = extra_rooms[best_idx]
            sp.name = chosen.name
            sp.name_vn = chosen.name_vn
            sp.category = chosen.category
            sp.nominal_area_m2 = chosen.nominal_area_m2
            sp.area_error_pct = round(best_err * 100.0, 2)


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

        # Launch Vision LLM calls in parallel with vector geometry processing
        llm_futures: dict[str, Future[LLMSemanticResult]] = {}
        executor: Optional[ThreadPoolExecutor] = None
        if self.llm_provider and self.llm_provider.is_available and extracted.regions:
            executor = ThreadPoolExecutor(max_workers=min(4, len(extracted.regions)))
            for region in extracted.regions:
                crop_png = out_dir / f"{base_name}_{region.region_id}_crop.png"
                self.extractor.render_region_png(
                    in_path, region.page_index, region.pdf_rect, crop_png, dpi=200
                )
                context_txt = "\n".join(t.text for t in region.texts)
                llm_futures[region.region_id] = executor.submit(
                    self.llm_provider.analyze_floor_plan,
                    str(crop_png),
                    context_txt,
                )

        floors: list[FloorPlan] = []
        try:
            for idx, region in enumerate(extracted.regions):
                # Stage 2B (Local): Vector-Text Semantic Parsing
                sem = self.semantic_parser.parse_region(region.texts)

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

                # Cross-check & Reconcile with parallel Vision LLM result if enabled
                floor_name = region.suggested_floor_name or f"Floor {idx + 1}"
                extra_llm_rooms: list[PositionedRoomHint] = []
                fut = llm_futures.get(region.region_id)
                if fut is not None:
                    try:
                        llm_res = fut.result()
                        if llm_res.scale_ratio and metadata.scale_ratio == "1:100":
                            metadata.scale_ratio = llm_res.scale_ratio
                        fallback_pt = Point2D(
                            x=(region.cad_bbox.x_min + region.cad_bbox.x_max) / 2.0,
                            y=(region.cad_bbox.y_min + region.cad_bbox.y_max) / 2.0,
                        )
                        floor_name, extra_llm_rooms = reconcile_semantics(
                            sem, llm_res, floor_name, fallback_pt
                        )
                    except Exception as exc:
                        logger.warning(
                            "Vision LLM enrichment skipped for %s: %s", region.region_id, exc
                        )

                # Stage 3C: Room Polygonization & Area Cross-Validation
                spaces = self.polygonizer.extract_spaces(
                    corners=solved.corners,
                    walls=solved.walls,
                    room_hints=sem.rooms,
                    mm_per_pt=scale_res.mm_per_pt,
                    origin_offset_mm=solved.origin_offset_mm,
                )
                assign_unmatched_rooms_by_area(spaces, extra_llm_rooms)

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
                        floor_name=floor_name,
                        elevation_peil=sem.elevation_peil_mm,
                        bounding_box=bbox,
                        corners=solved.corners,
                        walls=solved.walls,
                        openings=solved.openings,
                        spaces=spaces,
                        dimensions=scaled_dims,
                    )
                )
        finally:
            if executor is not None:
                executor.shutdown(wait=False)

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
