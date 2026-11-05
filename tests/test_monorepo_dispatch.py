"""Exercise new-repository routing while preserving consent and request contracts."""
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/dynamic/Backend'))

@pytest.fixture
def known_place(monkeypatch):
    from app import known_place as module
    with monkeypatch.context() as env:
        env.setenv('KNOWN_PLACE_REPOSITORY', 'Sagormodak/SARGuardian')
        env.setenv('KNOWN_PLACE_REF', 'migration/consolidate-render')
        importlib.reload(module)
        yield module
    importlib.reload(module)

def test_generic_and_paper_dispatch_use_target_repository(known_place, monkeypatch):
    seen = []
    monkeypatch.setattr(known_place, '_github_request', lambda _settings, method, path, body=None: (seen.append((method, path, body)) or (204, {})))
    settings = SimpleNamespace(displacement_actions_enabled=True, github_actions_token='test-token')
    request = known_place.KnownPlaceAnalysisRequest(
        aoi_wkt='POLYGON ((85.50 28.25, 85.54 28.25, 85.54 28.29, 85.50 28.29, 85.50 28.25))',
        start_date='2026-07-01', end_date='2026-07-20', hazard_mode='mixed',
        analysis_mode='exploratory', polarization='HH', track='ANY', direction='A', coherence_neighbours='5',
    )
    result = known_place.dispatch_known_place_analysis(settings, request)
    assert result.github_run_url.startswith('https://github.com/Sagormodak/SARGuardian/actions/')
    assert seen[0][1] == '/repos/Sagormodak/SARGuardian/actions/workflows/know-place-aoi-dispatcher.yml/dispatches'
    assert seen[0][2]['ref'] == 'migration/consolidate-render'
    assert seen[0][2]['inputs']['execute_downloads'] is False
    assert seen[0][2]['inputs']['consent_marker'] == ''
    assert known_place.KNOWN_PLACE_PAPER_REPOSITORY == 'Sagormodak/SARGuardian'
    assert known_place.KNOWN_PLACE_PAPER_REF == 'migration/consolidate-render'

def test_status_and_artifact_lookup_use_same_repository(known_place, monkeypatch):
    from uuid import uuid4
    seen = []
    monkeypatch.setattr(known_place, '_github_request', lambda _settings, method, path, body=None: (seen.append(path) or (200, {'workflow_runs': []})))
    settings = SimpleNamespace(displacement_actions_enabled=True, github_actions_token='test-token')
    known_place.get_known_place_analysis_status(settings, str(uuid4()))
    known_place.get_known_place_paper_reproduction_status(settings, str(uuid4()))
    assert len(seen) == 2
    assert all(path.startswith('/repos/Sagormodak/SARGuardian/actions/workflows/') for path in seen)
