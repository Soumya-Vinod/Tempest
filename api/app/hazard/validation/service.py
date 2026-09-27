"""Validation service layer bridging benchmark outputs and HTTP API endpoints.

Responses are generated directly from pre-computed benchmark artifacts.
Routes are strictly read-only — the pipeline is never executed inside a
user request.  If the committed artifacts are missing, routes return 503.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.hazard.validation.config import (
    VALIDATION_ARTIFACTS_DIR,
)
from app.hazard.validation.datasets import AdminBoundariesDataset

logger = logging.getLogger(__name__)


class ValidationDataUnavailableError(Exception):
    """Raised when committed validation artifacts are missing."""


def _get_benchmark_suite() -> dict[str, Any]:
    """Load the committed benchmark suite from disk (read-only).

    Raises ``ValidationDataUnavailableError`` if the file is missing so that
    the calling route can translate it into an HTTP 503.
    """
    suite_path = VALIDATION_ARTIFACTS_DIR / "benchmark_suite.json"
    if not suite_path.is_file():
        raise ValidationDataUnavailableError(
            "Validation benchmark data has not been generated. "
            "Run `python scripts/run_sentinel_validation.py` offline first."
        )
    return json.loads(suite_path.read_text(encoding="utf-8"))


def _resolve_block_key(block_param: str) -> str:
    """Resolve user-supplied block parameter to dictionary key."""
    clean = block_param.strip().lower().replace(" ", "_")
    dataset = AdminBoundariesDataset()
    try:
        block = dataset.get_block(clean)
        return block.name.lower().replace(" ", "_")
    except KeyError:
        return clean


def get_validation_overview() -> dict[str, Any]:
    """Return overview summary of all benchmarked coastal blocks."""
    suite = _get_benchmark_suite()
    blocks_data = suite.get("blocks", {})

    summaries = []
    for b_key, b_val in blocks_data.items():
        b_meta = b_val.get("block", {})
        m = b_val.get("metrics", {})
        summaries.append(
            {
                "identifier": b_meta.get("identifier", b_key),
                "name": b_meta.get("name", b_key.title()),
                "census_code": b_meta.get("census_code", ""),
                "area_km2": b_meta.get("area_km2", 0.0),
                "population": b_meta.get("population", 0),
                "observed_flood_km2": m.get("flooded_area_observed_km2", 0.0),
                "predicted_flood_km2": m.get("flooded_area_predicted_km2", 0.0),
                "iou": m.get("iou", 0.0),
                "precision": m.get("precision", 0.0),
                "recall": m.get("recall", 0.0),
                "f1_score": m.get("f1_score", 0.0),
                "accuracy": m.get("accuracy", 0.0),
                "specificity": m.get("specificity", 0.0),
                "cohens_kappa": m.get("cohens_kappa", 0.0),
            }
        )

    return {
        "execution_timestamp": suite.get("execution_timestamp", ""),
        "event_name": suite.get("event_name", "Cyclone Amphan"),
        "landfall_timestamp": suite.get("landfall_timestamp", "2020-05-20T12:00:00Z"),
        "aggregate_metrics": suite.get("aggregate_metrics", {}),
        "blocks": summaries,
    }


def get_block_validation(block_param: str) -> dict[str, Any] | None:
    """Return comprehensive validation report for a specific administrative block."""
    suite = _get_benchmark_suite()
    blocks_data = suite.get("blocks", {})
    resolved_key = _resolve_block_key(block_param)

    if resolved_key not in blocks_data:
        return None

    block_info = dict(blocks_data[resolved_key])
    # Enrich artifact links
    artifacts_map = block_info.get("artifacts", {})
    enriched_artifacts = {}
    for k, v in artifacts_map.items():
        fname = Path(v).name
        enriched_artifacts[k] = {
            "name": fname,
            "path": v,
            "url": f"/api/hazard/validation/{resolved_key}/artifacts/{fname}",
        }
    block_info["artifact_downloads"] = enriched_artifacts
    return block_info


def get_block_metrics(block_param: str) -> dict[str, Any] | None:
    """Return quantitative benchmark metrics for a specific administrative block."""
    block_val = get_block_validation(block_param)
    if not block_val:
        return None
    return {
        "block": block_val.get("block"),
        "metrics": block_val.get("metrics"),
    }


def get_block_artifacts(block_param: str) -> dict[str, Any] | None:
    """List available exported artifacts for a block with metadata and download URLs."""
    resolved_key = _resolve_block_key(block_param)
    block_dir = VALIDATION_ARTIFACTS_DIR / resolved_key
    if not block_dir.is_dir():
        return None

    artifact_list = []
    for item in sorted(block_dir.iterdir()):
        if item.is_file():
            artifact_list.append(
                {
                    "name": item.name,
                    "suffix": item.suffix.lstrip("."),
                    "size_bytes": item.stat().st_size,
                    "url": f"/api/hazard/validation/{resolved_key}/artifacts/{item.name}",
                }
            )

    return {
        "block": resolved_key,
        "artifacts": artifact_list,
    }


def get_artifact_file_path(block_param: str, artifact_name: str) -> Path | None:
    """Resolve physical file path for an exported artifact."""
    resolved_key = _resolve_block_key(block_param)
    block_dir = VALIDATION_ARTIFACTS_DIR / resolved_key
    target_file = block_dir / artifact_name

    # Path traversal protection
    try:
        resolved_target = target_file.resolve()
        resolved_base = VALIDATION_ARTIFACTS_DIR.resolve()
        if not str(resolved_target).startswith(str(resolved_base)):
            return None
    except Exception:
        return None

    if target_file.is_file():
        return target_file
    return None
