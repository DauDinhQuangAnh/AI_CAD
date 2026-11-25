"""Unit tests for AI_CAD Pydantic schema models."""

from src.core.schema import (
    AICADDocument,
    BoundingBox,
    Corner,
    Dimension,
    FloorPlan,
    Opening,
    Point2D,
    ProjectMetadata,
    Space,
    Wall,
)


def test_schema_roundtrip():
    doc = AICADDocument(
        project_metadata=ProjectMetadata(
            project_name="Test House",
            project_code="26-0001",
            scale_ratio="1:100",
        ),
        floors=[
            FloorPlan(
                floor_id="floor_1",
                floor_name="Ground Floor",
                elevation_peil=-50.0,
                bounding_box=BoundingBox(x_min=0, y_min=0, x_max=5000, y_max=4000),
                corners=[
                    Corner(id="c1", x=0, y=0),
                    Corner(id="c2", x=5000, y=0),
                    Corner(id="c3", x=5000, y=4000),
                    Corner(id="c4", x=0, y=4000),
                ],
                walls=[
                    Wall(id="w1", corner_start_id="c1", corner_end_id="c2", thickness=200),
                    Wall(id="w2", corner_start_id="c2", corner_end_id="c3", thickness=200),
                ],
                openings=[
                    Opening(
                        id="d1",
                        type="swing_door",
                        wall_id="w1",
                        position_along_wall_mm=1000,
                        width=900,
                    )
                ],
                spaces=[
                    Space(
                        id="s1",
                        name="living",
                        name_vn="Phòng khách",
                        category="living",
                        nominal_area_m2=20.0,
                        calculated_area_m2=20.0,
                        boundary_corner_ids=["c1", "c2", "c3", "c4"],
                    )
                ],
                dimensions=[
                    Dimension(
                        id="dim_1",
                        text="5000",
                        value_mm=5000,
                        orientation="horizontal",
                        start_point=Point2D(x=0, y=0),
                        end_point=Point2D(x=5000, y=0),
                    )
                ],
            )
        ],
    )
    raw = doc.model_dump_json()
    restored = AICADDocument.model_validate_json(raw)
    assert restored.project_metadata.project_code == "26-0001"
    assert len(restored.floors) == 1
    assert restored.floors[0].walls[0].thickness == 200
