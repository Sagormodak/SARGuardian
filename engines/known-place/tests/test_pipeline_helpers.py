from __future__ import annotations
import hashlib, importlib.util, json, os, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module)
    return module

download = load('download_nisar_product_testmod', ROOT/'tools/download_nisar_product.py')
drive = load('drive_resumable_upload_testmod', ROOT/'tools/drive_resumable_upload.py')

def test_normal_name_accepts_exact_h5_and_bare_granule():
    name = 'NISAR_L2_PR_GOFF_001_048_D_074_001_2000_SH_20260901T000000_20260901T000001_X00000_N_F_J_001'
    assert download.normal_name(name) == name
    assert download.normal_name(name + '.h5') == name

def test_normal_name_strips_path_and_extension_but_workflow_validates_format():
    # The helper normalizes public granule identifiers; workflow applies a strict allowlist regex before use.
    assert download.normal_name('/tmp/NISAR_L2_PR_GUNW_test.h5') == 'NISAR_L2_PR_GUNW_test'


def test_drive_hashes_stream_to_expected_digests(tmp_path):
    p = tmp_path/'test.bin'; data = b'abc123' * 1000; p.write_bytes(data)
    md5, sha, size = drive.hashes(p)
    assert md5 == hashlib.md5(data).hexdigest()
    assert sha == hashlib.sha256(data).hexdigest()
    assert size == len(data)

def test_reader_compare_value_identifies_numerical_change():
    import numpy as np
    errs, arrays, scalars = load('equiv_testmod', ROOT/'tools/verify_reader_equivalence.py').compare_values(
        {'displacement_mm': np.array([1.0, 2.0])}, {'displacement_mm': np.array([1.0, 2.1])}
    )
    assert arrays == 1 and scalars == 0 and errs

def test_reader_compare_accepts_identical_arrays_and_nans():
    import numpy as np
    eq = load('equiv_testmod2', ROOT/'tools/verify_reader_equivalence.py').compare_values
    errs, arrays, _ = eq({'v': np.array([1.0, np.nan])}, {'v': np.array([1.0, np.nan])})
    assert errs == [] and arrays == 1

def test_drive_cli_refuses_raw_hdf5_before_credentials_or_network(tmp_path, monkeypatch, capsys):
    raw = tmp_path / 'original.h5'; raw.write_bytes(b'raw')
    out = tmp_path / 'receipt.json'
    monkeypatch.setattr(sys, 'argv', ['drive_resumable_upload.py', '--root', str(tmp_path), '--product-type', 'GOFF',
        '--maturity', 'PROVISIONAL', '--granule-name', 'NISAR_L2_PR_GOFF_001_048_D_074_001_4000_SH_20260901T000000_20260901T000001_20260913T000000_20260913T000001_X00000_N_F_J_001',
        '--files', str(raw), '--out', str(out)])
    assert drive.main() == 2
    assert 'REFUSING_TO_UPLOAD_RAW_HDF5' in capsys.readouterr().err
    assert not out.exists()

def test_downloader_accepts_real_asf_pr_granule_id_before_auth(monkeypatch, tmp_path, capsys):
    # ASF NISAR Level-2 filenames commonly include the processing type (PR/OD).
    # The workflow must not reject a valid NISAR_L2_PR_GUNW/GOFF identifier.
    monkeypatch.delenv('EARTHDATA_USERNAME', raising=False)
    monkeypatch.delenv('EARTHDATA_PASSWORD', raising=False)
    monkeypatch.setattr(sys, 'argv', ['download_nisar_product.py', '--product-type', 'GOFF',
        '--maturity', 'PROVISIONAL',
        '--granule-name', 'NISAR_L2_PR_GOFF_001_030_A_019_002_2000_SH_20081012T060912_20081012T060924_20081127T061001_20081127T061013_D00402_M_P_J_001.h5',
        '--science-root', str(tmp_path), '--aoi', 'source', '--out-dir', str(tmp_path)])
    assert download.main() == 2
    assert 'EARTHDATA_CREDENTIALS_MISSING' in capsys.readouterr().err


def test_downloader_refuses_path_or_non_granule_input_before_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['download_nisar_product.py', '--product-type', 'GOFF', '--maturity', 'PROVISIONAL',
        '--granule-name', '../not-a-granule.h5', '--science-root', str(tmp_path), '--aoi', 'source', '--out-dir', str(tmp_path)])
    assert download.main() == 2
    assert 'EXACT_PUBLIC_GRANULE_NAME_REQUIRED' in capsys.readouterr().err


def test_product_grid_preflight_detects_intersection_before_archive_work(tmp_path):
    import h5py
    import numpy as np
    from types import SimpleNamespace

    tool = load("aoi_preflight_testmod", ROOT / "tools" / "validate_product_aoi.py")
    src = tmp_path / "coordinates.h5"
    group = "science/LSAR/GOFF/grids/frequencyA/pixelOffsets/HH/layer2"
    with h5py.File(src, "w") as f:
        g = f.require_group(group)
        g.create_dataset("xCoordinates", data=np.array([10.0, 20.0, 30.0]))
        g.create_dataset("yCoordinates", data=np.array([40.0, 50.0]))
        p = g.create_dataset("projection", data=np.array(4326, dtype=np.int32))
        p.attrs["epsg_code"] = 4326
    datasets = {
        f"{group}/xCoordinates": ((3,), np.dtype("float64")),
        f"{group}/yCoordinates": ((2,), np.dtype("float64")),
        f"{group}/projection": ((), np.dtype("int32")),
    }
    mask = np.array([[False, True, False], [False, True, False]], dtype=bool)
    engine = SimpleNamespace(
        AOI_RING=[],
        build_aoi_mask=lambda xs, ys, ring, epsg: mask,
    )
    with h5py.File(src, "r") as f:
        good = tool._grid(f, datasets, engine, group, None, "GOFF_pixelOffsets")
    assert good["intersects_aoi"] is True
    assert good["grid_pixels_inside_aoi"] == 2
    assert good["shape"] == [2, 3]

    engine.build_aoi_mask = lambda xs, ys, ring, epsg: np.zeros((2, 3), dtype=bool)
    with h5py.File(src, "r") as f:
        bad = tool._grid(f, datasets, engine, group, None, "GOFF_pixelOffsets")
    assert bad["intersects_aoi"] is False
    assert bad["grid_pixels_inside_aoi"] == 0


def test_drive_granule_folder_versions_keep_prior_assets_and_validate_tag():
    full_name = (
        "NISAR_L2_PR_GUNW_026_048_D_074_028_4000_SH_"
        "20260723T125813_20260723T125848_20260816T125812_20260816T125846_P05023_N_F_J_001.h5"
    )
    names = drive.granule_folder_names("GUNW", "PROVISIONAL", full_name, "39410309860-1")
    assert names == [
        "SARGuardian-DataArchive",
        "GUNW",
        "PROVISIONAL",
        full_name[:-3],
        "Runs",
        "39410309860-1",
    ]
    assert drive.granule_folder_names("GUNW", "PROVISIONAL", full_name) == names[:4]
    with pytest.raises(drive.DriveError, match="VERSION_TAG_INVALID"):
        drive.granule_folder_names("GUNW", "PROVISIONAL", full_name, "../overwrite")
