from __future__ import annotations

from pathlib import Path

import pytest

from mcp_servers.browser.server.artifacts import ArtifactStore


def test_put_file_and_export_roundtrip(tmp_path: Path) -> None:
    store = ArtifactStore(base_dir=tmp_path / "artifacts")

    src = tmp_path / "sample.txt"
    src.write_text("hello\nworld\n", encoding="utf-8")

    ref = store.put_file(kind="download_file", src_path=src, mime_type="text/plain", ext=".txt", metadata={"k": "v"})
    assert ref.id

    sl = store.get_text_slice(artifact_id=ref.id, offset=0, max_chars=50)
    assert "hello" in sl.get("text", "")

    out_dir = tmp_path / "outbox"
    payload = store.export(artifact_id=ref.id, out_dir=out_dir, name="exported.txt", overwrite=False)
    assert payload.get("ok") is True
    assert (out_dir / "exported.txt").exists()
    assert (out_dir / "exported.txt").read_text(encoding="utf-8") == "hello\nworld\n"

    with pytest.raises(FileExistsError):
        store.export(artifact_id=ref.id, out_dir=out_dir, name="exported.txt", overwrite=False)

    payload2 = store.export(artifact_id=ref.id, out_dir=out_dir, name="exported.txt", overwrite=True)
    assert payload2.get("ok") is True
