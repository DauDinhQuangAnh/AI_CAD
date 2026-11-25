"""CLI entry point for AI_CAD pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.pipeline import AICADPipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI_CAD: Convert 2D architectural vector PDFs to DXF & Floorplanner JSON."
    )
    parser.add_argument("input_pdf", type=Path, help="Path to input vector PDF floor plan.")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("data/outputs"),
        help="Directory for generated outputs (default: data/outputs).",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Enable Gemini Vision LLM enrichment (requires GEMINI_API_KEY).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )
    logging.getLogger("ezdxf").setLevel(logging.WARNING)

    pipeline = AICADPipeline(use_llm=args.use_llm)
    outputs = pipeline.run(args.input_pdf, output_dir=args.output_dir)

    print(f"Processed: {args.input_pdf}")
    print(f"  Project : {outputs.document.project_metadata.project_name}")
    print(f"  Floors  : {len(outputs.document.floors)}")
    for fl in outputs.document.floors:
        print(
            f"    - {fl.floor_name}: {len(fl.walls)} walls, "
            f"{len(fl.openings)} openings, {len(fl.spaces)} rooms"
        )
        for sp in fl.spaces:
            nom = f"{sp.nominal_area_m2:.2f}" if sp.nominal_area_m2 is not None else "N/A"
            calc = f"{sp.calculated_area_m2:.2f}" if sp.calculated_area_m2 is not None else "N/A"
            err = f" (err={sp.area_error_pct:.1f}%)" if sp.area_error_pct is not None else ""
            print(f"        * {sp.name}: calc={calc} m2, nominal={nom} m2{err}")
    print(f"  Schema  : {outputs.schema_json_path}")
    print(f"  DXF     : {outputs.dxf_path}")
    print(f"  Floorpl.: {outputs.floorplanner_json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
