import json

import app


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


def site_config():
    return {
        "base_url": "https://example.test",
        "accounts": [
            {
                "account_index": 7,
                "name": "first",
                "enabled": True,
                "base_url": "https://example.test",
                "new_api_user": "100",
                "session": "first-session-value-that-is-long-enough",
                "api_keys": [],
            },
            {
                "account_index": 8,
                "name": "second",
                "enabled": True,
                "base_url": "https://example.test",
                "new_api_user": "200",
                "session": "second-session-value-that-is-long-enough",
                "api_keys": [],
            },
        ],
    }


def test_site_remark_is_saved_outside_account_config(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(app.CONFIG_PATH, site_config())

    with app.app.test_client() as client:
        response = client.put(
            "/api/sites/info",
            json={"base_url": "https://example.test", "remark": "聚合地址备注"},
        )

    assert response.status_code == 200
    assert response.get_json()["site"]["remark"] == "聚合地址备注"
    site_store = json.loads(app.SITE_INFO_PATH.read_text(encoding="utf-8"))
    assert site_store["sites"]["https://example.test"]["remark"] == "聚合地址备注"
    config = json.loads(app.CONFIG_PATH.read_text(encoding="utf-8"))
    assert all("remark" not in account for account in config["accounts"])


def test_site_models_use_first_account_filter_and_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(app.CONFIG_PATH, site_config())
    calls = []

    def fake_get(url, cookies=None, headers=None, timeout=None):
        calls.append({"url": url, "cookies": cookies, "headers": headers, "timeout": timeout})
        return FakeResponse(
            {
                "success": True,
                "message": "",
                "data": [
                    "codex-gpt-image-2",
                    "gpt-image-2",
                    "gpt-4.1",
                    "claude-sonnet-4",
                    "Gemini-3.1-pro",
                    "grok-build-0.1",
                ],
            }
        )

    monkeypatch.setattr(app.requests, "get", fake_get)

    with app.app.test_client() as client:
        response = client.post("/api/sites/models", json={"base_url": "https://example.test"})

    assert response.status_code == 200
    assert response.get_json()["models"] == [
        "codex-gpt-image-2",
        "gpt-image-2",
        "gpt-4.1",
        "claude-sonnet-4",
        "Gemini-3.1-pro",
    ]
    assert calls[0]["url"] == "https://example.test/api/user/models"
    assert calls[0]["cookies"] == {"session": "first-session-value-that-is-long-enough"}
    assert calls[0]["headers"]["new-api-user"] == "100"
    assert calls[0]["headers"]["referer"] == "https://example.test/keys"
    cached = json.loads(app.SITE_INFO_PATH.read_text(encoding="utf-8"))
    assert cached["sites"]["https://example.test"]["models"] == response.get_json()["models"]
