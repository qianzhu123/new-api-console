import json

import app


SIGNED = "\u5df2\u7b7e\u5230"
UNSIGNED = "\u672a\u7b7e\u5230"


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_ambiguous_legacy_name_status_does_not_mark_duplicate_accounts_signed(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    write_json(
        app.SIGNIN_PATH,
        {
            "date": app.today_str(),
            "accounts": {
                "qianzhu": {
                    "status": SIGNED,
                    "updated_at": f"{app.today_str()} 08:00:00",
                }
            },
        },
    )

    accounts = [
        {"account_index": 3, "name": "qianzhu", "enabled": True},
        {"account_index": 9, "name": "qianzhu", "enabled": True},
    ]

    public_accounts = app.build_public_accounts(accounts)

    assert [item["signin_status"] for item in public_accounts] == [UNSIGNED, UNSIGNED]


def test_status_one_returns_today_signin_status_after_daily_rollover(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {
                    "account_index": 2,
                    "name": "ning zhang",
                    "enabled": True,
                    "base_url": "https://example.test",
                    "new_api_user": "123",
                    "session": "session-value-that-is-long-enough",
                    "api_keys": [],
                }
            ]
        },
    )
    write_json(
        app.SIGNIN_PATH,
        {
            "date": "2000-01-01",
            "accounts": {
                "2": {
                    "status": SIGNED,
                    "updated_at": "2000-01-01 08:00:00",
                }
            },
        },
    )
    monkeypatch.setattr(app, "fetch_public_status", lambda base_url=None: {"ok": True})
    monkeypatch.setattr(
        app,
        "check_status",
        lambda account, system_status=None: {
            "account": account["name"],
            "status_state": "VALID",
            "session_valid": True,
        },
    )

    with app.app.test_client() as client:
        response = client.post("/api/accounts/2/status", json={})

    assert response.status_code == 200
    assert response.get_json()["result"]["signin_status"] == UNSIGNED


def test_status_all_returns_today_signin_status_after_daily_rollover(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {
                    "account_index": 2,
                    "name": "ning zhang",
                    "enabled": True,
                    "base_url": "https://example.test",
                    "new_api_user": "123",
                    "session": "session-value-that-is-long-enough",
                    "api_keys": [],
                }
            ]
        },
    )
    write_json(
        app.SIGNIN_PATH,
        {
            "date": "2000-01-01",
            "accounts": {
                "2": {
                    "status": SIGNED,
                    "updated_at": "2000-01-01 08:00:00",
                }
            },
        },
    )
    monkeypatch.setattr(app, "fetch_public_status", lambda base_url=None: {"ok": True})
    monkeypatch.setattr(
        app,
        "check_status",
        lambda account, system_status=None: {
            "account": account["name"],
            "status_state": "VALID",
            "session_valid": True,
        },
    )

    with app.app.test_client() as client:
        response = client.post("/api/accounts/status-all", json={})

    assert response.status_code == 200
    assert response.get_json()["results"][0]["signin_status"] == UNSIGNED


def test_frontend_updates_signin_status_from_status_checks():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "state.signinStatus[key] = data.result.signin_status;" in template
    assert "state.signinStatus[key] = r.signin_status;" in template
