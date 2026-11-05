"""Audit crown-mask consistency on retained derived arrays without raw HDF5 replay."""
from __future__ import annotations
import argparse, hashlib, io, json, math, re, zipfile
from pathlib import Path
from typing import Any, Sequence
import numpy as np
from pyproj import Transformer

AUTHOR_ARCHIVE_SHA256 = "002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3"
CROWN = (85.5245, 28.2847, 85.5400, 28.2970)
BOX = (85.500, 28.265, 85.565, 28.318)
EPSG, WIDTH, HEIGHT = 32645, 4311, 4230
X0, Y0, DX, DY = 126720.0, 3347280.0, 80.0, -80.0
EXPECTED_CROWN_CELLS = 323
PAIRS = (
 ("2026-06-20/2026-07-02","20260620__20260702",283,302),
 ("2026-07-02/2026-07-14","20260702__20260714",294,299),
 ("2026-07-14/2026-07-26","20260714__20260726",296,302),
 ("2026-07-26/2026-08-19","20260726__20260819",292,298),
 ("2026-08-19/2026-08-31","20260819__20260831",195,202),
)

AUTHOR_SOURCE_COLLECTION_ID = "C2854341702-ASF"
AUTHOR_SOURCE_COLLECTION_NAME = "NISAR_L2_GOFF_PROVISIONAL_V1"
AUTHOR_SOURCE_MATURITY = "PROVISIONAL"
AUTHOR_SOURCE_EPSG = 32645
AUTHOR_SOURCE_WIDTH = 4311
AUTHOR_SOURCE_HEIGHT = 4230
AUTHOR_SOURCE_GRID = {
    "grid_epsg": AUTHOR_SOURCE_EPSG,
    "grid_width": AUTHOR_SOURCE_WIDTH,
    "grid_height": AUTHOR_SOURCE_HEIGHT,
    "grid_x_min_m": 126760.0,
    "grid_x_max_m": 471560.0,
    "grid_y_min_m": 3008920.0,
    "grid_y_max_m": 3347240.0,
    "grid_x_posting_m": 80.0,
    "grid_y_posting_m": -80.0,
    "polarization": "HH",
    "layer": "layer2",
}
# Frozen identity and byte-integrity ledger for the five exact author-published
# products. The hashes are retained evidence, not a claim that deleted raw bytes
# were re-read by this audit.
AUTHOR_EXPECTED_PRODUCTS = (
    {
        "interval": "2026-06-20/2026-07-02",
        "cmr_id": "G4248299988-ASF",
        "filename": "NISAR_L2_PR_GOFF_023_098_A_016_024_4000_SH_20260620T233921_20260620T233956_20260702T233920_20260702T233955_P05023_N_F_J_001.h5",
        "bytes": 1090519040,
        "sha256": "d3670f0504576feac52f75a7e8f0ff12f5f5c2ef676a0329a16f66cb91300f05",
    },
    {
        "interval": "2026-07-02/2026-07-14",
        "cmr_id": "G4261120661-ASF",
        "filename": "NISAR_L2_PR_GOFF_024_098_A_016_025_4000_SH_20260702T233920_20260702T233955_20260714T233920_20260714T233954_P05023_F_F_J_001.h5",
        "bytes": 1090519040,
        "sha256": "8a947f7fa4458afb564431514f36950a89e004d79e6f0e6bfb7461f7e867123c",
    },
    {
        "interval": "2026-07-14/2026-07-26",
        "cmr_id": "G4264302811-ASF",
        "filename": "NISAR_L2_PR_GOFF_025_098_A_016_026_4000_SH_20260714T233920_20260714T233954_20260726T233919_20260726T233954_P05023_N_F_J_001.h5",
        "bytes": 1092616192,
        "sha256": "ac3eb50eb5c35cb70769b44492398d6b212e880b70558d4d7d2376c5d8e49313",
    },
    {
        "interval": "2026-07-26/2026-08-19",
        "cmr_id": "G4286855543-ASF",
        "filename": "NISAR_L2_PR_GOFF_026_098_A_016_028_4000_SH_20260726T233919_20260726T233954_20260819T233918_20260819T233953_P05023_N_F_J_001.h5",
        "bytes": 1101004800,
        "sha256": "45e4641da04f235941b1e88262961e9e62ca05ce3ceb35fdac452649b13e416f",
    },
    {
        "interval": "2026-08-19/2026-08-31",
        "cmr_id": "G4296814366-ASF",
        "filename": "NISAR_L2_PR_GOFF_028_098_A_016_029_4000_SH_20260819T233918_20260819T233953_20260831T233918_20260831T233952_P05023_N_F_J_001.h5",
        "bytes": 1098907648,
        "sha256": "4dbe3d82c2e03422abf9fc3ead2ad70c0734a80ec52cad87cd6659716fce5371",
    },
)

class CrownMaskAuditError(ValueError):
    """Raised when an archive cannot support an unambiguous audit."""

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _json(z: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try: value = json.loads(z.read(name).decode("utf-8"))
    except KeyError as exc: raise CrownMaskAuditError(f"MEMBER_MISSING:{name}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise CrownMaskAuditError(f"JSON_INVALID:{name}") from exc
    if not isinstance(value, dict): raise CrownMaskAuditError(f"JSON_NOT_OBJECT:{name}")
    return value

def _mask(v: Any, shape: tuple[int,int], label: str) -> np.ndarray:
    a = np.asarray(v)
    if a.ndim != 2 or a.shape != shape: raise CrownMaskAuditError(f"{label}_SHAPE_MISMATCH")
    if a.dtype.kind not in "biuf" or not np.isfinite(a).all() or not np.isin(a,(0,1)).all():
        raise CrownMaskAuditError(f"{label}_NOT_FINITE_BINARY")
    return a.astype(bool, copy=False)

def geographic_mask(x: Any, y: Any, epsg: int | None = None, bounds: Sequence[float] | None = None) -> np.ndarray:
    """Independent mask from inverse-projected native-grid cell centres."""
    x,y=np.asarray(x,dtype=float),np.asarray(y,dtype=float)
    if x.ndim!=1 or y.ndim!=1 or not x.size or not y.size: raise CrownMaskAuditError("AXES_MUST_BE_NONEMPTY_1D")
    if not np.isfinite(x).all() or not np.isfinite(y).all(): raise CrownMaskAuditError("AXES_NONFINITE")
    if x.size>1 and not (np.all(np.diff(x)>0) or np.all(np.diff(x)<0)): raise CrownMaskAuditError("X_AXIS_NOT_STRICTLY_MONOTONIC")
    if y.size>1 and not (np.all(np.diff(y)>0) or np.all(np.diff(y)<0)): raise CrownMaskAuditError("Y_AXIS_NOT_STRICTLY_MONOTONIC")
    if epsg is None:
        epsg = EPSG
    if bounds is None:
        bounds = CROWN
    west,south,east,north=map(float,bounds)
    if not all(map(math.isfinite,(west,south,east,north))) or not (-180<=west<east<=180 and -90<=south<north<=90):
        raise CrownMaskAuditError("CROWN_BOUNDS_INVALID")
    tx=Transformer.from_crs(f"EPSG:{epsg}","EPSG:4326",always_xy=True)
    xx,yy=np.meshgrid(x,y); lon,lat=tx.transform(xx,yy,errcheck=True)
    if not np.isfinite(lon).all() or not np.isfinite(lat).all(): raise CrownMaskAuditError("INVERSE_TRANSFORM_NONFINITE")
    return (lon>=west)&(lon<=east)&(lat>=south)&(lat<=north)

def endpoint_crop(shape: Sequence[int], extent: Sequence[float], bounds: Sequence[float] | None = None) -> np.ndarray:
    """Reproduce the published endpoint-linear extent and searchsorted crop."""
    if bounds is None:
        bounds = CROWN
    if len(shape)!=2 or len(extent)!=4 or len(bounds)!=4: raise CrownMaskAuditError("CROP_SHAPE_OR_BOUNDS_INVALID")
    h,w=map(int,shape); left,right,bottom,top=map(float,extent); west,south,east,north=map(float,bounds)
    if h<=0 or w<=0 or not (all(map(math.isfinite,(left,right,bottom,top,west,south,east,north))) and left<west<east<right and bottom<south<north<top):
        raise CrownMaskAuditError("CROWN_OUTSIDE_OR_INVALID_EXTENT")
    lon=np.linspace(left,right,w); lat=np.linspace(top,bottom,h)
    r0,r1=int(np.searchsorted(-lat,-north)),int(np.searchsorted(-lat,-south))
    c0,c1=int(np.searchsorted(lon,west)),int(np.searchsorted(lon,east))
    if r0>=r1 or c0>=c1: raise CrownMaskAuditError("CROP_EMPTY")
    out=np.zeros((h,w),dtype=bool); out[r0:r1,c0:c1]=True
    return out

def _mask_hash(a: np.ndarray) -> str:
    a=np.asarray(a,dtype=bool)
    header=json.dumps({"shape":list(a.shape),"dtype":"bool","order":"C"},sort_keys=True).encode()
    return sha256_bytes(header+b"\0"+np.packbits(a.ravel(),bitorder="little").tobytes())

def _window(item: dict[str,Any]) -> tuple[int,int,int,int]:
    g=item.get("source_grid",{})
    if (g.get("epsg")!=EPSG or g.get("original_width")!=WIDTH or g.get("original_height")!=HEIGHT
        or g.get("x_posting_m")!=DX or g.get("y_posting_m")!=DY):
        raise CrownMaskAuditError("PINNED_SOURCE_GRID_MISMATCH")
    w=g.get("window_slices",{})
    try: r0,r1,c0,c1=map(int,(w["row_start"],w["row_stop"],w["column_start"],w["column_stop"]))
    except (KeyError,TypeError,ValueError) as exc: raise CrownMaskAuditError("SOURCE_WINDOW_METADATA_MISSING") from exc
    if not (0<=r0<r1<=HEIGHT and 0<=c0<c1<=WIDTH): raise CrownMaskAuditError("SOURCE_WINDOW_OUTSIDE_GRID")
    if g.get("window_shape") != [r1-r0,c1-c0]: raise CrownMaskAuditError("SOURCE_WINDOW_SHAPE_MISMATCH")
    return r0,r1,c0,c1

def _validate_wkt(v: Any, bounds: Sequence[float], label: str) -> None:
    if not isinstance(v,str): raise CrownMaskAuditError(f"{label}_WKT_MISSING")
    m=re.fullmatch(r"(?is)\s*POLYGON\s*\(\s*\((.*?)\)\s*\)\s*",v.strip())
    if not m: raise CrownMaskAuditError(f"{label}_WKT_INVALID")
    try: pts=tuple(tuple(map(float,p.split())) for p in m.group(1).split(","))
    except (ValueError,TypeError) as exc: raise CrownMaskAuditError(f"{label}_WKT_INVALID") from exc
    w,s,e,n=map(float,bounds); expected=((w,s),(e,s),(e,n),(w,n),(w,s))
    if pts!=expected: raise CrownMaskAuditError(f"{label}_WKT_NOT_EXACT_PUBLISHED_RECTANGLE")


def _validate_source_provenance(
    source: dict[str, Any], source_manifest_bytes: bytes, cleanup: dict[str, Any]
) -> None:
    """Fail closed on source-row identity, bytes, grid, and raw-delete evidence."""
    if (
        source.get("author_release_id") != "P05023"
        or source.get("collection_concept_id") != AUTHOR_SOURCE_COLLECTION_ID
        or source.get("expected_collection_short_name") != AUTHOR_SOURCE_COLLECTION_NAME
        or source.get("expected_maturity") != AUTHOR_SOURCE_MATURITY
        or source.get("expected_intervals") != [p["interval"] for p in AUTHOR_EXPECTED_PRODUCTS]
        or source.get("author_product_count") != 5
        or source.get("exact_cmr_confirmed_count") != 5
        or source.get("blocking_count") != 0
        or source.get("status") != "PASS_FIVE_EXACT_HDF5_DOWNLOADED_HASHED_AND_GRID_VALIDATED"
        or source.get("source_sha256_count") != 5
        or source.get("author_exact_source_sha256_count") != 5
    ):
        raise CrownMaskAuditError("AUTHOR_SOURCE_IDENTITY_MANIFEST_INVALID")

    if (
        cleanup.get("source_manifest_sha256") != sha256_bytes(source_manifest_bytes)
        or cleanup.get("source_manifest_verified") is not True
    ):
        raise CrownMaskAuditError("SOURCE_MANIFEST_RECEIPT_HASH_MISMATCH")

    products = source.get("products")
    if not isinstance(products, list) or len(products) != len(AUTHOR_EXPECTED_PRODUCTS):
        raise CrownMaskAuditError("AUTHOR_SOURCE_IDENTITY_MANIFEST_INVALID")

    seen_hashes: set[str] = set()
    for index, (product, expected) in enumerate(zip(products, AUTHOR_EXPECTED_PRODUCTS, strict=True)):
        interval = expected["interval"]
        start, end = interval.split("/")
        filename = expected["filename"]
        stem = filename[:-3]
        identity = product.get("identity_validation")
        checks = identity.get("checks") if isinstance(identity, dict) else None
        required_checks = {
            "filename": filename,
            "granule_stem": stem,
            "release_id": "P05023",
            "reference_start_date": start,
            "secondary_start_date": end,
            "epsg": AUTHOR_SOURCE_EPSG,
        }
        if (
            product.get("interval") != interval
            or product.get("release_id") != "P05023"
            or product.get("collection_concept_id") != AUTHOR_SOURCE_COLLECTION_ID
            or product.get("cmr_granule_concept_id") != expected["cmr_id"]
            or product.get("granule_name") != stem
            or product.get("source_filename") != filename
            or product.get("download_url_host") != "nisar.asf.earthdatacloud.nasa.gov"
            or product.get("remote_content_length_bytes") != expected["bytes"]
            or product.get("source_bytes") != expected["bytes"]
            or product.get("source_sha256") != expected["sha256"]
            or not isinstance(product.get("source_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", product.get("source_sha256", "")) is None
            or product.get("download_status") != "PASS"
            or product.get("hdf5_container_valid") is not True
            or product.get("byte_count_validation") != "PASS"
            or product.get("content_validation_status") != "PASS"
            or product.get("grid_validation_status") != "PASS"
            or product.get("polarization") != "HH"
            or product.get("layer") != "layer2"
            or not isinstance(identity, dict)
            or identity.get("status") != "PASS"
            or identity.get("expected_granule_name_without_extension") != stem
            or identity.get("expected_source_filename_with_extension") != filename
            or identity.get("actual_identity_filename") != filename
            or identity.get("mismatch_fields") != []
            or not isinstance(checks, dict)
            or any(
                not isinstance(checks.get(name), dict)
                or checks[name].get("passed") is not True
                or checks[name].get("expected") != value
                or checks[name].get("actual") != value
                for name, value in required_checks.items()
            )
            or any(product.get(key) != value for key, value in AUTHOR_SOURCE_GRID.items())
        ):
            raise CrownMaskAuditError(f"AUTHOR_SOURCE_ROW_PROVENANCE_INVALID:{interval}")
        if not isinstance(product.get("validated_at_utc"), str) or not product["validated_at_utc"].strip():
            raise CrownMaskAuditError(f"AUTHOR_SOURCE_ROW_PROVENANCE_INVALID:{interval}")
        seen_hashes.add(product["source_sha256"])

    if len(seen_hashes) != 5:
        raise CrownMaskAuditError("AUTHOR_SOURCE_ROWS_NOT_UNIQUE")

    deleted = cleanup.get("deleted_sources")
    if (
        cleanup.get("expected_source_count") != 5
        or cleanup.get("source_files_hash_verified_before_delete") != 5
        or cleanup.get("raw_hdf5_files_before_delete") != 5
        or cleanup.get("raw_hdf5_deleted_count") != 5
        or cleanup.get("raw_hdf5_files_remaining_count") != 0
        or cleanup.get("raw_hdf5_remaining_count", 0) != 0
        or cleanup.get("raw_hdf5_remaining") != []
        or cleanup.get("raw_hdf5_uploaded") is not False
        or cleanup.get("raw_hdf5_deleted_after_verified_drive_retention") is not True
        or cleanup.get("raw_cleanup_evidence_is_post_delete") is not True
        or cleanup.get("raw_directory_removed") is not True
        or not isinstance(deleted, list)
        or len(deleted) != 5
        or not isinstance(cleanup.get("drive_derived_bundle_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", cleanup.get("drive_derived_bundle_sha256", "")) is None
        or not isinstance(cleanup.get("drive_derived_bundle_bytes"), int)
        or cleanup.get("drive_derived_bundle_bytes", 0) <= 0
        or not cleanup.get("drive_derived_bundle_file_id")
        or not cleanup.get("drive_upload_receipt_copy_id")
    ):
        raise CrownMaskAuditError("RAW_SOURCE_DELETE_RECEIPT_INVALID")

    for product, receipt, expected in zip(products, deleted, AUTHOR_EXPECTED_PRODUCTS, strict=True):
        if (
            not isinstance(receipt, dict)
            or receipt.get("source_filename") != expected["filename"]
            or receipt.get("source_bytes") != expected["bytes"]
            or receipt.get("source_sha256") != expected["sha256"]
            or receipt.get("source_filename") != product.get("source_filename")
            or receipt.get("source_bytes") != product.get("source_bytes")
            or receipt.get("source_sha256") != product.get("source_sha256")
            or receipt.get("deleted") is not True
        ):
            raise CrownMaskAuditError("RAW_SOURCE_DELETE_RECEIPT_MISMATCH")


def audit_crown_masks(run_artifact: str | Path, author_archive: str | Path) -> dict[str,Any]:
    runp,authp=Path(run_artifact),Path(author_archive)
    if not runp.is_file() or not authp.is_file(): raise CrownMaskAuditError("INPUT_ARCHIVE_MISSING")
    rb,ab=runp.read_bytes(),authp.read_bytes(); rsha,asha=sha256_bytes(rb),sha256_bytes(ab)
    if asha!=AUTHOR_ARCHIVE_SHA256: raise CrownMaskAuditError("AUTHOR_ARCHIVE_SHA256_MISMATCH")
    try: rz,az=zipfile.ZipFile(io.BytesIO(rb)),zipfile.ZipFile(io.BytesIO(ab))
    except zipfile.BadZipFile as exc: raise CrownMaskAuditError("INPUT_NOT_VALID_ZIP") from exc
    with rz,az:
        if rz.testzip() or az.testzip(): raise CrownMaskAuditError("ZIP_CRC_FAILURE")
        nested_name="author-exact-derived-results.zip"
        if nested_name not in rz.namelist(): raise CrownMaskAuditError("DERIVED_BUNDLE_MISSING")
        outer_raw=[n for n in rz.namelist() if n.lower().endswith((".h5",".hdf5"))]
        with zipfile.ZipFile(io.BytesIO(rz.read(nested_name))) as nz:
            if nz.testzip(): raise CrownMaskAuditError("NESTED_ZIP_CRC_FAILURE")
            inner_raw=[n for n in nz.namelist() if n.lower().endswith((".h5",".hdf5"))]
        if outer_raw or inner_raw: raise CrownMaskAuditError("RAW_HDF5_FOUND_IN_DERIVED_ARTIFACT")
        inputs,source,cleanup,status,report=(_json(rz,n) for n in (
            "know-place-inputs.json","author-exact-source-manifest.json","author-exact-raw-cleanup-receipt.json",
            "author-exact-analysis-status.json","author-raw-site-series-report.json"))
        _validate_wkt(inputs.get("crown_wkt"),CROWN,"CROWN")
        _validate_wkt(inputs.get("reference_box_wkt"),BOX,"REFERENCE_BOX")
        source_manifest_bytes = rz.read("author-exact-source-manifest.json")
        _validate_source_provenance(source, source_manifest_bytes, cleanup)
        if status.get("status")!="OUTPUTS_WRITTEN" or status.get("analysis_metrics_complete") is not True:
            raise CrownMaskAuditError("ANALYSIS_OUTPUT_STATUS_NOT_PASS")
        if (cleanup.get("status")!="PASS" or cleanup.get("raw_hdf5_deleted_count")!=5
            or cleanup.get("raw_hdf5_files_remaining_count")!=0 or cleanup.get("raw_hdf5_uploaded") is not False
            or cleanup.get("remote_derived_bundle_verification")!="PASS"
            or cleanup.get("remote_upload_receipt_copy_verification")!="PASS"):
            raise CrownMaskAuditError("CLEANUP_OR_DRIVE_RECEIPTS_NOT_PASS")
        series=json.loads(az.read("tables/nisar_pot_series.json").decode())
        nulls=json.loads(az.read("tables/polygon_null.json").decode())
        reports=report.get("pair_reports",[])
        if len(series)!=5 or len(nulls)!=5 or len(reports)!=5: raise CrownMaskAuditError("EXPECTED_FIVE_ROWS_PER_TABLE_AND_REPORT")
        rows=[]; common=set()
        for i,(interval,prefix,want_disp,want_r) in enumerate(PAIRS):
            site_name=prefix+"_author_site_series_arrays.npz"; diag_name=prefix+"_diagnostic_arrays.npz"
            site_bytes,diag_bytes=rz.read(site_name),rz.read(diag_name)
            item=reports[i]
            if item.get("pair")!=interval.replace("/","->"): raise CrownMaskAuditError(f"PAIR_INTERVAL_MISMATCH:{prefix}")
            # This legacy report field actually points to the site-array NPZ.
            if item.get("diagnostic_npz")!=site_name or item.get("diagnostic_arrays_sha256")!=sha256_bytes(site_bytes):
                raise CrownMaskAuditError(f"REPORTED_SITE_ARRAY_SHA_MISMATCH:{prefix}")
            r0,r1,c0,c1=_window(item); shape=(r1-r0,c1-c0); ext=item.get("extent_lonlat")
            x=X0+(np.arange(c0,c1)+.5)*DX; y=Y0+(np.arange(r0,r1)+.5)*DY
            with np.load(io.BytesIO(site_bytes),allow_pickle=False) as z:
                need={"east_m","north_m","horizontal_magnitude_m","directional_coherence_R","valid_mask","crown_mask"}
                if not need.issubset(z.files): raise CrownMaskAuditError(f"SITE_ARRAY_SCHEMA_INVALID:{prefix}")
                sm=_mask(z["crown_mask"],shape,"SITE_CROWN_MASK"); valid=_mask(z["valid_mask"],shape,"SITE_VALID_MASK")
                east,north,mag,r=(np.asarray(z[k],dtype=float) for k in ("east_m","north_m","horizontal_magnitude_m","directional_coherence_R"))
                if any(a.shape!=shape for a in (east,north,mag,r)) or not np.array_equal(np.isfinite(east),np.isfinite(north)):
                    raise CrownMaskAuditError(f"SITE_NUMERIC_ARRAY_SHAPE_MISMATCH:{prefix}")
                disp=int(np.count_nonzero(valid&sm)); rc=int(np.count_nonzero(np.isfinite(r)&sm))
                geo=geographic_mask(x,y); crop=endpoint_crop(shape,ext)
            with np.load(io.BytesIO(diag_bytes),allow_pickle=False) as z:
                need={"east_m","north_m","horizontal_magnitude_m","directional_coherence_R","valid_mask","crown_mask","x_coordinates_m","y_coordinates_m"}
                if not need.issubset(z.files): raise CrownMaskAuditError(f"DIAGNOSTIC_SCHEMA_INVALID:{prefix}")
                xd,yd=np.asarray(z["x_coordinates_m"],float),np.asarray(z["y_coordinates_m"],float)
                dm=_mask(z["crown_mask"],(yd.size,xd.size),"DIAGNOSTIC_CROWN_MASK")
                if any(np.asarray(z[k]).shape!=dm.shape for k in ("east_m","north_m","horizontal_magnitude_m","directional_coherence_R","valid_mask")):
                    raise CrownMaskAuditError(f"DIAGNOSTIC_ARRAY_SHAPE_MISMATCH:{prefix}")
                cf=(xd-X0)/DX-.5; rf=(yd-Y0)/DY-.5; cols,grid_rows=np.rint(cf).astype(int),np.rint(rf).astype(int)
                if (np.max(np.abs(cf-cols))>1e-7 or np.max(np.abs(rf-grid_rows))>1e-7
                    or np.any(cols<0) or np.any(cols>=WIDTH) or np.any(grid_rows<0) or np.any(grid_rows>=HEIGHT)):
                    raise CrownMaskAuditError(f"DIAGNOSTIC_AXES_NOT_PINNED_GRID_CENTRES:{prefix}")
                gdiag=geographic_mask(xd,yd)
                globalsite={(int(r0+rr),int(c0+cc)) for rr,cc in np.argwhere(sm)}
                globaldiag={(int(grid_rows[rr]),int(cols[cc])) for rr,cc in np.argwhere(dm)}
            sx=int(np.count_nonzero(sm^geo)); sc=int(np.count_nonzero(sm^crop)); dg=int(np.count_nonzero(dm^gdiag))
            cross=len(globalsite.symmetric_difference(globaldiag)); nc,nd=int(sm.sum()),int(dm.sum())
            a,b=interval.split("/")
            if (str(series[i].get("a")),str(series[i].get("b")))!=(a.replace("-",""),b.replace("-","")):
                raise CrownMaskAuditError(f"PUBLISHED_INTERVAL_MISMATCH:{prefix}")
            if int(series[i].get("n",-1))!=want_disp or int(nulls[i].get("n_px",-1))!=want_r:
                raise CrownMaskAuditError(f"PUBLISHED_COUNT_FIXTURE_MISMATCH:{prefix}")
            pm=nc==nd==EXPECTED_CROWN_CELLS and sx==sc==dg==cross==0
            pc=disp==want_disp==int(series[i]["n"]) and rc==want_r==int(nulls[i]["n_px"])
            sh,dh=_mask_hash(sm),_mask_hash(dm); common.add(sh)
            rows.append({"interval":interval,"site_cells":nc,"diagnostic_cells":nd,"site_mask_sha256":sh,
                "diagnostic_mask_sha256":dh,"site_vs_geographic_xor_cells":sx,"site_vs_endpoint_crop_xor_cells":sc,
                "diagnostic_vs_geographic_xor_cells":dg,"site_vs_diagnostic_global_xor_cells":cross,
                "displacement_valid_n":disp,"published_n":int(series[i]["n"]),
                "coherence_valid_n_px":rc,"published_n_px":int(nulls[i]["n_px"]),
                "status":"PASS" if pm and pc else "FAIL"})
        failures=[r["interval"] for r in rows if r["status"]!="PASS"]
        if len(common)!=1: failures.append("CROSS_PAIR_MASK_HASH_MISMATCH")
        return {"schema_version":"know-place-crown-mask-audit/1.0","status":"PASS" if not failures else "FAIL",
            "scope":"Retained derived arrays and published bounds/source-grid consistency; no raw HDF5 read.",
            "inputs":{"run_artifact":{"name":runp.name,"bytes":len(rb),"sha256":rsha,"source_run_id":cleanup.get("workflow_run_id"),
                 "source_commit":source.get("repository_commit")},"author_archive":{"name":authp.name,"bytes":len(ab),"sha256":asha},
                 "raw_hdf5_outer_members":len(outer_raw),"raw_hdf5_nested_members":len(inner_raw)},
            "grid":{"epsg":EPSG,"width":WIDTH,"height":HEIGHT,"transform":[DX,0,X0,0,DY,Y0],
                    "site_window":{"rows":[2675,2748],"columns":[2827,2907],"shape":[73,80]}},
            "crown_bounds_lonlat":list(CROWN),"reference_box_bounds_lonlat":list(BOX),
            "common_site_mask_sha256":next(iter(common)) if len(common)==1 else None,"pair_count":len(rows),"pairs":rows,
            "counts_are_distinct_estimands":True,
            "author_original_vector_mask_parity":"UNVERIFIED_AUTHOR_EDITABLE_VECTOR_OR_MASK_NOT_IN_ARCHIVE",
            "paper_reproduction_status":"PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED",
            "hazard_detection_status":"NOT_EVALUATED","failures":failures}

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--run-artifact",required=True,type=Path)
    p.add_argument("--author-archive",required=True,type=Path); p.add_argument("--out",required=True,type=Path); a=p.parse_args()
    try: result=audit_crown_masks(a.run_artifact,a.author_archive)
    except (CrownMaskAuditError,OSError,ValueError,zipfile.BadZipFile,json.JSONDecodeError) as exc:
        result={"schema_version":"know-place-crown-mask-audit/1.0","status":"FAIL","error_type":type(exc).__name__,
            "error":str(exc).split(":",1)[0],"author_original_vector_mask_parity":"UNVERIFIED_AUTHOR_EDITABLE_VECTOR_OR_MASK_NOT_IN_ARCHIVE",
            "paper_reproduction_status":"PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED",
            "hazard_detection_status":"NOT_EVALUATED"}
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    print("CROWN_MASK_AUDIT="+result["status"]); print("PAIR_COUNT="+str(result.get("pair_count",0)))
    print("PAPER_REPRODUCTION_STATUS="+result["paper_reproduction_status"]); print("HAZARD_DETECTION_STATUS=NOT_EVALUATED")
    return 0 if result["status"]=="PASS" else 1
if __name__=="__main__": raise SystemExit(main())
