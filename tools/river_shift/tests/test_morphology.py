import numpy as np

from affine import Affine

from river_shift.morphology import _orthogonal_pixel_sizes, run_morphology_analysis, symmetric_boundary_distance_m


def test_morphology_finds_persistent_erosion_and_deposition_candidates(tmp_path, raster_writer):
    before = np.full((20, 20), 0.3, dtype=np.float32)
    before[5:10, 5:15] = 0.01
    post = np.full((20, 20), 0.3, dtype=np.float32)
    post[5:12, 5:11] = 0.01
    paths = [
        raster_writer("before.tif", before),
        raster_writer("post1.tif", post),
        raster_writer("post2.tif", post.copy()),
    ]
    result = run_morphology_analysis(
        before_path=str(paths[0]), post_one_path=str(paths[1]), post_two_path=str(paths[2]),
        output_dir=str(tmp_path / "out"), units="linear", threshold_db=-12.0,
        use_otsu=False, maturity="PROVISIONAL", frequency="frequencyA", polarization_term="HHHH",
    )
    metrics = result["metrics"]
    assert metrics["persistent_erosion_candidate_area_ha"] > 0
    assert metrics["persistent_deposition_candidate_area_ha"] > 0
    assert result["quality"]["status"] == "PERSISTENCE_SCREENED_NOT_INDEPENDENTLY_VALIDATED"
    assert result["quality"]["release_status"] == "PROVISIONAL"
    assert len(result["uncertainty"]["classification_threshold_sensitivity"]["scenarios"]) == 5
    assert (tmp_path / "out" / "erosion_candidates.geojson").exists()
    assert (tmp_path / "out" / "deposition_candidates.geojson").exists()


def test_boundary_distance_is_symmetric_and_positive():
    before = np.zeros((20, 20), dtype=bool)
    after = np.zeros((20, 20), dtype=bool)
    before[5:10, 5:10] = True
    after[7:12, 5:10] = True
    mean, p95 = symmetric_boundary_distance_m(
        before, after, pixel_size_y_m=10, pixel_size_x_m=10
    )
    assert mean is not None and mean > 0
    assert p95 is not None and p95 > 0


def test_boundary_distance_ignores_boundaries_adjacent_to_nodata():
    support = np.ones((20, 20), dtype=bool)
    support[:, 9] = False
    before = np.zeros((20, 20), dtype=bool)
    after = np.zeros((20, 20), dtype=bool)
    before[:, 8] = True
    after[:, 10] = True

    mean, p95 = symmetric_boundary_distance_m(
        before,
        after,
        pixel_size_y_m=10,
        pixel_size_x_m=10,
        valid_mask=support,
    )

    assert mean is None
    assert p95 is None


def test_orthogonal_pixel_sizes_use_full_affine_vector_lengths():
    rotated = Affine.rotation(30) * Affine.scale(10, -20)

    row_size, column_size = _orthogonal_pixel_sizes(rotated)

    assert row_size == pytest.approx(20)
    assert column_size == pytest.approx(10)


def test_boundary_distance_rejects_sheared_affine_grid():
    sheared = Affine(10, 2, 0, 0, -20, 0)

    with pytest.raises(ValueError, match="orthogonal projected raster grid"):
        _orthogonal_pixel_sizes(sheared)


