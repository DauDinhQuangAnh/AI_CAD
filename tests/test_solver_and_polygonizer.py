"""Unit tests for ScaleCalibrator, OrthogonalSnapSolver, and RoomPolygonizer."""

from src.core.room_polygonizer import RoomPolygonizer
from src.core.schema import Dimension, Point2D
from src.llm.heuristic_parser import PositionedRoomHint
from src.preprocessor.pdf_extractor import VectorSegment
from src.solver.orthogonal_snap import OrthogonalSnapSolver
from src.solver.scale_calibrator import MM_PER_PT, ScaleCalibrator
from src.vision.vector_geometry import RawWallSegment


def test_scale_calibrator_rejects_outlier():
    cal = ScaleCalibrator()
    prior = MM_PER_PT * 100.0
    # 2 valid dimension lines + 1 bad outlier
    dims = [
        Dimension(
            id="d1",
            text="5000",
            value_mm=5000.0,
            orientation="horizontal",
            start_point=Point2D(x=0, y=10),
            end_point=Point2D(x=5000.0 / prior, y=15),
        ),
        Dimension(
            id="d2",
            text="3000",
            value_mm=3000.0,
            orientation="vertical",
            start_point=Point2D(x=10, y=0),
            end_point=Point2D(x=15, y=3000.0 / prior),
        ),
        Dimension(
            id="d3_outlier",
            text="9999",
            value_mm=9999.0,
            orientation="horizontal",
            start_point=Point2D(x=0, y=20),
            end_point=Point2D(x=20, y=25),
        ),
    ]
    segs = [
        VectorSegment(x1=0, y1=12, x2=5000.0 / prior, y2=12),
        VectorSegment(x1=12, y1=0, x2=12, y2=3000.0 / prior),
        VectorSegment(x1=0, y1=22, x2=5000.0 / prior, y2=22),
    ]
    res = cal.calibrate(dims, segs, scale_ratio="1:100")
    assert abs(res.mm_per_pt - prior) < 1e-3
    assert res.matched_count == 2


def test_orthogonal_snap_and_polygonizer_closes_room():
    # A 5000 x 4000 mm room with slightly skewed walls (0.5 deg) and a 900 mm door gap
    raw_walls = [
        RawWallSegment(start=Point2D(x=0, y=0), end=Point2D(x=5000, y=20), thickness_mm=200),
        RawWallSegment(start=Point2D(x=5000, y=0), end=Point2D(x=4985, y=4000), thickness_mm=200),
        RawWallSegment(start=Point2D(x=5000, y=4000), end=Point2D(x=900, y=4000), thickness_mm=200),
        RawWallSegment(start=Point2D(x=0, y=4000), end=Point2D(x=0, y=0), thickness_mm=200),
    ]
    solver = OrthogonalSnapSolver()
    solved = solver.solve(raw_walls)
    assert len(solved.walls) == 4

    poly = RoomPolygonizer()
    hints = [
        PositionedRoomHint(
            name="living",
            name_vn="Phòng khách",
            category="living",
            nominal_area_m2=20.0,
            center=Point2D(x=2500, y=2000),
        )
    ]
    spaces = poly.extract_spaces(
        solved.corners,
        solved.walls,
        room_hints=hints,
        mm_per_pt=1.0,
        origin_offset_mm=solved.origin_offset_mm,
    )
    assert len(spaces) == 1
    assert spaces[0].name == "living"
    assert 19.5 <= (spaces[0].calculated_area_m2 or 0.0) <= 20.5


def test_orthogonal_snap_preserves_intentional_slanted_wall():
    # 12-degree slanted facade wall must NOT be forced to 0 deg
    raw_walls = [
        RawWallSegment(start=Point2D(x=0, y=0), end=Point2D(x=5000, y=1060), thickness_mm=200),
    ]
    solver = OrthogonalSnapSolver(angle_snap_deg=1.5, normalize_origin=False)
    solved = solver.solve(raw_walls)
    c_map = {c.id: c for c in solved.corners}
    w = solved.walls[0]
    dy = abs(c_map[w.corner_end_id].y - c_map[w.corner_start_id].y)
    assert dy > 900.0
