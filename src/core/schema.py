"""Pydantic v2 models for the AI-CAD Unified Intermediate Schema (docs/DATA_SCHEMA.md)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Point2D(BaseModel):
    """2D coordinate in millimeters (or PDF points prior to scaling)."""

    x: float
    y: float


class BoundingBox(BaseModel):
    """Axis-aligned 2D bounding box."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def width(self) -> float:
        return max(0.0, self.x_max - self.x_min)

    @property
    def height(self) -> float:
        return max(0.0, self.y_max - self.y_min)


class ProjectMetadata(BaseModel):
    """Project-level metadata extracted from the drawing title block."""

    project_name: str = "Untitled Project"
    project_code: Optional[str] = None
    address: Optional[str] = None
    author: Optional[str] = None
    scale_ratio: str = "1:100"
    units: Literal["mm", "cm", "m"] = "mm"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Corner(BaseModel):
    """Wall junction / vertex in real-world millimeters."""

    id: str
    x: float
    y: float
    elevation: float = 0.0


class Wall(BaseModel):
    """Wall segment connecting two corners."""

    id: str
    corner_start_id: str
    corner_end_id: str
    wall_type: Literal["exterior", "interior", "bearing"] = "interior"
    thickness: float = Field(default=200.0, gt=0)
    height: float = Field(default=2800.0, gt=0)
    material: Optional[str] = None
    fire_rating_minutes: Optional[int] = None


class Opening(BaseModel):
    """Door, window, or architectural opening placed along a wall."""

    id: str
    type: Literal["swing_door", "sliding_door", "window", "opening"] = "swing_door"
    wall_id: str
    position_along_wall_mm: float = Field(ge=0.0)
    width: float = Field(gt=0.0)
    height: float = Field(default=2100.0, gt=0.0)
    swing_direction: Optional[
        Literal["inward_left", "inward_right", "outward_left", "outward_right"]
    ] = None
    material: Optional[str] = None


class Space(BaseModel):
    """Closed room polygon with semantic label and area cross-validation."""

    id: str
    name: str
    name_vn: Optional[str] = None
    category: str = "other"
    nominal_area_m2: Optional[float] = None
    calculated_area_m2: Optional[float] = None
    boundary_corner_ids: list[str] = Field(default_factory=list)
    elevation_offset_mm: Optional[float] = None
    area_error_pct: Optional[float] = None


class Dimension(BaseModel):
    """Dimension annotation extracted from drawing for scale calibration & cross-validation."""

    id: str
    text: str
    value_mm: float = Field(gt=0.0)
    orientation: Literal["horizontal", "vertical", "diagonal"] = "horizontal"
    start_point: Point2D
    end_point: Point2D


class FloorPlan(BaseModel):
    """Single floor representation containing geometry, openings, rooms, and dimensions."""

    floor_id: str
    floor_name: str
    elevation_peil: Optional[float] = None
    bounding_box: BoundingBox
    corners: list[Corner] = Field(default_factory=list)
    walls: list[Wall] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)
    spaces: list[Space] = Field(default_factory=list)
    dimensions: list[Dimension] = Field(default_factory=list)


class AICADDocument(BaseModel):
    """Root Unified Intermediate Schema document."""

    project_metadata: ProjectMetadata = Field(default_factory=ProjectMetadata)
    floors: list[FloorPlan] = Field(default_factory=list)
