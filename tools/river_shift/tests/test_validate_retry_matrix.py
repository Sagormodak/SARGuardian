from __future__ import annotations

import json

import pytest

from validate_retry_matrix import validate_retry_matrix


def _matrix(attempt: int, names: list[str]):
    return {
        "include": [
            {
                "granule_name": name,
                "acquisition_date": "2026-07-12",
                "batch_number": 4 + attempt,
                "batch_count": 1,
                "product_index": index,
                "total_products": len(names),
                "retry_attempt": attempt,
            }
            for index, name in enumerate(names, start=1)
        ]
    }


@pytest.mark.parametrize("attempt", [1, 2, 3])
def test_matrix_accepts_the_exact_retry_wave(attempt):
    names = [
        "NISAR_L2_PR_GCOV_025_069_A_014_4005_DHDH_A_20260712T232134_20260712T232208_P05023_N_F_J_001"
    ]
    matrix, count = validate_retry_matrix(json.dumps(_matrix(attempt, names)), "1", attempt)
    assert count == 1
    assert matrix["include"][0]["retry_attempt"] == attempt


def test_matrix_accepts_an_empty_queue_for_a_completed_wave():
    matrix, count = validate_retry_matrix('{"include":[]}', "0", 3)
    assert count == 0
    assert matrix == {"include": []}


def test_matrix_rejects_a_row_from_another_retry_wave():
    with pytest.raises(ValueError, match="invalid or duplicate"):
        validate_retry_matrix(json.dumps(_matrix(1, ["NISAR_L2_PR_GCOV_025"])), "1", 2)


def test_matrix_rejects_duplicate_product_identity():
    name = "NISAR_L2_PR_GCOV_025"
    matrix = _matrix(2, [name, name])
    with pytest.raises(ValueError, match="invalid or duplicate"):
        validate_retry_matrix(json.dumps(matrix), "2", 2)


def test_matrix_rejects_count_mismatch():
    with pytest.raises(ValueError, match="matrix_include_count"):
        validate_retry_matrix('{"include":[]}', "1", 1)


def test_matrix_rejects_non_contiguous_product_indexes():
    matrix = _matrix(3, ["NISAR_L2_PR_GCOV_025"])
    matrix["include"][0]["product_index"] = 2
    with pytest.raises(ValueError, match="not contiguous"):
        validate_retry_matrix(json.dumps(matrix), "1", 3)
