import json
from datetime import date
from urllib.parse import parse_qs, urlparse

from discover_gcov_products import search_catalogue


def test_all_maturity_queries_beta_and_provisional_as_distinct_collections(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self):
            self.headers = {"CMR-Hits": "0"}
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return json.dumps({"hits": 0, "items": []}).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append(parse_qs(urlparse(request.full_url).query))
        return FakeResponse()

    monkeypatch.setattr("discover_gcov_products.urllib.request.urlopen", fake_urlopen)
    result = search_catalogue(
        "POLYGON ((89.6 24.4, 89.8 24.4, 89.8 24.6, 89.6 24.6, 89.6 24.4))",
        date(2026, 6, 17), date(2026, 10, 31),
        "ALL", None, None, 100, 20, "ALL",
    )
    assert len(calls) == 2
    assert {item["short_name"][0] for item in calls} == {
        "NISAR_L2_GCOV_BETA_V1",
        "NISAR_L2_GCOV_PROVISIONAL_V1",
    }
    assert result["product_count"] == 0
    assert result["query"]["collection_short_names"] == [
        "NISAR_L2_GCOV_BETA_V1",
        "NISAR_L2_GCOV_PROVISIONAL_V1",
    ]
