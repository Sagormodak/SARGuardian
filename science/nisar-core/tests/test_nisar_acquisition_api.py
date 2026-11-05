from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import nisar_acquisition as acquisition


def test_asf_search_uses_a_documented_json_output_format(monkeypatch):
    captured = {}

    def fake_get(url):
        parsed = urlparse(url)
        captured.update(parse_qs(parsed.query))
        return {"results": [{"granuleName": "NISAR_L2_PR_GUNW_example"}]}

    monkeypatch.setattr(acquisition, "_get", fake_get)
    rows = acquisition.asf_query(
        warn_on_cap=False,
        platform="NISAR",
        processingLevel="GUNW",
    )

    assert captured["output"] == ["json"]
    assert captured["platform"] == ["NISAR"]
    assert captured["processingLevel"] == ["GUNW"]
    assert rows == [{"granuleName": "NISAR_L2_PR_GUNW_example"}]
    assert "jsonlite" not in captured["output"]

def test_asf_http_error_body_is_preserved_without_url_or_secret(monkeypatch):
    import io
    import urllib.error
    import pytest

    body = b'{"errors":["Invalid value for processingLevel"],"token":"secret-value"}'

    def fake_urlopen(url, timeout):
        raise urllib.error.HTTPError(
            url, 400, "Bad Request", hdrs=None, fp=io.BytesIO(body)
        )

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="Invalid value for processingLevel") as caught:
        acquisition._get("https://asf.example.invalid/query", retries=1)

    assert "secret-value" not in str(caught.value)
