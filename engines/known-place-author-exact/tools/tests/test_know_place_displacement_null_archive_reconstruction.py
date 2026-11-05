from __future__ import annotations
import numpy as np
import pytest
from tools.know_place.displacement_null_archive_reconstruction import (
    DisplacementNullReconstructionError, crown_slice, disk, reconstruct_pair
)


def _fixture():
    yy,xx=np.mgrid[:24,:30]
    mag=(.05+.002*yy+.003*xx+.08*np.abs(np.sin(xx+2*yy))).astype(float)
    mag[(yy*3+xx*5)%17==0]=np.nan
    crown=np.zeros(mag.shape,dtype=bool); crown[9:15,10:18]=True
    return mag,crown


def test_seeded_reconstruction_is_deterministic():
    mag,crown=_fixture()
    a=reconstruct_pair(mag,crown,rng=np.random.default_rng(20260907),n_draw=300)
    b=reconstruct_pair(mag,crown,rng=np.random.default_rng(20260907),n_draw=300)
    assert a==b and a["crown_displacement_valid_n"]>0
    assert 0<=a["percentile"]<=100 and 0<a["accepted_null_draws"]<=300
    assert a["candidate_centres_tried"]==300 and len(a["reconstructed_draw_values_sha256"])==64


def test_crown_slice_uses_published_endpoint_policy():
    rs,cs=crown_slice((73,80),(85.4997873137,85.5649316446,28.2657831210,28.3170684719))
    assert (rs.stop-rs.start,cs.stop-cs.start)==(17,19)


def test_disk_area_radius_rule():
    assert int(disk((9,9),4,4,1).sum())==1
    assert disk((9,9),4,4,25).shape==(9,9)


def test_empty_crown_support_fails_closed():
    mag=np.full((10,10),np.nan); crown=np.zeros((10,10),bool); crown[2:4,2:4]=True
    with pytest.raises(DisplacementNullReconstructionError,match="CROWN_HAS_NO_VALID_DISPLACEMENT"):
        reconstruct_pair(mag,crown,rng=np.random.default_rng(1))


def test_invalid_mask_and_sampling_policy_fail_closed():
    mag,crown=_fixture()
    with pytest.raises(DisplacementNullReconstructionError,match="CROWN_MASK_SHAPE_MISMATCH"):
        reconstruct_pair(mag,np.ones((9,10)),rng=np.random.default_rng(1))
    bad=np.zeros(mag.shape,float); bad[1,1]=2
    with pytest.raises(DisplacementNullReconstructionError,match="CROWN_MASK_NOT_BINARY"):
        reconstruct_pair(mag,bad,rng=np.random.default_rng(1))
    with pytest.raises(DisplacementNullReconstructionError,match="SAMPLING_POLICY_INVALID"):
        reconstruct_pair(mag,crown,rng=np.random.default_rng(1),n_draw=0)
