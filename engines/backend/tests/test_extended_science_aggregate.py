import inspect

from tools.aggregate_streamed_outputs import run_common_reference_target_series


def test_common_reference_series_can_target_a_fresh_candidate_without_changing_defaults():
    signature = inspect.signature(run_common_reference_target_series)
    assert signature.parameters["target_lat"].default == 28.27799
    assert signature.parameters["target_lon"].default == 85.52983
    assert signature.parameters["target_label"].default == "Candidate-4"
