"""Abstract base class and structured output models for Vision LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field


class LLMExtractedDimension(BaseModel):
    """Dimension annotation parsed by a Vision LLM."""

    text: str
    value_mm: float
    orientation: str = "horizontal"  # "horizontal" | "vertical" | "diagonal"


class LLMExtractedRoom(BaseModel):
    """Room label & area parsed by a Vision LLM."""

    name: str
    name_vn: Optional[str] = None
    category: str = "other"
    nominal_area_m2: Optional[float] = None
    elevation_offset_mm: Optional[float] = None


class LLMSemanticResult(BaseModel):
    """Combined semantic output for a single floor plan image."""

    floor_name: Optional[str] = None
    elevation_peil_mm: Optional[float] = None
    scale_ratio: Optional[str] = None
    dimensions: list[LLMExtractedDimension] = Field(default_factory=list)
    rooms: list[LLMExtractedRoom] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class BaseVisionLLM(ABC):
    """Abstract base class for all Vision LLM providers (Strategy Pattern)."""

    @abstractmethod
    def analyze_floor_plan(
        self,
        image_path: str,
        context_text: str = "",
    ) -> LLMSemanticResult:
        """Analyze a cropped floor-plan image and return structured semantic data."""
        raise NotImplementedError
