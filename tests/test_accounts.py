import json

import app


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_add_account_allows_empty_new_api_user(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    write_json(app.CONFIG_PATH, {"base_url": "https://example.test", "accounts": []})

    with app.app.test_client() as client:
        response = client.post(
            "/api/accounts",
            json={
                "name": "optional fields",
                "base_url": "https://example.test",
                "new_api_user": "",
                "session": "session-value-that-is-long-enough",
                "enabled": True,
            },
        )

    assert response.status_code == 200
    account = response.get_json()["account"]
    assert account["new_api_user"] == ""


def test_update_account_allows_empty_new_api_user():
    payload = {
        "name": "account",
        "base_url": "https://example.test",
        "new_api_user": "",
        "session": "session-value-that-is-long-enough",
        "enabled": True,
    }

    parsed = app.parse_account_payload(payload)

    assert parsed["new_api_user"] == ""


def test_new_api_user_must_be_numeric_when_provided():
    payload = {
        "name": "account",
        "base_url": "https://example.test",
        "new_api_user": "abc",
        "session": "session-value-that-is-long-enough",
        "enabled": True,
    }

    try:
        app.parse_account_payload(payload)
    except ValueError as exc:
        assert "numeric" in str(exc)
    else:
        raise AssertionError("non-numeric new_api_user should be rejected")


def test_normalize_account_removes_legacy_account_remark():
    normalized = app.normalize_account(
        {
            "name": "account",
            "remark": "legacy note",
            "base_url": "https://example.test",
            "new_api_user": "",
            "session": "session-value-that-is-long-enough",
        }
    )

    assert "remark" not in normalized
