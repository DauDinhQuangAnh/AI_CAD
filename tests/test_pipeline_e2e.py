"""End-to-end integration test on data/raw/test1.pdf."""

import json
from pathlib import Path

import ezdxf

from src.core.schema import AICADDocument
from src.pipeline import AICADPipeline


def test_e2e_test1_pdf(tmp_path: Path):
    pdf_path = Path("data/raw/test1.pdf")
    assert pdf_path.exists()

    pipeline = AICADPipeline(use_llm=False)
    outputs = pipeline.run(pdf_path, output_dir=tmp_path, stem="test1_e2e")

    assert outputs.schema_json_path.exists()
    assert outputs.dxf_path.exists()
    assert outputs.floorplanner_json_path.exists()

    doc = AICADDocument.model_validate_json(outputs.schema_json_path.read_text(encoding="utf-8"))
    assert doc.project_metadata.project_code == "26-1122"
    assert doc.project_metadata.scale_ratio == "1:100"
    assert len(doc.floors) == 2

    # Verify DXF is valid and has expected architectural layers
    dxf_doc = ezdxf.readfile(str(outputs.dxf_path))
    for layer in ("A-WALL-CORE", "A-DOOR", "A-AREA", "A-ANNO-TEXT"):
        assert layer in dxf_doc.layers
    assert len(list(dxf_doc.modelspace())) > 50

    # Verify Floorplanner JSON structure
    fp_data = json.loads(outputs.floorplanner_json_path.read_text(encoding="utf-8"))
    assert len(fp_data["floors"]) == 2
    assert len(fp_data["floors"][0]["walls"]) > 10
    assert len(fp_data["floors"][0]["rooms"]) >= 3
