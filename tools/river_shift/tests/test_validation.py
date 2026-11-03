import numpy as np
import json
import pytest

from river_shift.validation import validate_binary_classification


def test_validation_metrics_are_calculated_from_confusion_matrix(raster_writer):
    prediction = np.array([[1, 0], [1, 0]], dtype=np.uint8)
    reference = np.array([[1, 0], [0, 1]], dtype=np.uint8)
    pred_path = raster_writer("prediction.tif", prediction)
    ref_path = raster_writer("reference.tif", reference)
    result = validate_binary_classification(
        str(pred_path), str(ref_path), reference_source="independent test mask",
        reference_date="2026-07-01", reference_method="manually reviewed synthetic fixture",
    )
    assert result["confusion_matrix"] == {
        "true_positive": 1, "true_negative": 1, "false_positive": 1, "false_negative": 1
    }
    assert result["metrics"]["accuracy"] == 0.5
    assert result["metrics"]["f1_score"] == 0.5
    assert round(result["metrics"]["intersection_over_union"], 6) == round(1 / 3, 6)
    assert result["quality"]["release_status"] == "PROVISIONAL"
    assert result["quality"]["provenance_complete"] is False
    assert result["uncertainty"]["spatial_block_bootstrap"]["status"] == "NOT_ESTIMATED_TOO_FEW_SPATIAL_BLOCKS"


def test_spatial_block_bootstrap_is_deterministic_and_reports_intervals(raster_writer):
    prediction = np.indices((10, 10)).sum(axis=0).astype(np.uint8) % 2
    reference = prediction.copy()
    reference[::3, ::3] = 1 - reference[::3, ::3]
    pred_path = raster_writer("prediction-10.tif", prediction)
    ref_path = raster_writer("reference-10.tif", reference)
    kwargs = dict(
        reference_source="independent test mask", reference_date="2026-07-01",
        reference_method="manually reviewed synthetic fixture", block_size_pixels=2,
        bootstrap_replicates=100, random_seed=7,
    )
    first = validate_binary_classification(str(pred_path), str(ref_path), **kwargs)
    second = validate_binary_classification(str(pred_path), str(ref_path), **kwargs)
    first_uncertainty = first["uncertainty"]["spatial_block_bootstrap"]
    second_uncertainty = second["uncertainty"]["spatial_block_bootstrap"]
    assert first_uncertainty["status"] == "ESTIMATED_SPATIAL_BLOCK_BOOTSTRAP"
    assert first_uncertainty["block_count"] == 25
    assert first_uncertainty["intervals"] == second_uncertainty["intervals"]


def test_validation_requires_reference_provenance(raster_writer):
    values = np.array([[1, 0], [0, 1]], dtype=np.uint8)
    path = raster_writer("mask.tif", values)
    import pytest
    with pytest.raises(ValueError, match="reference_source"):
        validate_binary_classification(
            str(path), str(path), reference_source="", reference_date="2026-07-01",
            reference_method="manual",
        )


@pytest.mark.parametrize("analysis_type", ["flood_inundation_screening", "river_morphology_screening"])
def test_validation_records_parent_gcov_report_provenance(raster_writer, analysis_type):
    from river_shift.raster_io import sha256_file

    prediction = np.array([[1, 0], [0, 1]], dtype=np.uint8)
    pred_path = raster_writer("flood/during_water_mask.tif", prediction)
    ref_path = raster_writer("reference.tif", prediction)
    result_path = pred_path.parent / "river_shift_result.json"
    result = {
        "analysis_type": analysis_type,
        "source": {
            "mission": "NISAR", "product": "GCOV", "maturity": "PROVISIONAL",
            "frequency": "A", "covariance_term": "HHHH",
            "granule_names": ["NISAR_L2_PR_GCOV_001"],
            "source_granule_sha256": ["a" * 64],
        },
        "quality": {"provenance_complete": True},
        "outputs": {
            "during_water_mask": pred_path.name,
            "during_water_mask_sha256": sha256_file(pred_path),
        },
    }
    result_path.write_text(json.dumps(result), encoding="utf-8")
    report = validate_binary_classification(
        str(pred_path), str(ref_path), reference_source="independent fixture",
        reference_date="2026-07-01", reference_method="synthetic test fixture",
    )
    assert report["quality"]["provenance_complete"] is True
    assert report["source"]["prediction_analysis"]["source_granule_sha256"] == ["a" * 64]


def test_validation_rejects_mismatched_parent_output_digest(raster_writer):
    from river_shift.raster_io import sha256_file

    prediction = np.array([[1, 0], [0, 1]], dtype=np.uint8)
    pred_path = raster_writer("flood/during_water_mask.tif", prediction)
    ref_path = raster_writer("reference.tif", prediction)
    result = {
        "analysis_type": "flood_inundation_screening",
        "source": {
            "mission": "NISAR", "product": "GCOV", "maturity": "PROVISIONAL",
            "frequency": "A", "covariance_term": "HHHH",
            "granule_names": ["NISAR_L2_PR_GCOV_001"],
            "source_granule_sha256": ["a" * 64],
        },
        "quality": {"provenance_complete": True},
        "outputs": {"during_water_mask": pred_path.name, "during_water_mask_sha256": "b" * 64},
    }
    (pred_path.parent / "river_shift_result.json").write_text(json.dumps(result), encoding="utf-8")
    report = validate_binary_classification(
        str(pred_path), str(ref_path), reference_source="independent fixture",
        reference_date="2026-07-01", reference_method="synthetic test fixture",
    )
    assert sha256_file(pred_path) != "b" * 64
    assert report["quality"]["provenance_complete"] is False
