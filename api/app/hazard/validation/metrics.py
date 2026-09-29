"""Quantitative benchmark metrics derived directly from spatial raster and cell overlap.

Scientific Integrity Rules:
- No metric is hardcoded or fabricated.
- Every metric is computed strictly from the underlying confusion matrix (TP, FP, FN, TN).
- Precision and prediction overlap are mathematically unified.
- Confidence scores are derived directly from empirical performance (F1, IoU, Accuracy).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.hazard.validation.comparison import HazardComparisonResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BenchmarkMetrics:
    """Quantitative validation metrics computed from spatial overlap."""

    iou: float  # Intersection over Union: TP / (TP + FP + FN)
    precision: float  # TP / (TP + FP)
    recall: float  # TP / (TP + FN)
    f1_score: float  # 2 * (P * R) / (P + R)
    accuracy: float  # (TP + TN) / Total
    specificity: float  # TN / (TN + FP)
    cohens_kappa: float  # Chance-adjusted inter-rater agreement
    flooded_area_observed_km2: float  # TP + FN
    flooded_area_predicted_km2: float  # TP + FP
    intersection_area_km2: float  # TP
    union_area_km2: float  # TP + FP + FN
    flooded_area_agreement: float  # 1.0 - |obs - pred| / max(obs, pred)
    confusion_matrix: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to JSON-serializable dictionary."""
        return {
            "iou": self.iou,
            "precision": self.precision,
            "recall": self.recall,
            "f1_score": self.f1_score,
            "accuracy": self.accuracy,
            "specificity": self.specificity,
            "cohens_kappa": self.cohens_kappa,
            "flooded_area_observed_km2": self.flooded_area_observed_km2,
            "flooded_area_predicted_km2": self.flooded_area_predicted_km2,
            "intersection_area_km2": self.intersection_area_km2,
            "union_area_km2": self.union_area_km2,
            "flooded_area_agreement": self.flooded_area_agreement,
            "confusion_matrix": self.confusion_matrix,
        }


def compute_benchmark_metrics(
    comparison: HazardComparisonResult,
) -> BenchmarkMetrics:
    """Compute complete quantitative benchmark suite from a HazardComparisonResult."""
    tp = float(comparison.tp_area_km2)
    fp = float(comparison.fp_area_km2)
    fn = float(comparison.fn_area_km2)
    tn = float(comparison.tn_area_km2)

    total_area = tp + fp + fn + tn
    union_area = tp + fp + fn
    intersection_area = tp

    # 1. Precision: TP / (TP + FP)
    pred_flood = tp + fp
    precision = (tp / pred_flood) if pred_flood > 0.0 else 0.0

    # 2. Recall: TP / (TP + FN)
    obs_flood = tp + fn
    recall = (tp / obs_flood) if obs_flood > 0.0 else 0.0

    # 3. Intersection over Union (IoU / Jaccard Index): TP / (TP + FP + FN)
    iou = (tp / union_area) if union_area > 0.0 else 0.0

    # 4. F1 Score (Dice Coefficient): 2 * TP / (2 * TP + FP + FN)
    f1_denom = (2.0 * tp) + fp + fn
    f1_score = ((2.0 * tp) / f1_denom) if f1_denom > 0.0 else 0.0

    # 5. Accuracy: (TP + TN) / Total
    accuracy = ((tp + tn) / total_area) if total_area > 0.0 else 0.0

    # 6. Specificity (True Negative Rate): TN / (TN + FP)
    negatives = tn + fp
    specificity = (tn / negatives) if negatives > 0.0 else 0.0

    # 7. Cohen's Kappa
    # Observed accuracy: Po
    p0 = accuracy
    # Expected chance accuracy: Pe
    if total_area > 0.0:
        p_pred_yes = (tp + fp) / total_area
        p_obs_yes = (tp + fn) / total_area
        p_pred_no = (tn + fn) / total_area
        p_obs_no = (tn + fp) / total_area
        pe = (p_pred_yes * p_obs_yes) + (p_pred_no * p_obs_no)
        kappa = ((p0 - pe) / (1.0 - pe)) if (1.0 - pe) > 1e-6 else 0.0
    else:
        kappa = 0.0

    # 8. Flooded area agreement: 1.0 - relative absolute area error
    max_area = max(obs_flood, pred_flood, 1e-6)
    area_agreement = max(0.0, 1.0 - (abs(obs_flood - pred_flood) / max_area))

    cm = {
        "tp_km2": round(tp, 2),
        "fp_km2": round(fp, 2),
        "fn_km2": round(fn, 2),
        "tn_km2": round(tn, 2),
        "tp_cells": comparison.tp_count,
        "fp_cells": comparison.fp_count,
        "fn_cells": comparison.fn_count,
        "tn_cells": comparison.tn_count,
    }

    return BenchmarkMetrics(
        iou=round(min(1.0, max(0.0, iou)), 4),
        precision=round(min(1.0, max(0.0, precision)), 4),
        recall=round(min(1.0, max(0.0, recall)), 4),
        f1_score=round(min(1.0, max(0.0, f1_score)), 4),
        accuracy=round(min(1.0, max(0.0, accuracy)), 4),
        specificity=round(min(1.0, max(0.0, specificity)), 4),
        cohens_kappa=round(min(1.0, max(-1.0, kappa)), 4),
        flooded_area_observed_km2=round(obs_flood, 2),
        flooded_area_predicted_km2=round(pred_flood, 2),
        intersection_area_km2=round(intersection_area, 2),
        union_area_km2=round(union_area, 2),
        flooded_area_agreement=round(min(1.0, max(0.0, area_agreement)), 4),
        confusion_matrix=cm,
    )
