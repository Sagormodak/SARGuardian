from __future__ import annotations

import hashlib

from drive_upload_adapter import _md5_file


def test_drive_md5_checksum_streams_file_and_matches_google_drive_checksum(tmp_path, monkeypatch):
    path = tmp_path / "large-result.tif"
    payload = (b"RiverShift artifact bytes\x00" * 500_000)
    path.write_bytes(payload)

    def reject_read_bytes(_self):
        raise AssertionError("large artifact verification must not read the whole file into memory")

    monkeypatch.setattr(type(path), "read_bytes", reject_read_bytes)

    assert _md5_file(path) == hashlib.md5(payload).hexdigest()
