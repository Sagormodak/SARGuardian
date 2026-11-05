"""Held-out event-level evaluation for future calibrated hazard detectors.

This module evaluates an independently labelled event registry plus frozen
per-case predictions. It does not create a detector, invent a risk score, or
allow a threshold to be selected using held-out test labels.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Iterable

import numpy as np

from .geometry import parse_polygon_wkt
from .goff_io import GoffReadError

REGISTRY_SCHEMA = "know-place-event-registry/1.0"
THRESHOLD_SCHEMA = "know-place-frozen-threshold-policy/1.1"
VALIDATION_SCORE_SCHEMA = "know-place-validation-scores/1.1"
PREDICTION_SCHEMA = "know-place-event-predictions/1.1"
SPLITS = {"development", "validation", "test"}
PREDICTION_STATES = {"ALERT", "NO_ALERT", "NO_RESULT"}
METRIC_NAMES = ("precision", "recall", "specificity", "f1")


class EventValidationError(ValueError):
    """Registry, frozen threshold or held-out prediction contract failed."""


def _canonical_sha256(value: dict[str, Any], *, exclude: set[str] = frozenset()) -> str:
    body = {key: item for key, item in value.items() if key not in exclude}
    encoded = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validated_sha256(value: Any, code: str) -> str:
    if not isinstance(value, str):
        raise EventValidationError(code)
    digest = value.strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise EventValidationError(code)
    return digest


def _source_product_hashes(value: Any, code_prefix: str) -> list[str]:
    if not isinstance(value, list):
        raise EventValidationError(f"{code_prefix}_SOURCE_PRODUCT_HASHES_REQUIRED")
    return [
        _validated_sha256(item, f"{code_prefix}_SOURCE_PRODUCT_HASH_INVALID")
        for item in value
    ]


def _required_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EventValidationError(code)
    return value.strip()


def _utc_datetime(value: Any, code: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise EventValidationError(code)
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventValidationError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EventValidationError(f"{code}_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _canonical_geometry_identity(wkt: str) -> str:
    """Hash a polygon ring independent of its start vertex or winding direction."""
    ring = parse_polygon_wkt(wkt)
    vertices = tuple((float(lon), float(lat)) for lon, lat in ring[:-1])
    candidates = []
    for sequence in (vertices, tuple(reversed(vertices))):
        for offset in range(len(sequence)):
            candidates.append(sequence[offset:] + sequence[:offset])
    canonical_ring = min(candidates)
    return _canonical_sha256({"canonical_wgs84_ring": [[lon, lat] for lon, lat in canonical_ring]})


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return float(numerator / denominator) if denominator else None


def seal_threshold_policy(policy_without_hash: dict[str, Any]) -> dict[str, Any]:
    """Return a content-addressed threshold policy which must be frozen pre-test."""
    policy = dict(policy_without_hash)
    if "policy_sha256" in policy:
        raise EventValidationError("THRESHOLD_POLICY_MUST_NOT_PREDECLARE_HASH")
    policy["policy_sha256"] = _canonical_sha256(policy)
    return policy


def validate_event_registry(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate independent event labels and return a canonical registry identity."""
    if not isinstance(payload, dict) or payload.get("schema_version") != REGISTRY_SCHEMA:
        raise EventValidationError("EVENT_REGISTRY_SCHEMA_UNSUPPORTED")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EventValidationError("EVENT_REGISTRY_CASES_MUST_BE_NONEMPTY_ARRAY")

    normalized_cases: list[dict[str, Any]] = []
    case_ids: set[str] = set()
    geometry_site_ids: dict[str, str] = {}
    for index, raw in enumerate(raw_cases):
        prefix = f"CASE_{index}"
        if not isinstance(raw, dict):
            raise EventValidationError(f"{prefix}_MUST_BE_OBJECT")
        case_id = _required_text(raw.get("case_id"), f"{prefix}_ID_REQUIRED")
        if case_id in case_ids:
            raise EventValidationError(f"CASE_ID_DUPLICATE:{case_id}")
        case_ids.add(case_id)

        site_id = _required_text(raw.get("site_id"), f"{case_id}_SITE_ID_REQUIRED")
        split = raw.get("split")
        if split not in SPLITS:
            raise EventValidationError(f"{case_id}_SPLIT_UNSUPPORTED")
        label = raw.get("event_label")
        if not isinstance(label, bool):
            raise EventValidationError(f"{case_id}_INDEPENDENT_EVENT_LABEL_REQUIRED")
        hazard = _required_text(raw.get("hazard_type"), f"{case_id}_HAZARD_TYPE_REQUIRED").lower()
        if hazard not in {"landslide", "glacier_collapse", "ice_rock_avalanche", "non_event"}:
            raise EventValidationError(f"{case_id}_HAZARD_TYPE_UNSUPPORTED")
        if (hazard == "non_event") == label:
            raise EventValidationError(f"{case_id}_HAZARD_TYPE_LABEL_CONFLICT")

        aoi_wkt = _required_text(raw.get("aoi_wkt"), f"{case_id}_AOI_WKT_REQUIRED")
        try:
            parse_polygon_wkt(aoi_wkt)
        except GoffReadError as exc:
            raise EventValidationError(f"{case_id}_AOI_GEOMETRY_INVALID:{exc}") from exc
        geometry_sha = _canonical_sha256({"aoi_wkt": aoi_wkt})
        geometry_identity = _canonical_geometry_identity(aoi_wkt)
        previous_site_id = geometry_site_ids.get(geometry_identity)
        if previous_site_id is not None and previous_site_id != site_id:
            raise EventValidationError(
                f"{case_id}_AOI_GEOMETRY_ASSIGNED_TO_MULTIPLE_SITE_IDS"
            )
        geometry_site_ids[geometry_identity] = site_id
        declared_geometry_sha = raw.get("aoi_geometry_sha256")
        if declared_geometry_sha is not None and declared_geometry_sha != geometry_sha:
            raise EventValidationError(f"{case_id}_AOI_GEOMETRY_CHECKSUM_MISMATCH")

        evidence = raw.get("independent_label_evidence")
        if not isinstance(evidence, dict):
            raise EventValidationError(f"{case_id}_INDEPENDENT_LABEL_EVIDENCE_REQUIRED")
        source_url = _required_text(
            evidence.get("source_url_or_doi"), f"{case_id}_INDEPENDENT_EVIDENCE_REFERENCE_REQUIRED"
        )
        label_method = _required_text(
            evidence.get("label_method"), f"{case_id}_LABEL_METHOD_REQUIRED"
        )
        if evidence.get("reviewed_independently") is not True:
            raise EventValidationError(f"{case_id}_LABEL_NOT_INDEPENDENTLY_REVIEWED")

        observation = raw.get("observation_window_utc")
        if not isinstance(observation, dict):
            raise EventValidationError(f"{case_id}_OBSERVATION_WINDOW_REQUIRED")
        obs_start = _utc_datetime(observation.get("start"), f"{case_id}_OBSERVATION_START_INVALID")
        obs_end = _utc_datetime(observation.get("end"), f"{case_id}_OBSERVATION_END_INVALID")
        if obs_end <= obs_start:
            raise EventValidationError(f"{case_id}_OBSERVATION_WINDOW_ORDER_INVALID")

        event_time_value = raw.get("event_time_utc")
        event_time = None
        if label:
            event_time = _utc_datetime(event_time_value, f"{case_id}_EVENT_TIME_REQUIRED")
        elif event_time_value is not None:
            event_time = _utc_datetime(event_time_value, f"{case_id}_EVENT_TIME_INVALID")

        exposure = raw.get("monitoring_exposure_aoi_months")
        if isinstance(exposure, bool) or not isinstance(exposure, (int, float)):
            raise EventValidationError(f"{case_id}_MONITORING_EXPOSURE_MUST_BE_NUMERIC")
        if not math.isfinite(float(exposure)) or exposure < 0:
            raise EventValidationError(f"{case_id}_MONITORING_EXPOSURE_INVALID")

        products = raw.get("source_products", [])
        if not isinstance(products, list):
            raise EventValidationError(f"{case_id}_SOURCE_PRODUCTS_MUST_BE_ARRAY")
        product_rows = []
        seen_products: set[str] = set()
        for product_index, product in enumerate(products):
            if not isinstance(product, dict):
                raise EventValidationError(f"{case_id}_SOURCE_PRODUCT_{product_index}_INVALID")
            granule = _required_text(product.get("granule_name"), f"{case_id}_SOURCE_GRANULE_NAME_REQUIRED")
            sha = _required_text(product.get("sha256"), f"{case_id}_SOURCE_SHA256_REQUIRED").lower()
            if len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha):
                raise EventValidationError(f"{case_id}_SOURCE_SHA256_INVALID")
            if granule in seen_products:
                raise EventValidationError(f"{case_id}_SOURCE_GRANULE_DUPLICATE:{granule}")
            seen_products.add(granule)
            product_rows.append({"granule_name": granule, "sha256": sha})

        normalized_cases.append({
            "case_id": case_id,
            "site_id": site_id,
            "split": split,
            "event_label": label,
            "hazard_type": hazard,
            "aoi_wkt": aoi_wkt,
            "aoi_geometry_sha256": geometry_sha,
            "independent_label_evidence": {
                "source_url_or_doi": source_url,
                "label_method": label_method,
                "reviewed_independently": True,
            },
            "observation_window_utc": {
                "start": obs_start.isoformat().replace("+00:00", "Z"),
                "end": obs_end.isoformat().replace("+00:00", "Z"),
            },
            "event_time_utc": event_time.isoformat().replace("+00:00", "Z") if event_time else None,
            "monitoring_exposure_aoi_months": float(exposure),
            "source_products": product_rows,
        })

    registry_body = {
        "schema_version": REGISTRY_SCHEMA,
        "label_policy": _required_text(payload.get("label_policy"), "EVENT_REGISTRY_LABEL_POLICY_REQUIRED"),
        "cases": normalized_cases,
    }
    declared_registry_sha = payload.get("registry_sha256")
    registry_sha = _canonical_sha256(registry_body)
    if declared_registry_sha is not None and declared_registry_sha != registry_sha:
        raise EventValidationError("EVENT_REGISTRY_CHECKSUM_MISMATCH")
    return {**registry_body, "registry_sha256": registry_sha}


def select_validation_threshold(
    registry_payload: dict[str, Any],
    validation_scores_payload: dict[str, Any],
    *,
    model_policy_name: str,
    model_policy_sha256: str,
    score_name: str,
    objective: str = "max_youden_j",
    decision_rule: str = ">=",
    minimum_specificity: float | None = None,
) -> dict[str, Any]:
    """Choose a threshold using only the registry's validation split and seal it.

    Supported objectives are max_youden_j, max_f1, or
    max_recall_at_min_specificity. The objective and any specificity constraint
    become part of the content-addressed policy, making threshold selection
    reproducible and distinct from the held-out test evaluation.
    """
    raw_registry_cases = registry_payload.get("cases") if isinstance(registry_payload, dict) else None
    if isinstance(raw_registry_cases, list) and any(
        isinstance(case, dict) and case.get("split") != "validation"
        for case in raw_registry_cases
    ):
        raise EventValidationError("VALIDATION_REGISTRY_MUST_CONTAIN_VALIDATION_CASES_ONLY")
    registry = validate_event_registry(registry_payload)
    _required_text(model_policy_name, "THRESHOLD_MODEL_POLICY_NAME_REQUIRED")
    model_policy_sha = _validated_sha256(model_policy_sha256, "THRESHOLD_MODEL_POLICY_SHA256_INVALID")
    _required_text(score_name, "THRESHOLD_SCORE_NAME_REQUIRED")
    if objective not in {"max_youden_j", "max_f1", "max_recall_at_min_specificity"}:
        raise EventValidationError("THRESHOLD_SELECTION_OBJECTIVE_UNSUPPORTED")
    if decision_rule not in {">=", ">"}:
        raise EventValidationError("THRESHOLD_POLICY_DECISION_RULE_UNSUPPORTED")
    if objective == "max_recall_at_min_specificity":
        if (
            isinstance(minimum_specificity, bool)
            or not isinstance(minimum_specificity, (int, float))
            or not math.isfinite(float(minimum_specificity))
            or not 0.0 <= float(minimum_specificity) <= 1.0
        ):
            raise EventValidationError("MINIMUM_SPECIFICITY_REQUIRED_FOR_OBJECTIVE")
    elif minimum_specificity is not None:
        raise EventValidationError("MINIMUM_SPECIFICITY_ONLY_ALLOWED_FOR_CONSTRAINED_RECALL_OBJECTIVE")

    if not isinstance(validation_scores_payload, dict) or validation_scores_payload.get("schema_version") != VALIDATION_SCORE_SCHEMA:
        raise EventValidationError("VALIDATION_SCORE_SCHEMA_UNSUPPORTED")
    scores_policy_sha = _validated_sha256(
        validation_scores_payload.get("model_policy_sha256"),
        "VALIDATION_SCORE_MODEL_POLICY_SHA256_INVALID",
    )
    if scores_policy_sha != model_policy_sha:
        raise EventValidationError("VALIDATION_SCORE_MODEL_POLICY_HASH_MISMATCH")
    raw_rows = validation_scores_payload.get("cases")
    if not isinstance(raw_rows, list):
        raise EventValidationError("VALIDATION_SCORES_CASES_MUST_BE_ARRAY")
    validation_cases = {case["case_id"]: case for case in registry["cases"]}
    if not validation_cases:
        raise EventValidationError("NO_VALIDATION_SPLIT_CASES")

    scores: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, dict):
            raise EventValidationError(f"VALIDATION_SCORE_{index}_MUST_BE_OBJECT")
        case_id = _required_text(raw.get("case_id"), f"VALIDATION_SCORE_{index}_CASE_ID_REQUIRED")
        if case_id not in validation_cases:
            raise EventValidationError(f"VALIDATION_SCORE_NOT_VALIDATION_CASE:{case_id}")
        if case_id in scores:
            raise EventValidationError(f"VALIDATION_SCORE_CASE_DUPLICATE:{case_id}")
        source_hashes = _source_product_hashes(raw.get("source_product_sha256s"), "VALIDATION_SCORE")
        expected_hashes = [product["sha256"] for product in validation_cases[case_id]["source_products"]]
        if sorted(source_hashes) != sorted(expected_hashes):
            raise EventValidationError(f"VALIDATION_SCORE_SOURCE_PRODUCT_HASH_MISMATCH:{case_id}")
        state = raw.get("state")
        if state not in {"SCORED", "NO_RESULT"}:
            raise EventValidationError(f"VALIDATION_SCORE_STATE_UNSUPPORTED:{case_id}")
        value = raw.get("score")
        if state == "NO_RESULT":
            if value is not None:
                raise EventValidationError(f"VALIDATION_NO_RESULT_MUST_NOT_HAVE_SCORE:{case_id}")
        else:
            if not validation_cases[case_id]["source_products"]:
                raise EventValidationError(f"VALIDATION_SCORE_WITHOUT_VERIFIED_SOURCE_PRODUCTS:{case_id}")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise EventValidationError(f"VALIDATION_SCORE_NONFINITE_OR_MISSING:{case_id}")
        scores[case_id] = {
            "case_id": case_id,
            "state": state,
            "score": float(value) if value is not None else None,
            "source_product_sha256s": source_hashes,
        }

    if set(scores) != set(validation_cases):
        missing = sorted(set(validation_cases) - set(scores))
        raise EventValidationError("VALIDATION_SCORES_INCOMPLETE:" + ",".join(missing))

    scored = [
        {**validation_cases[case_id], **row, "state": (
            "ALERT" if row["state"] == "SCORED" else "NO_RESULT"
        )}
        for case_id, row in scores.items()
        if row["state"] == "SCORED"
    ]
    if not any(row["event_label"] for row in scored):
        raise EventValidationError("VALIDATION_SCORES_HAVE_NO_POSITIVE_EVENTS")
    if not any(not row["event_label"] for row in scored):
        raise EventValidationError("VALIDATION_SCORES_HAVE_NO_NON_EVENT_CONTROLS")

    unique_scores = sorted({row["score"] for row in scored})
    candidates = set(unique_scores)
    below_min = float(np.nextafter(unique_scores[0], -math.inf))
    above_max = float(np.nextafter(unique_scores[-1], math.inf))
    if math.isfinite(below_min):
        candidates.add(below_min)
    if math.isfinite(above_max):
        candidates.add(above_max)

    rows: list[dict[str, Any]] = []
    for threshold in sorted(candidates):
        candidate_rows = []
        for row in scored:
            should_alert = row["score"] >= threshold if decision_rule == ">=" else row["score"] > threshold
            candidate_rows.append({**row, "state": "ALERT" if should_alert else "NO_ALERT"})
        metric_row = _confusion_metrics(candidate_rows)
        specificity = metric_row["specificity"]
        recall = metric_row["recall"]
        f1 = metric_row["f1"]
        youden = recall + specificity - 1.0 if recall is not None and specificity is not None else None
        rows.append({
            "threshold": float(threshold),
            **metric_row,
            "youden_j": youden,
            "selection_objective": objective,
            "meets_minimum_specificity": (
                specificity is not None and specificity >= float(minimum_specificity)
                if objective == "max_recall_at_min_specificity" else None
            ),
        })

    if objective == "max_youden_j":
        selected = max(rows, key=lambda row: (
            row["youden_j"] if row["youden_j"] is not None else -math.inf,
            row["recall"] if row["recall"] is not None else -math.inf,
            row["specificity"] if row["specificity"] is not None else -math.inf,
            row["threshold"],
        ))
    elif objective == "max_f1":
        selected = max(rows, key=lambda row: (
            row["f1"] if row["f1"] is not None else -math.inf,
            row["specificity"] if row["specificity"] is not None else -math.inf,
            row["threshold"],
        ))
    else:
        feasible = [
            row for row in rows
            if row["meets_minimum_specificity"] is True and row["recall"] is not None
        ]
        if not feasible:
            raise EventValidationError("NO_THRESHOLD_MEETS_MINIMUM_SPECIFICITY")
        selected = max(feasible, key=lambda row: (
            row["recall"],
            row["precision"] if row["precision"] is not None else -math.inf,
            row["specificity"] if row["specificity"] is not None else -math.inf,
            row["threshold"],
        ))

    all_event_count = sum(case["event_label"] for case in validation_cases.values())
    conservative_tp = sum(
        case["event_label"] and scores[case_id]["state"] == "SCORED"
        and (
            scores[case_id]["score"] >= selected["threshold"]
            if decision_rule == ">="
            else scores[case_id]["score"] > selected["threshold"]
        )
        for case_id, case in validation_cases.items()
    )
    base_policy = {
        "schema_version": THRESHOLD_SCHEMA,
        "model_policy_name": model_policy_name,
        "model_policy_sha256": model_policy_sha,
        "score_name": score_name,
        "threshold": selected["threshold"],
        "decision_rule": decision_rule,
        "threshold_selection_split": "validation",
        "threshold_selection_objective": objective,
        "minimum_specificity": float(minimum_specificity) if minimum_specificity is not None else None,
        "frozen_before_test": True,
        "validation_registry_sha256": registry["registry_sha256"],
        "validation_case_ids_sha256": _canonical_sha256({"case_ids": sorted(validation_cases)}),
        "validation_scores_sha256": _canonical_sha256(validation_scores_payload),
        "selection_evidence": "Threshold selected from validation-split scores only; do not revise after held-out test scoring.",
    }
    policy = seal_threshold_policy(base_policy)
    return {
        "schema_version": "know-place-validation-threshold-selection/1.0",
        "status": "THRESHOLD_SELECTED_ON_VALIDATION_SPLIT",
        "validation_registry_sha256": registry["registry_sha256"],
        "validation_scores_sha256": _canonical_sha256(validation_scores_payload),
        "objective": objective,
        "minimum_specificity": float(minimum_specificity) if minimum_specificity is not None else None,
        "validation_case_count": len(validation_cases),
        "validation_scored_case_count": len(scored),
        "validation_no_result_case_count": len(validation_cases) - len(scored),
        "conservative_recall_all_validation_events": _safe_ratio(conservative_tp, all_event_count),
        "selected_validation_metrics": selected,
        "candidate_threshold_count": len(rows),
        "threshold_policy": policy,
        "limitations": [
            "The selected threshold is calibrated only to the validation set and declared objective.",
            "The validation score must itself be produced by a scientifically specified detector policy.",
            "Selecting a threshold does not justify deploying it; held-out test evaluation and site-level uncertainty are mandatory.",
        ],
    }


def _confusion_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(row["event_label"] and row["state"] == "ALERT" for row in rows)
    fp = sum((not row["event_label"]) and row["state"] == "ALERT" for row in rows)
    tn = sum((not row["event_label"]) and row["state"] == "NO_ALERT" for row in rows)
    fn = sum(row["event_label"] and row["state"] == "NO_ALERT" for row in rows)
    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    specificity = _safe_ratio(tn, tn + fp)
    f1 = _safe_ratio(2 * precision * recall, precision + recall) if precision is not None and recall is not None else None
    return {
        "evaluated_cases": len(rows),
        "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn),
        "precision": precision, "recall": recall, "specificity": specificity, "f1": f1,
    }


def _cluster_bootstrap_intervals(
    rows: list[dict[str, Any]],
    *,
    replicates: int,
    seed: int,
    minimum_sites: int,
    minimum_positive_sites: int = 5,
    minimum_non_event_sites: int = 5,
    minimum_defined_fraction: float = 0.95,
) -> dict[str, Any]:
    sites = sorted({row["site_id"] for row in rows})
    positive_sites = {row["site_id"] for row in rows if row["event_label"]}
    non_event_sites = {row["site_id"] for row in rows if not row["event_label"]}
    base = {
        "independent_sites": len(sites),
        "independent_positive_event_sites": len(positive_sites),
        "independent_non_event_sites": len(non_event_sites),
        "minimum_sites_required": minimum_sites,
        "minimum_positive_event_sites_required": minimum_positive_sites,
        "minimum_non_event_sites_required": minimum_non_event_sites,
        "minimum_defined_bootstrap_fraction_required": minimum_defined_fraction,
        "intervals": {name: None for name in METRIC_NAMES},
        "defined_replicates": {name: 0 for name in METRIC_NAMES},
        "defined_replicate_fraction": {name: 0.0 for name in METRIC_NAMES},
        "withheld_metrics": list(METRIC_NAMES),
    }
    if len(sites) < minimum_sites:
        return {"status": "INSUFFICIENT_INDEPENDENT_SITES", **base}
    if len(positive_sites) < minimum_positive_sites or len(non_event_sites) < minimum_non_event_sites:
        return {"status": "INSUFFICIENT_INDEPENDENT_CLASS_SITES", **base}

    grouped = {site: [row for row in rows if row["site_id"] == site] for site in sites}
    rng = np.random.default_rng(seed)
    sampled: dict[str, list[float]] = {name: [] for name in METRIC_NAMES}
    for _ in range(replicates):
        chosen = rng.choice(sites, size=len(sites), replace=True)
        sample_rows = [row for site in chosen for row in grouped[str(site)]]
        metrics = _confusion_metrics(sample_rows)
        for name in METRIC_NAMES:
            value = metrics[name]
            if value is not None and math.isfinite(value):
                sampled[name].append(float(value))

    defined_counts = {name: len(values) for name, values in sampled.items()}
    defined_fractions = {name: count / replicates for name, count in defined_counts.items()}
    withheld = [
        name for name in METRIC_NAMES
        if defined_fractions[name] < minimum_defined_fraction
    ]
    intervals = {
        name: (
            [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]
            if values and defined_fractions[name] >= minimum_defined_fraction else None
        )
        for name, values in sampled.items()
    }
    return {
        "status": "COMPUTED_SITE_CLUSTER_BOOTSTRAP" if not withheld else "INSUFFICIENT_DEFINED_BOOTSTRAP_REPLICATES",
        **{key: value for key, value in base.items() if key not in {"intervals", "defined_replicates", "defined_replicate_fraction", "withheld_metrics"}},
        "replicates": replicates,
        "seed": seed,
        "prng": "numpy.default_rng/PCG64",
        "intervals": intervals,
        "defined_replicates": defined_counts,
        "defined_replicate_fraction": defined_fractions,
        "withheld_metrics": withheld,
        "interpretation": "Percentile intervals use site-cluster resampling. A metric interval is withheld unless at least 95% of requested replicates define that metric; sites, not pixels, are resampled.",
    }


def evaluate_heldout_events(
    registry_payload: dict[str, Any],
    prediction_payload: dict[str, Any],
    threshold_policy: dict[str, Any],
    *,
    validation_registry_payload: dict[str, Any] | None = None,
    bootstrap_replicates: int = 2000,
    bootstrap_seed: int = 260826,
    minimum_independent_sites_for_ci: int = 5,
    minimum_independent_positive_sites_for_ci: int = 5,
    minimum_independent_non_event_sites_for_ci: int = 5,
) -> dict[str, Any]:
    """Score only held-out test cases against a content-addressed frozen policy.

    Predictions must already have been produced by a detector/measurement policy.
    This function does not derive a risk score from displacement and is not itself
    evidence that the detection method has been calibrated.
    """
    raw_test_cases = registry_payload.get("cases") if isinstance(registry_payload, dict) else None
    if isinstance(raw_test_cases, list) and any(
        isinstance(case, dict) and case.get("split") != "test"
        for case in raw_test_cases
    ):
        raise EventValidationError("HELDOUT_REGISTRY_MUST_CONTAIN_TEST_CASES_ONLY")
    registry = validate_event_registry(registry_payload)
    if validation_registry_payload is None:
        raise EventValidationError("VALIDATION_REGISTRY_REQUIRED_TO_VERIFY_FROZEN_THRESHOLD")
    raw_validation_cases = validation_registry_payload.get("cases") if isinstance(validation_registry_payload, dict) else None
    if isinstance(raw_validation_cases, list) and any(
        isinstance(case, dict) and case.get("split") != "validation"
        for case in raw_validation_cases
    ):
        raise EventValidationError("VALIDATION_REGISTRY_MUST_CONTAIN_VALIDATION_CASES_ONLY")
    validation_registry = validate_event_registry(validation_registry_payload)
    validation_site_ids = {case["site_id"] for case in validation_registry["cases"]}
    test_site_ids = {case["site_id"] for case in registry["cases"]}
    overlapping_site_ids = sorted(validation_site_ids & test_site_ids)
    if overlapping_site_ids:
        raise EventValidationError(
            "VALIDATION_TEST_SITE_OVERLAP:" + ",".join(overlapping_site_ids)
        )
    validation_geometry_ids = {
        _canonical_geometry_identity(case["aoi_wkt"]) for case in validation_registry["cases"]
    }
    test_geometry_ids = {
        _canonical_geometry_identity(case["aoi_wkt"]) for case in registry["cases"]
    }
    overlapping_geometry_ids = sorted(validation_geometry_ids & test_geometry_ids)
    if overlapping_geometry_ids:
        raise EventValidationError(
            "VALIDATION_TEST_AOI_GEOMETRY_OVERLAP:" + ",".join(overlapping_geometry_ids)
        )
    if not isinstance(threshold_policy, dict) or threshold_policy.get("schema_version") != THRESHOLD_SCHEMA:
        raise EventValidationError("THRESHOLD_POLICY_SCHEMA_UNSUPPORTED")
    if threshold_policy.get("threshold_selection_split") != "validation":
        raise EventValidationError("THRESHOLD_MUST_BE_SELECTED_ON_VALIDATION_SPLIT")
    _required_text(threshold_policy.get("model_policy_name"), "THRESHOLD_MODEL_POLICY_NAME_REQUIRED")
    threshold_model_policy_sha = _validated_sha256(
        threshold_policy.get("model_policy_sha256"),
        "THRESHOLD_MODEL_POLICY_SHA256_INVALID",
    )
    _required_text(threshold_policy.get("score_name"), "THRESHOLD_SCORE_NAME_REQUIRED")
    if threshold_policy.get("frozen_before_test") is not True:
        raise EventValidationError("THRESHOLD_POLICY_NOT_FROZEN_BEFORE_TEST")
    if threshold_policy.get("validation_registry_sha256") != validation_registry["registry_sha256"]:
        raise EventValidationError("THRESHOLD_POLICY_VALIDATION_REGISTRY_CHECKSUM_MISMATCH")
    threshold = threshold_policy.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(float(threshold)):
        raise EventValidationError("THRESHOLD_POLICY_THRESHOLD_INVALID")
    rule = threshold_policy.get("decision_rule", ">=")
    if rule not in {">=", ">"}:
        raise EventValidationError("THRESHOLD_POLICY_DECISION_RULE_UNSUPPORTED")
    policy_sha = threshold_policy.get("policy_sha256")
    if not isinstance(policy_sha, str) or len(policy_sha) != 64:
        raise EventValidationError("THRESHOLD_POLICY_CHECKSUM_REQUIRED")
    if _canonical_sha256(threshold_policy, exclude={"policy_sha256"}) != policy_sha:
        raise EventValidationError("THRESHOLD_POLICY_CHECKSUM_MISMATCH")
    if isinstance(bootstrap_replicates, bool) or not isinstance(bootstrap_replicates, int) or bootstrap_replicates < 100:
        raise EventValidationError("BOOTSTRAP_REPLICATES_MUST_BE_AT_LEAST_100")
    if isinstance(minimum_independent_sites_for_ci, bool) or not isinstance(minimum_independent_sites_for_ci, int) or minimum_independent_sites_for_ci < 2:
        raise EventValidationError("MINIMUM_INDEPENDENT_SITES_INVALID")
    if (
        isinstance(minimum_independent_positive_sites_for_ci, bool)
        or not isinstance(minimum_independent_positive_sites_for_ci, int)
        or minimum_independent_positive_sites_for_ci < 2
    ):
        raise EventValidationError("MINIMUM_INDEPENDENT_POSITIVE_SITES_INVALID")
    if (
        isinstance(minimum_independent_non_event_sites_for_ci, bool)
        or not isinstance(minimum_independent_non_event_sites_for_ci, int)
        or minimum_independent_non_event_sites_for_ci < 2
    ):
        raise EventValidationError("MINIMUM_INDEPENDENT_NON_EVENT_SITES_INVALID")

    if not isinstance(prediction_payload, dict) or prediction_payload.get("schema_version") != PREDICTION_SCHEMA:
        raise EventValidationError("PREDICTION_SCHEMA_UNSUPPORTED")
    prediction_model_sha = _validated_sha256(
        prediction_payload.get("model_policy_sha256"),
        "PREDICTION_MODEL_POLICY_SHA256_INVALID",
    )
    if prediction_model_sha != threshold_model_policy_sha:
        raise EventValidationError("PREDICTION_MODEL_POLICY_HASH_MISMATCH")
    raw_prediction_cases = prediction_payload.get("cases")
    if not isinstance(raw_prediction_cases, list):
        raise EventValidationError("PREDICTIONS_CASES_MUST_BE_ARRAY")
    test_cases = {case["case_id"]: case for case in registry["cases"]}
    if not test_cases:
        raise EventValidationError("NO_HELDOUT_TEST_CASES")
    if not any(case["event_label"] for case in test_cases.values()):
        raise EventValidationError("HELDOUT_TEST_HAS_NO_POSITIVE_EVENT_CASES")
    if not any(not case["event_label"] for case in test_cases.values()):
        raise EventValidationError("HELDOUT_TEST_HAS_NO_NON_EVENT_CASES")
    predictions: dict[str, dict[str, Any]] = {}
    for i, raw in enumerate(raw_prediction_cases):
        if not isinstance(raw, dict):
            raise EventValidationError(f"PREDICTION_{i}_MUST_BE_OBJECT")
        case_id = _required_text(raw.get("case_id"), f"PREDICTION_{i}_CASE_ID_REQUIRED")
        if case_id not in test_cases:
            raise EventValidationError(f"PREDICTION_NOT_HELDOUT_TEST_CASE:{case_id}")
        if case_id in predictions:
            raise EventValidationError(f"PREDICTION_CASE_DUPLICATE:{case_id}")
        source_hashes = _source_product_hashes(raw.get("source_product_sha256s"), "PREDICTION")
        expected_hashes = [product["sha256"] for product in test_cases[case_id]["source_products"]]
        if sorted(source_hashes) != sorted(expected_hashes):
            raise EventValidationError(f"PREDICTION_SOURCE_PRODUCT_HASH_MISMATCH:{case_id}")
        state = raw.get("state")
        if state not in PREDICTION_STATES:
            raise EventValidationError(f"PREDICTION_STATE_UNSUPPORTED:{case_id}")
        score_value = raw.get("score")
        if state == "NO_RESULT":
            if score_value is not None:
                raise EventValidationError(f"NO_RESULT_MUST_NOT_HAVE_SCORE:{case_id}")
        else:
            if isinstance(score_value, bool) or not isinstance(score_value, (int, float)) or not math.isfinite(float(score_value)):
                raise EventValidationError(f"PREDICTION_SCORE_INVALID:{case_id}")
            should_alert = float(score_value) >= float(threshold) if rule == ">=" else float(score_value) > float(threshold)
            if (state == "ALERT") != should_alert:
                raise EventValidationError(f"PREDICTION_THRESHOLD_RULE_MISMATCH:{case_id}")
            if not test_cases[case_id]["source_products"]:
                raise EventValidationError(f"PREDICTION_WITHOUT_VERIFIED_SOURCE_PRODUCTS:{case_id}")
        first_alarm = raw.get("first_alarm_time_utc")
        first_alarm_utc = _utc_datetime(first_alarm, f"{case_id}_FIRST_ALARM_TIME_INVALID") if first_alarm is not None else None
        if first_alarm_utc is not None:
            if state != "ALERT":
                raise EventValidationError(f"FIRST_ALARM_TIME_REQUIRES_ALERT_STATE:{case_id}")
            observed_start = _utc_datetime(
                test_cases[case_id]["observation_window_utc"]["start"],
                f"{case_id}_OBSERVATION_START_INVALID",
            )
            observed_end = _utc_datetime(
                test_cases[case_id]["observation_window_utc"]["end"],
                f"{case_id}_OBSERVATION_END_INVALID",
            )
            if not observed_start <= first_alarm_utc <= observed_end:
                raise EventValidationError(f"FIRST_ALARM_TIME_OUTSIDE_OBSERVATION_WINDOW:{case_id}")
        predictions[case_id] = {
            "case_id": case_id, "state": state,
            "score": float(score_value) if score_value is not None else None,
            "source_product_sha256s": source_hashes,
            "first_alarm_time_utc": first_alarm_utc.isoformat().replace("+00:00", "Z") if first_alarm_utc else None,
        }
    if set(predictions) != set(test_cases):
        missing = sorted(set(test_cases) - set(predictions))
        raise EventValidationError("HELDOUT_TEST_PREDICTIONS_INCOMPLETE:" + ",".join(missing))

    rows = [
        {
            **case,
            **predictions[case_id],
        }
        for case_id, case in test_cases.items()
    ]
    available = [row for row in rows if row["state"] != "NO_RESULT"]
    conditional = _confusion_metrics(available)
    positive_rows = [row for row in rows if row["event_label"]]
    tp_all = sum(row["event_label"] and row["state"] == "ALERT" for row in rows)
    conservative_recall = _safe_ratio(tp_all, len(positive_rows))
    exposure_months = sum(
        row["monitoring_exposure_aoi_months"]
        for row in rows if not row["event_label"] and row["state"] != "NO_RESULT"
    )
    false_positives = conditional["fp"]
    false_alarms_per_month = _safe_ratio(false_positives, exposure_months)

    lead_times_hours: list[float] = []
    detection_delays_hours: list[float] = []
    for row in positive_rows:
        event_time = row["event_time_utc"]
        first_alarm = row["first_alarm_time_utc"]
        if row["state"] != "ALERT" or first_alarm is None or event_time is None:
            continue
        event_dt = _utc_datetime(event_time, "EVENT_TIME_INVALID")
        alarm_dt = _utc_datetime(first_alarm, "FIRST_ALARM_TIME_INVALID")
        hours = (event_dt - alarm_dt).total_seconds() / 3600.0
        if hours > 0:
            lead_times_hours.append(hours)
        else:
            detection_delays_hours.append(-hours)

    positive_event_alerts = [row for row in positive_rows if row["state"] == "ALERT"]
    positive_alerts_with_time = [row for row in positive_event_alerts if row["first_alarm_time_utc"] is not None]
    positive_alerts_without_time = len(positive_event_alerts) - len(positive_alerts_with_time)
    timing_coverage = {
        "status": "COMPLETE_FOR_POSITIVE_EVENT_ALERTS" if positive_alerts_without_time == 0 else "PARTIAL_MISSING_ALARM_TIMESTAMPS",
        "positive_event_cases": len(positive_rows),
        "positive_event_alert_cases": len(positive_event_alerts),
        "positive_event_alerts_with_first_alarm_time": len(positive_alerts_with_time),
        "positive_event_alerts_without_first_alarm_time": positive_alerts_without_time,
        "lead_time_values_reported": len(lead_times_hours),
        "post_event_detection_delay_values_reported": len(detection_delays_hours),
        "policy": "Missing first-alarm times are reported as unavailable; they are not imputed and do not erase the ALERT state from event-level recall.",
    }

    ci = _cluster_bootstrap_intervals(
        available,
        replicates=bootstrap_replicates,
        seed=bootstrap_seed,
        minimum_sites=minimum_independent_sites_for_ci,
        minimum_positive_sites=minimum_independent_positive_sites_for_ci,
        minimum_non_event_sites=minimum_independent_non_event_sites_for_ci,
    )
    return {
        "schema_version": "know-place-event-evaluation/1.0",
        "status": "EVALUATED_EXPLORATORY_HELDOUT_TEST",
        "test_registry_sha256": registry["registry_sha256"],
        "validation_registry_sha256": validation_registry["registry_sha256"],
        "threshold_policy_sha256": policy_sha,
        "model_policy_sha256": threshold_model_policy_sha,
        "prediction_payload_sha256": _canonical_sha256(prediction_payload),
        "prediction_source_provenance_status": "PASS_ALL_CASE_SOURCE_HASHES_MATCH_REGISTRY",
        "threshold_selection_split": "validation",
        "test_only": True,
        "total_heldout_cases": len(rows),
        "independent_heldout_sites": len({row["site_id"] for row in rows}),
        "validation_site_independence": {
            "status": "PASS_DISJOINT_SITE_AND_GEOMETRY_SPLITS",
            "validation_site_count": len(validation_site_ids),
            "test_site_count": len(test_site_ids),
            "overlapping_site_ids": [],
            "validation_unique_aoi_geometry_count": len(validation_geometry_ids),
            "test_unique_aoi_geometry_count": len(test_geometry_ids),
            "overlapping_aoi_geometry_hashes": [],
            "policy": "No site_id or exact canonical WGS84 AOI ring may occur in both validation and held-out test registries. Repeated observations from one site remain in one split; exact polygon reuse with a renamed site is still leakage.",
        },
        "availability": {
            "evaluable_cases": len(available),
            "no_result_cases": len(rows) - len(available),
            "coverage_fraction": _safe_ratio(len(available), len(rows)),
            "no_result_policy": "not counted as a negative observation; all labelled events without an alert reduce conservative_recall_all_events",
        },
        "event_level_metrics_on_evaluable_cases": conditional,
        "conservative_recall_all_labelled_events": conservative_recall,
        "false_alarms_per_aoi_month": false_alarms_per_month,
        "evaluable_non_event_exposure_aoi_months": exposure_months,
        "alarm_time_coverage": timing_coverage,
        "lead_time_hours_before_event": {
            "count": len(lead_times_hours),
            "median": float(np.median(lead_times_hours)) if lead_times_hours else None,
            "values": lead_times_hours,
        },
        "detection_delay_hours_after_event": {
            "count": len(detection_delays_hours),
            "median": float(np.median(detection_delays_hours)) if detection_delays_hours else None,
            "values": detection_delays_hours,
        },
        "uncertainty": ci,
        "limitations": [
            "The evaluator scores supplied predictions; it does not build or calibrate a hazard detector.",
            "Point metrics are event/site-level. Pixels are never treated as independent events.",
            "Site-cluster confidence intervals are withheld if too few independent sites exist.",
            "NO_RESULT remains a coverage failure, not evidence of no movement or no hazard.",
            "A low false-alarm count is not informative without the recorded monitored AOI-month exposure.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """Evaluate a prepared case registry and precomputed held-out predictions."""
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Score a frozen, held-out event/non-event prediction set; does not build a detector."
    )
    parser.add_argument("--registry", required=True, type=Path, help="Held-out test-only registry JSON; do not include development/validation labels")
    parser.add_argument("--validation-registry", required=True, type=Path, help="Validation-only registry JSON used to select the frozen threshold")
    parser.add_argument("--predictions", required=True, type=Path, help="Per-case ALERT/NO_ALERT/NO_RESULT JSON")
    parser.add_argument("--threshold-policy", required=True, type=Path, help="Content-addressed threshold policy frozen on validation split")
    parser.add_argument("--out", required=True, type=Path, help="Evaluation JSON output")
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=260826)
    parser.add_argument("--minimum-independent-sites-for-ci", type=int, default=5)
    parser.add_argument("--minimum-independent-positive-sites-for-ci", type=int, default=5)
    parser.add_argument("--minimum-independent-non-event-sites-for-ci", type=int, default=5)
    args = parser.parse_args(argv)

    try:
        registry_payload = json.loads(args.registry.read_text(encoding="utf-8"))
        validation_registry_payload = json.loads(args.validation_registry.read_text(encoding="utf-8"))
        prediction_payload = json.loads(args.predictions.read_text(encoding="utf-8"))
        threshold_policy = json.loads(args.threshold_policy.read_text(encoding="utf-8"))
        result = evaluate_heldout_events(
            registry_payload,
            prediction_payload,
            threshold_policy,
            validation_registry_payload=validation_registry_payload,
            bootstrap_replicates=args.bootstrap_replicates,
            bootstrap_seed=args.bootstrap_seed,
            minimum_independent_sites_for_ci=args.minimum_independent_sites_for_ci,
            minimum_independent_positive_sites_for_ci=args.minimum_independent_positive_sites_for_ci,
            minimum_independent_non_event_sites_for_ci=args.minimum_independent_non_event_sites_for_ci,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError) as exc:
        print("EVENT_VALIDATION_STATUS=FAIL")
        print(f"ERROR={type(exc).__name__}:INPUT_OR_OUTPUT_IO_FAILED")
        return 2
    except EventValidationError as exc:
        code = str(exc).split(":", 1)[0]
        print("EVENT_VALIDATION_STATUS=FAIL")
        print(f"ERROR={code}")
        return 2

    print(f"EVENT_VALIDATION_STATUS={result['status']}")
    print(f"TEST_REGISTRY_SHA256={result['test_registry_sha256']}")
    print(f"VALIDATION_REGISTRY_SHA256={result['validation_registry_sha256']}")
    print(f"THRESHOLD_POLICY_SHA256={result['threshold_policy_sha256']}")
    print(f"HELDOUT_CASES={result['total_heldout_cases']}")
    print(f"NO_RESULT_CASES={result['availability']['no_result_cases']}")
    print(f"OUTPUT={args.out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
