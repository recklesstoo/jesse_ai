from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

import backend.app as app_module


def test_ml_model_upload_roundtrip(tmp_path):
    client = TestClient(app_module.app)
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    payload = b"FAKE_JOBLIB_HEADER_CONTENT_FOR_TESTING"
    files = {"file": (f"{bot_id}.joblib", payload, "application/octet-stream")}

    res = client.post(f"/api/v1/ml/upload/{bot_id}", files=files)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["bot_id"] == bot_id

    # The file should now be downloadable.
    dl = client.get(f"/api/v1/ml/model/{bot_id}")
    assert dl.status_code == 200
    assert dl.content == payload

