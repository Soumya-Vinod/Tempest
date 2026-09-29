"""Advisory suggestion rule (v1.3 change, pending Dev A), shared by GET /api/advisory/suggestions
and the action countdown's "first alert" key moment, so the two can't disagree.

A block is suggested at a timestep when, on the expected hazard (horizon 24):
- its risk score is at least SUGGEST_MIN_SCORE, or
- a facility inside it is isolated in the horizon-24 impact results (expected to be cut off
  within 24 h; that includes facilities already cut off). Facilities that don't count for
  advisories (weights.counts_for_advisory: nursing homes, diagnostic centres...) are skipped.
Each suggestion says why, one reason per cause.
"""

from collections.abc import Iterable

import geopandas as gpd
import shapely
from shapely.geometry import shape

from app.exposure.ingest import METRIC_CRS
from app.impact.engine import feature_label
from app.risk import weights as W
from app.risk.blocks import Blocks
from app.schemas import AdvisorySuggestion, InfraFeature, SuggestionReason

SUGGEST_MIN_SCORE = 0.25  # blocks at or above this risk score are suggested for an advisory


def facility_blocks(features: Iterable[InfraFeature], blocks: Blocks) -> dict[str, str]:
    """Hospital and shelter id -> the CD block containing its point (as the risk engine assigns
    points: within the block polygon, metric CRS). Facilities outside every block are left out."""
    points = [
        f
        for f in features
        if f.properties.infra_type in ("hospital", "shelter") and f.geometry.type == "Point"
    ]
    if not points:
        return {}
    pts = gpd.GeoSeries([shape(f.geometry.model_dump()) for f in points], crs="EPSG:4326")
    tree = shapely.STRtree(blocks.metric.to_numpy())
    p_idx, b_idx = tree.query(pts.to_crs(METRIC_CRS).to_numpy(), predicate="within")
    out: dict[str, str] = {}
    for p, b in zip(p_idx, b_idx, strict=True):
        out.setdefault(points[p].id, blocks.codes[int(b)])
    return out


def expected_by_block(
    isolated_ids: Iterable[str], infra: dict[str, InfraFeature], blocks_of: dict[str, str]
) -> dict[str, list[InfraFeature]]:
    """Block code -> the facilities in it isolated at horizon 24 that count for advisories,
    by name."""
    out: dict[str, list[InfraFeature]] = {}
    for i in isolated_ids:
        f = infra.get(i)
        if f is None or i not in blocks_of or not W.counts_for_advisory(f.properties.name):
            continue
        out.setdefault(blocks_of[i], []).append(f)
    for fs in out.values():
        fs.sort(key=feature_label)
    return out


def suggest(
    scores: Iterable[tuple[str, str, float]],
    expected: dict[str, list[InfraFeature]],
    threshold: float = SUGGEST_MIN_SCORE,
) -> list[AdvisorySuggestion]:
    """Suggested blocks, highest score first (then by name), each with its reasons: the risk
    score if at or above the threshold, then each facility expected to be cut off.
    `scores`: (block_id, block_name, horizon-24 score) for every block."""
    out = []
    for block_id, name, score in scores:
        reasons = []
        if score >= threshold:
            reasons.append(SuggestionReason(kind="risk", label=f"risk {score:.2f}", infra_id=None))
        for f in expected.get(block_id, []):
            reasons.append(
                SuggestionReason(
                    kind="expected_cut_off",
                    label=f"{feature_label(f)} expected to be cut off",
                    infra_id=f.id,
                )
            )
        if reasons:
            out.append(
                AdvisorySuggestion(block_id=block_id, block_name=name, score=score, reasons=reasons)
            )
    out.sort(key=lambda s: (-s.score, s.block_name))
    return out
