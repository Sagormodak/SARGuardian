from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import h5py
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "sarguardian_hdf5_archive.py"
MAIN_ZIP = ROOT / "SARGuardian-main-source.zip"
spec = importlib.util.spec_from_file_location("sarguardian_hdf5_archive", TOOL)
archive_tool = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(archive_tool)


def _build_synthetic_products(root: Path):
    shape = (110, 110)
    rng = np.random.default_rng(90731)
    phase = rng.normal(0, 0.7, size=shape).astype("float32")
    coherence = np.full(shape, 0.87, dtype="float32")
    components = np.ones(shape, dtype="uint8")
    mask = np.full(shape, 11, dtype="uint8")  # dry land, valid subswath in both acquisitions
    ionosphere = rng.normal(0, 0.001, size=shape).astype("float32")

    gunw = root / "NISAR_L2_PR_GUNW_001_098_A_016_001_4000_SH_20251128T000000_20251128T000010_20251210T000000_20251210T000010_X05010_N_F_J_001.h5"
    with h5py.File(gunw, "w") as f:
        f.attrs["archiveTest"] = "synthetic-science-compatibility"
        group = f.require_group("science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram")
        hh = group.require_group("HH")
        for name, value in [("unwrappedPhase", phase), ("coherenceMagnitude", coherence),
                            ("connectedComponents", components), ("mask", mask),
                            ("ionospherePhaseScreen", ionosphere)]:
            hh.create_dataset(name, data=value)
        group.create_dataset("xCoordinates", data=np.linspace(85.40, 85.60, shape[1]))
        group.create_dataset("yCoordinates", data=np.linspace(28.20, 28.40, shape[0]))
        projection = group.create_dataset("projection", data=np.array(4326, dtype="int32"))
        projection.attrs["epsg_code"] = 4326
        f.require_group("science/LSAR/GUNW/metadata/processingInformation").create_dataset(
            "centerFrequency", data=np.array(1.2575e9, dtype="float64"))
        radar = f.require_group("science/LSAR/GUNW/metadata/radarGrid")
        radar.create_dataset("xCoordinates", data=np.linspace(85.40, 85.60, shape[1]))
        radar.create_dataset("yCoordinates", data=np.linspace(28.20, 28.40, shape[0]))
        radar.create_dataset("projection", data=np.array(4326, dtype="int32"))
        for name in ("losUnitVectorX", "losUnitVectorY", "incidenceAngle"):
            radar.create_dataset(name, data=np.ones((1, *shape), dtype="float32"))
        f.require_group("science/LSAR/identification").create_dataset("lookDirection", data=np.bytes_("Left"))
        # Large, deliberately excluded grid to prove inventory sidecar records it.
        f.require_group("science/LSAR/GUNW/grids/frequencyA/wrappedInterferogram/HH").create_dataset(
            "wrappedInterferogram", data=np.ones((80, 84), dtype="complex64"))

    goff = root / "NISAR_L2_PR_GOFF_001_098_A_016_001_4000_SH_20251128T000000_20251128T000010_20251210T000000_20251210T000010_X05010_N_F_J_001.h5"
    with h5py.File(goff, "w") as f:
        po = f.require_group("science/LSAR/GOFF/grids/frequencyA/pixelOffsets")
        for pol in ("HH", "VV"):
            for layer in ("layer1", "layer2", "layer3"):
                g = po.require_group(f"{pol}/{layer}")
                offset = phase.astype("float64") / (100 if pol == "HH" else 90)
                for name, value in [
                    ("slantRangeOffset", offset),
                    ("alongTrackOffset", offset / 2),
                    ("correlationSurfacePeak", np.full(shape, .85)),
                    ("snr", np.full(shape, 5.0)),
                    ("slantRangeOffsetVariance", np.full(shape, .01)),
                    ("alongTrackOffsetVariance", np.full(shape, .02)),
                ]:
                    g.create_dataset(name, data=value)
                g.create_dataset("xCoordinates", data=np.linspace(85.40, 85.60, shape[1]))
                g.create_dataset("yCoordinates", data=np.linspace(28.20, 28.40, shape[0]))
                projection = g.create_dataset("projection", data=np.array(4326, dtype="int32"))
                projection.attrs["epsg_code"] = 4326
    return gunw, goff


def test_existing_science_readers_return_identical_arrays_for_curated_hdf5(tmp_path):
    # This optional compatibility test uses the source snapshot distributed in the full audit bundle.
    # Do not commit the source ZIP into the backend repo merely to satisfy this local test.
    if not MAIN_ZIP.is_file():
        pytest.skip("SARGuardian-main-source.zip is not included in the GitHub patch; run this test from the full audit bundle or supply that file temporarily")
    # Import the exact code in the user-supplied main ZIP, rather than reimplementing readers.
    extract = tmp_path / "main_source"
    extract.mkdir()
    with zipfile.ZipFile(MAIN_ZIP) as zf:
        zf.extractall(extract)
    src_dir = extract / "SARGuardian-main" / "src"
    sys.path.insert(0, str(src_dir))
    try:
        import gunw_reader
        import goff_reader
        gunw, goff = _build_synthetic_products(tmp_path)
        gunw_curated = tmp_path / "curated_gunw.h5"
        gunw_manifest = tmp_path / "curated_gunw.json"
        goff_curated = tmp_path / "curated_goff.h5"
        goff_manifest = tmp_path / "curated_goff.json"
        archive_tool.build_archive(gunw, gunw_curated, gunw_manifest, "GUNW")
        archive_tool.build_archive(goff, goff_curated, goff_manifest, "GOFF")

        raw_gunw = gunw_reader.read_gunw(gunw, clip_aoi=True, auto_ref=True)
        assert raw_gunw["valid"].any(), "synthetic GUNW fixture must contain valid pixels"
        curated_gunw = gunw_reader.read_gunw(gunw_curated, clip_aoi=True, auto_ref=True)
        for key in ("displacement_mm", "valid", "coherence", "components", "mask"):
            a, b = raw_gunw.get(key), curated_gunw.get(key)
            if a is not None:
                assert np.array_equal(a, b, equal_nan=True), f"GUNW mismatch in {key}"

        raw_goff = goff_reader.read_goff(goff, layer="best", clip_aoi=True,
                                         auto_ref=True, deramp=True)
        assert raw_goff["layers"]["HH/layer2"]["valid"].any(), "synthetic GOFF fixture must contain valid pixels"
        curated_goff = goff_reader.read_goff(goff_curated, layer="best", clip_aoi=True,
                                             auto_ref=True, deramp=True)
        assert raw_goff["layers"].keys() == curated_goff["layers"].keys()
        for layer_name in raw_goff["layers"]:
            for key in ("range_m", "azimuth_m", "correlation", "snr", "range_var", "valid", "xs", "ys"):
                assert np.array_equal(raw_goff["layers"][layer_name][key],
                                      curated_goff["layers"][layer_name][key], equal_nan=True), \
                    f"GOFF mismatch in {layer_name}/{key}"
    finally:
        sys.path.remove(str(src_dir))
        # Avoid import leakage if another test imports a different source tree.
        for name in ("gunw_reader", "goff_reader", "paths"):
            sys.modules.pop(name, None)
