"""CLI: select and checksum a score threshold using validation cases only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .event_validation import EventValidationError, select_validation_threshold


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select a frozen event score threshold on validation cases; test labels are rejected."
    )
    parser.add_argument("--registry", required=True, type=Path, help="Validation-only registry JSON; development/test cases are rejected")
    parser.add_argument("--validation-scores", required=True, type=Path)
    parser.add_argument("--model-policy-name", required=True)
    parser.add_argument(
        "--model-policy-manifest", required=True, type=Path,
        help="JSON manifest defining algorithm, features, parameters, implementation revision and score units; exact file bytes are SHA-256-addressed",
    )
    parser.add_argument("--score-name", required=True)
    parser.add_argument("--objective", choices=["max_youden_j", "max_f1", "max_recall_at_min_specificity"], default="max_youden_j")
    parser.add_argument("--decision-rule", choices=[">=", ">"], default=">=")
    parser.add_argument("--minimum-specificity", type=float, default=None)
    parser.add_argument("--out", required=True, type=Path, help="Full threshold-selection report JSON")
    parser.add_argument("--threshold-policy-out", required=True, type=Path, help="Frozen, checksum-addressed threshold policy JSON")
    args = parser.parse_args(argv)

    try:
        registry = json.loads(args.registry.read_text(encoding="utf-8"))
        scores = json.loads(args.validation_scores.read_text(encoding="utf-8"))
        manifest_bytes = args.model_policy_manifest.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise EventValidationError("MODEL_POLICY_MANIFEST_MUST_BE_JSON_OBJECT")
        manifest_schema = manifest.get("schema_version")
        if manifest_schema != "know-place-detector-policy/1.0":
            raise EventValidationError("MODEL_POLICY_MANIFEST_SCHEMA_UNSUPPORTED")
        if manifest.get("model_policy_name") != args.model_policy_name:
            raise EventValidationError("MODEL_POLICY_MANIFEST_NAME_MISMATCH")
        if manifest.get("score_name") != args.score_name:
            raise EventValidationError("MODEL_POLICY_MANIFEST_SCORE_NAME_MISMATCH")
        if not isinstance(manifest.get("score_units"), str) or not manifest["score_units"].strip():
            raise EventValidationError("MODEL_POLICY_MANIFEST_SCORE_UNITS_REQUIRED")
        if not isinstance(manifest.get("algorithm"), str) or not manifest["algorithm"].strip():
            raise EventValidationError("MODEL_POLICY_MANIFEST_ALGORITHM_REQUIRED")
        if not isinstance(manifest.get("implementation_revision"), str) or not manifest["implementation_revision"].strip():
            raise EventValidationError("MODEL_POLICY_MANIFEST_IMPLEMENTATION_REVISION_REQUIRED")
        if not isinstance(manifest.get("parameters"), dict):
            raise EventValidationError("MODEL_POLICY_MANIFEST_PARAMETERS_REQUIRED")
        if not isinstance(manifest.get("feature_manifest_sha256"), str) or len(manifest["feature_manifest_sha256"]) != 64 or any(
            character not in "0123456789abcdef" for character in manifest["feature_manifest_sha256"].lower()
        ):
            raise EventValidationError("MODEL_POLICY_MANIFEST_FEATURE_HASH_INVALID")
        model_policy_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        result = select_validation_threshold(
            registry,
            scores,
            model_policy_name=args.model_policy_name,
            model_policy_sha256=model_policy_sha256,
            score_name=args.score_name,
            objective=args.objective,
            decision_rule=args.decision_rule,
            minimum_specificity=args.minimum_specificity,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.threshold_policy_out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        args.threshold_policy_out.write_text(
            json.dumps(result["threshold_policy"], indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError) as exc:
        print("THRESHOLD_SELECTION_STATUS=FAIL")
        print(f"ERROR={type(exc).__name__}:INPUT_OR_OUTPUT_IO_FAILED")
        return 2
    except EventValidationError as exc:
        print("THRESHOLD_SELECTION_STATUS=FAIL")
        print(f"ERROR={str(exc).split(':', 1)[0]}")
        return 2

    print(f"THRESHOLD_SELECTION_STATUS={result['status']}")
    print(f"VALIDATION_REGISTRY_SHA256={result['validation_registry_sha256']}")
    print(f"VALIDATION_SCORES_SHA256={result['validation_scores_sha256']}")
    print(f"MODEL_POLICY_SHA256={result['threshold_policy']['model_policy_sha256']}")
    print(f"THRESHOLD={result['threshold_policy']['threshold']:.17g}")
    print(f"POLICY_SHA256={result['threshold_policy']['policy_sha256']}")
    print(f"THRESHOLD_POLICY={args.threshold_policy_out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
