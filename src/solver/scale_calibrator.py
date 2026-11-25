"""Scale calibrator converting PDF points into real-world millimeters.

Uses PDF architectural scale ratio (e.g. 1:100 -> 35.2778 mm/pt) as a prior,
then cross-validates and refines using Median / RANSAC over matched dimension lines.
"""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass
from typing import Optional

from src.core.schema import Dimension
from src.preprocessor.pdf_extractor import VectorSegment

logger = logging.getLogger(__name__)

MM_PER_PT = 25.4 / 72.0  # 1 PDF point = 0.352777... mm on paper


@dataclass(frozen=True)
class ScaleResult:
    """Calibrated scale factor from PDF points to real-world millimeters."""

    mm_per_pt: float
    source: str  # "ransac_dimensions" | "scale_ratio_prior" | "default"
    matched_count: int
    confidence: float


class ScaleCalibrator:
    """Robust scale estimator using scale-ratio prior + Median/RANSAC on dimension lines."""

    def __init__(self, tolerance_ratio: float = 0.08) -> None:
        self.tolerance_ratio = tolerance_ratio

    @staticmethod
    def prior_from_scale_ratio(scale_ratio: str) -> Optional[float]:
        """Convert architectural scale string like '1:100' into mm_per_pt."""
        m = re.search(r"1\s*:\s*(\d+)", scale_ratio or "")
        if not m:
            return None
        denom = float(m.group(1))
        if denom <= 0:
            return None
        return MM_PER_PT * denom

    def calibrate(
        self,
        dimensions: list[Dimension],
        segments: list[VectorSegment],
        scale_ratio: str = "1:100",
    ) -> ScaleResult:
        """Estimate mm_per_pt robustly without outlier corruption."""
        prior = self.prior_from_scale_ratio(scale_ratio) or (MM_PER_PT * 100.0)

        # Match each dimension text to nearby parallel dimension-line segments
        ratios: list[float] = []
        for dim in dimensions:
            expected_pt = dim.value_mm / prior
            if expected_pt < 5.0:
                continue

            cx = (dim.start_point.x + dim.end_point.x) / 2.0
            cy = (dim.start_point.y + dim.end_point.y) / 2.0

            best_seg_len: Optional[float] = None
            best_err = float("inf")
            for seg in segments:
                # Filter by orientation
                ang = seg.angle_deg
                is_horiz = ang < 5.0 or ang > 175.0
                is_vert = 85.0 < ang < 95.0
                if dim.orientation == "horizontal" and not is_horiz:
                    continue
                if dim.orientation == "vertical" and not is_vert:
                    continue

                # Dimension line should be reasonably close to the dimension text
                mid = seg.midpoint
                dist = abs(mid.y - cy) if dim.orientation == "horizontal" else abs(mid.x - cx)
                if dist > 25.0:
                    continue

                # Check if segment length is plausible relative to prior
                if seg.length < 5.0:
                    continue
                rel_err = abs(seg.length - expected_pt) / expected_pt
                if rel_err < 0.25 and rel_err < best_err:
                    best_err = rel_err
                    best_seg_len = seg.length

            if best_seg_len is not None:
                ratios.append(dim.value_mm / best_seg_len)

        if len(ratios) >= 2:
            med = statistics.median(ratios)
            inliers = [r for r in ratios if abs(r - med) / med <= self.tolerance_ratio]
            if len(inliers) >= 2:
                refined = statistics.median(inliers)
                # If refined is very close to exact CAD scale prior (within 1.5%), snap to exact prior
                if abs(refined - prior) / prior <= 0.015:
                    logger.info(
                        "Scale verified by %d dimension inliers (within 1.5%% of prior %.4f)",
                        len(inliers),
                        prior,
                    )
                    return ScaleResult(
                        mm_per_pt=prior,
                        source="scale_ratio_prior",
                        matched_count=len(inliers),
                        confidence=0.99,
                    )
                return ScaleResult(
                    mm_per_pt=refined,
                    source="ransac_dimensions",
                    matched_count=len(inliers),
                    confidence=0.9,
                )

        return ScaleResult(
            mm_per_pt=prior,
            source="scale_ratio_prior",
            matched_count=len(ratios),
            confidence=0.85,
        )
