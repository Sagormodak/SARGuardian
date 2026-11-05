"""Source-inspired reconstruction of the archived displacement-null fields.

Runs only on the deposited CC BY 4.0 derived GeoTIFFs; it never reads or
downloads raw GOFF HDF5. The archive does not include the displacement-null
generator or draw-level rejection history. Matching rounded table values is
numeric output agreement, not proof of original source or draw-sequence identity.
"""
from __future__ import annotations
import argparse, hashlib, io, json, math, zipfile
from pathlib import Path
from typing import Any
import numpy as np
import rasterio

AUTHOR_SHA256="002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3"
DOI="10.5281/zenodo.22730419"
TABLE="tables/displacement_null.json"
SERIES="tables/nisar_pot_series.json"
POLY="tables/polygon_null.json"
CROWN=(85.5245,28.2847,85.5400,28.2970)
SEED=20260907
N_DRAW=1200
MIN_SUPPORT=0.60
PAIRS=(
 ("20260620->20260702","fields/offsets_20260620_20260702.tif",283,302),
 ("20260702->20260714","fields/offsets_20260702_20260714.tif",294,299),
 ("20260714->20260726","fields/offsets_20260714_20260726.tif",296,302),
 ("20260726->20260819","fields/offsets_20260726_20260819.tif",292,298),
 ("20260819->20260831","fields/offsets_20260819_20260831.tif",195,202),
)


class DisplacementNullReconstructionError(ValueError):
    """A source archive or field violates the audit contract."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def disk(shape: tuple[int,int], row: int, col: int, npx: int) -> np.ndarray:
    if len(shape)!=2 or min(shape)<1 or npx<1 or not (0<=row<shape[0] and 0<=col<shape[1]):
        raise DisplacementNullReconstructionError("DISK_INPUT_INVALID")
    radius=math.sqrt(npx/math.pi)
    yy,xx=np.ogrid[:shape[0],:shape[1]]
    return (yy-row)**2+(xx-col)**2<=radius**2


def crown_slice(shape, extent, bounds=CROWN):
    if len(shape)!=2 or min(shape)<1 or len(extent)!=4 or len(bounds)!=4:
        raise DisplacementNullReconstructionError("CROWN_SLICE_INPUT_INVALID")
    x0,x1,y0,y1=map(float,extent)
    west,south,east,north=map(float,bounds)
    if not (x0<x1 and y0<y1 and west<east and south<north):
        raise DisplacementNullReconstructionError("CROWN_SLICE_EXTENT_INVALID")
    ny,nx=shape
    lon=np.linspace(x0,x1,nx)
    lat=np.linspace(y1,y0,ny)
    rows=slice(int(np.searchsorted(-lat,-north)),int(np.searchsorted(-lat,-south)))
    cols=slice(int(np.searchsorted(lon,west)),int(np.searchsorted(lon,east)))
    if rows.start>=rows.stop or cols.start>=cols.stop:
        raise DisplacementNullReconstructionError("CROWN_SLICE_EMPTY")
    return rows,cols


def reconstruct_pair(magnitude: Any, crown_mask: Any, *, rng: np.random.Generator,
                     n_draw: int=N_DRAW, min_support: float=MIN_SUPPORT) -> dict[str,Any]:
    mag=np.asarray(magnitude,dtype=float)
    crown=np.asarray(crown_mask)
    if mag.ndim!=2 or mag.size==0:
        raise DisplacementNullReconstructionError("MAGNITUDE_ARRAY_INVALID")
    if crown.ndim!=2 or crown.shape!=mag.shape:
        raise DisplacementNullReconstructionError("CROWN_MASK_SHAPE_MISMATCH")
    if crown.dtype.kind not in "biuf" or not np.isfinite(crown).all() or not np.isin(crown,(0,1)).all():
        raise DisplacementNullReconstructionError("CROWN_MASK_NOT_BINARY")
    if not isinstance(n_draw,int) or n_draw<=0 or not math.isfinite(min_support) or not 0<min_support<=1:
        raise DisplacementNullReconstructionError("SAMPLING_POLICY_INVALID")
    crown=crown.astype(bool,copy=False)
    valid=np.isfinite(mag)
    obs=mag[crown&valid]
    if not obs.size:
        raise DisplacementNullReconstructionError("CROWN_HAS_NO_VALID_DISPLACEMENT")
    npx=int(obs.size)
    rr,cc=np.nonzero(valid)
    if not rr.size:
        raise DisplacementNullReconstructionError("NO_VALID_CENTRES")
    selected=rng.choice(rr.size,size=min(n_draw,rr.size),replace=False)
    null=[]
    for ix in selected:
        candidate=disk(mag.shape,int(rr[ix]),int(cc[ix]),npx)&valid
        if int(candidate.sum())>=min_support*npx:
            null.append(float(np.median(mag[candidate])))
    arr=np.asarray(null,dtype=float)
    if not arr.size or not np.isfinite(arr).all():
        raise DisplacementNullReconstructionError("NO_ACCEPTED_NULL_DRAWS")
    return {
      "crown_displacement_valid_n":npx,
      "crown_median_m":float(np.median(obs)),
      "candidate_centres_available":int(rr.size),
      "candidate_centres_tried":int(selected.size),
      "accepted_null_draws":int(arr.size),
      "rejected_null_draws":int(selected.size-arr.size),
      "null_median_m":float(np.median(arr)),
      "percentile":float(np.mean(arr<float(np.median(obs)))*100.0),
      "reconstructed_draw_values_sha256":sha256(np.asarray(arr,dtype="<f8").tobytes()),
    }


def _read_tif(payload: bytes, member: str):
    try:
        with rasterio.open(io.BytesIO(payload)) as ds:
            if ds.count!=3 or (ds.width,ds.height)!=(80,73):
                raise DisplacementNullReconstructionError("FIELD_RASTER_SCHEMA_INVALID:"+member)
            if ds.crs is None or ds.crs.to_epsg()!=4326:
                raise DisplacementNullReconstructionError("FIELD_RASTER_CRS_INVALID:"+member)
            if list(ds.descriptions[:2])!=["dE_m ground-referenced east displacement","dN_m ground-referenced north displacement"]:
                raise DisplacementNullReconstructionError("FIELD_BAND_IDENTITY_INVALID:"+member)
            values=ds.read().astype(np.float64)
            tr=ds.transform
            lon0,lon1=tr.c+tr.a*.5,tr.c+tr.a*(ds.width-.5)
            latn,lats=tr.f+tr.e*.5,tr.f+tr.e*(ds.height-.5)
            extent=(min(lon0,lon1),max(lon0,lon1),min(lats,latn),max(lats,latn))
            profile={"width":ds.width,"height":ds.height,"count":ds.count,
              "descriptions":list(ds.descriptions),"crs":ds.crs.to_string(),
              "transform":[float(v) for v in tuple(tr)],"dtype":list(ds.dtypes)}
    except DisplacementNullReconstructionError:
        raise
    except Exception as exc:
        raise DisplacementNullReconstructionError("FIELD_RASTER_READ_FAILED:"+member) from exc
    east,north=values[0],values[1]
    mag=np.hypot(east,north)
    mag[~(np.isfinite(east)&np.isfinite(north))]=np.nan
    return mag,extent,profile


def audit_archive(path: str|Path) -> dict[str,Any]:
    p=Path(path)
    if not p.is_file():
        raise DisplacementNullReconstructionError("AUTHOR_ARCHIVE_MISSING")
    raw=p.read_bytes()
    if sha256(raw)!=AUTHOR_SHA256:
        raise DisplacementNullReconstructionError("AUTHOR_ARCHIVE_SHA256_MISMATCH")
    try: z=zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise DisplacementNullReconstructionError("AUTHOR_ARCHIVE_NOT_ZIP") from exc
    with z:
        bad=z.testzip()
        if bad: raise DisplacementNullReconstructionError("AUTHOR_ARCHIVE_CRC_FAILURE")
        needed=[TABLE,SERIES,POLY]+[m for _,m,_,_ in PAIRS]
        names=set(z.namelist())
        for name in needed:
            if name not in names: raise DisplacementNullReconstructionError("AUTHOR_MEMBER_MISSING:"+name)
        target=json.loads(z.read(TABLE))
        series=json.loads(z.read(SERIES))
        poly=json.loads(z.read(POLY))
        if not (len(target)==len(series)==len(poly)==5):
            raise DisplacementNullReconstructionError("TABLE_ROW_COUNT_INVALID")
        rng=np.random.default_rng(SEED)
        rows=[]
        for i,(pair,member,expected_n,expected_r_n) in enumerate(PAIRS):
            if target[i].get("pair")!=pair or f"{series[i].get('a')}->{series[i].get('b')}"!=pair or poly[i].get("pair")!=pair:
                raise DisplacementNullReconstructionError("PAIR_ORDER_MISMATCH:"+pair)
            payload=z.read(member)
            mag,extent,profile=_read_tif(payload,member)
            rs,cs=crown_slice(mag.shape,extent)
            mask=np.zeros(mag.shape,dtype=bool); mask[rs,cs]=True
            result=reconstruct_pair(mag,mask,rng=rng)
            if int(series[i].get("n",-1))!=expected_n or result["crown_displacement_valid_n"]!=expected_n:
                raise DisplacementNullReconstructionError("DISPLACEMENT_COUNT_MISMATCH:"+pair)
            if int(poly[i].get("n_px",-1))!=expected_r_n:
                raise DisplacementNullReconstructionError("COHERENCE_COUNT_MISMATCH:"+pair)
            ok=(round(result["crown_median_m"],2)==round(float(target[i]["crown"]),2)
                and round(result["null_median_m"],2)==round(float(target[i]["null_med"]),2)
                and round(result["percentile"],1)==round(float(target[i]["pctile"]),1))
            rows.append({"pair":pair,"field_member":member,"field_member_bytes":len(payload),
              "field_member_sha256":sha256(payload),"field_profile":profile,
              "crown_slice_shape":[rs.stop-rs.start,cs.stop-cs.start],**result,
              "published_crown_m":float(target[i]["crown"]),
              "published_null_median_m":float(target[i]["null_med"]),
              "published_percentile":float(target[i]["pctile"]),
              "comparison_status":"PASS_AT_PUBLISHED_TABLE_PRECISION" if ok else "FAIL_AT_PUBLISHED_TABLE_PRECISION"})
        passed=all(r["comparison_status"]=="PASS_AT_PUBLISHED_TABLE_PRECISION" for r in rows)
        table_bytes=z.read(TABLE)
        return {
          "schema_version":"know-place-displacement-null-reconstruction/1.0",
          "status":"PASS_AT_PUBLISHED_TABLE_PRECISION" if passed else "FAIL_AT_PUBLISHED_TABLE_PRECISION",
          "scope":"Derived-only source-inspired reconstruction; no raw HDF5 read/download.",
          "inputs":{"author_archive":{"name":p.name,"bytes":len(raw),"sha256":sha256(raw),"doi":DOI},
            "published_table":{"path":TABLE,"bytes":len(table_bytes),"sha256":sha256(table_bytes)}},
          "policy":{"seed":SEED,"rng":"numpy.default_rng / PCG64; shared stream in chronological order",
            "draws":N_DRAW,"centre_domain":"finite magnitude centres sampled without replacement",
            "region":"pixel-index disk with nominal area equal to valid crown displacement count",
            "acceptance":"minimum 60% valid support","percentile":"strict fraction of accepted null medians below observed crown median",
            "method_origin":"source-inspired mirror of code/polygon_null.py; the displacement-specific generator is absent"},
          "original_generator_source":"NOT_PRESENT_IN_REVIEWED_ZENODO_ARCHIVE",
          "author_draw_sequence_identity":"UNVERIFIED_NO_ORIGINAL_DRAW_OR_REJECTION_HISTORY",
          "paper_reproduction_status":"PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED",
          "hazard_detection_status":"NOT_EVALUATED","rows":rows,
          "limitations":[
            "The five crown/null medians and percentiles match archived table precision under this declared reconstruction.",
            "The archive does not contain the displacement-null generator or draw-level rejection history.",
            "Numeric output match does not prove source-code or original draw-sequence identity.",
            "No operational warning or event-level hazard skill is evaluated."
          ]}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--author-archive",required=True,type=Path)
    parser.add_argument("--out",required=True,type=Path)
    args=parser.parse_args()
    try: report=audit_archive(args.author_archive)
    except (DisplacementNullReconstructionError,OSError,ValueError,zipfile.BadZipFile,json.JSONDecodeError) as exc:
        report={"schema_version":"know-place-displacement-null-reconstruction/1.0","status":"FAIL",
          "error_type":type(exc).__name__,"error":str(exc).split(":",1)[0],
          "original_generator_source":"NOT_PRESENT_IN_REVIEWED_ZENODO_ARCHIVE",
          "paper_reproduction_status":"PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED",
          "hazard_detection_status":"NOT_EVALUATED"}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    print("DISPLACEMENT_NULL_RECONSTRUCTION="+str(report.get("status")))
    print("DISPLACEMENT_NULL_PAIRS="+str(sum(r.get("comparison_status")=="PASS_AT_PUBLISHED_TABLE_PRECISION" for r in report.get("rows",[]))))
    print("ORIGINAL_GENERATOR_SOURCE="+str(report.get("original_generator_source")))
    print("PAPER_REPRODUCTION_STATUS="+str(report.get("paper_reproduction_status")))
    print("HAZARD_DETECTION_STATUS=NOT_EVALUATED")
    return 0 if report.get("status")=="PASS_AT_PUBLISHED_TABLE_PRECISION" else 1


if __name__=="__main__":
    raise SystemExit(main())
