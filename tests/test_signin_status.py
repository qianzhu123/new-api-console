import json

import app


SIGNED = "\u5df2\u7b7e\u5230"
UNSIGNED = "\u672a\u7b7e\u5230"
UNSUPPORTED = "\u4e0d\u53ef\u7b7e\u5230"


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


def test_signin_store_preserves_unsupported_status(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    write_json(
        app.SIGNIN_PATH,
        {
            "date": app.today_str(),
            "accounts": {
                "7": {
                    "status": UNSUPPORTED,
                    "updated_at": f"{app.today_str()} 08:00:00",
                }
            },
        },
    )

    assert app.get_signin_status_today("7") == UNSUPPORTED


def test_classify_checkin_marks_missing_endpoint_unsupported(monkeypatch):
    monkeypatch.setattr(
        app.requests,
        "post",
        lambda *args, **kwargs: FakeResponse({"message": "not found"}, status_code=404),
    )

    result = app.classify_checkin(
        {
            "account_index": 7,
            "name": "no checkin",
            "base_url": "https://example.test",
            "new_api_user": "7",
            "session": "session-value-that-is-long-enough",
        }
    )

    assert result["state"] == "UNSUPPORTED"


def test_classify_checkin_does_not_use_status_cache_to_skip_checkin(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(
        app.STATUS_CACHE_PATH,
        {
            "accounts": {
                "7": {
                    "system_status": {
                        "checkin_enabled": False,
                    }
                }
            }
        },
    )

    calls = []

    def fake_post(*args, **kwargs):
        calls.append(args)
        return FakeResponse({"success": True, "message": "ok"})

    monkeypatch.setattr(app.requests, "post", fake_post)
    result = app.classify_checkin(
        {
            "account_index": 7,
            "name": "no checkin",
            "base_url": "https://example.test",
            "new_api_user": "7",
            "session": "session-value-that-is-long-enough",
        }
    )

    assert calls
    assert result["state"] == "SIGNED_NOW"


def test_checkin_one_marks_only_current_account_unsupported(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {
                    "account_index": 7,
                    "name": "first",
                    "enabled": True,
                    "base_url": "https://example.test",
                    "new_api_user": "7",
                    "session": "session-value-that-is-long-enough",
                },
                {
                    "account_index": 8,
                    "name": "second",
                    "enabled": True,
                    "base_url": "https://example.test",
                    "new_api_user": "8",
                    "session": "another-session-value-long-enough",
                },
            ]
        },
    )
    monkeypatch.setattr(
        app.requests,
        "post",
        lambda *args, **kwargs: FakeResponse({"message": "not found"}, status_code=404),
    )

    with app.app.test_client() as client:
        response = client.post("/api/accounts/7/checkin", json={})

    assert response.status_code == 200
    assert response.get_json()["result"]["state"] == "UNSUPPORTED"
    assert app.get_signin_status_today("7") == UNSUPPORTED
    assert app.get_signin_status_today("8") == UNSIGNED


def test_checkin_all_only_requests_unsigned_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {
                    "account_index": 7,
                    "name": "first",
                    "enabled": True,
                    "base_url": "https://unsupported.test",
                },
                {
                    "account_index": 8,
                    "name": "second",
                    "enabled": True,
                    "base_url": "https://unsupported.test",
                },
                {
                    "account_index": 9,
                    "name": "unsigned",
                    "enabled": True,
                    "base_url": "https://supported.test",
                },
                {
                    "account_index": 10,
                    "name": "signed",
                    "enabled": True,
                    "base_url": "https://supported.test",
                },
            ]
        },
    )
    write_json(
        app.SIGNIN_PATH,
        {
            "date": app.today_str(),
            "accounts": {
                "7": {
                    "status": UNSUPPORTED,
                    "updated_at": f"{app.today_str()} 08:00:00",
                },
                "10": {
                    "status": SIGNED,
                    "updated_at": f"{app.today_str()} 08:00:00",
                }
            },
        },
    )
    checked_accounts = []

    def fake_classify(account):
        checked_accounts.append(account["account_index"])
        return {
            "account": account["name"],
            "state": "SIGNED_NOW",
            "message": "ok",
            "timestamp": app.now_ts(),
        }

    monkeypatch.setattr(app, "classify_checkin", fake_classify)

    with app.app.test_client() as client:
        response = client.post("/api/accounts/checkin-all", json={})

    assert response.status_code == 200
    payload = response.get_json()
    results = payload["results"]
    assert checked_accounts == [8, 9]
    assert [result["state"] for result in results] == ["SIGNED_NOW", "SIGNED_NOW"]
    assert payload["eligible_count"] == 2
    assert payload["skipped_signed"] == 1
    assert payload["skipped_unsupported"] == 1
    assert app.get_signin_status_today("8") == SIGNED


def test_status_failure_does_not_overwrite_last_success_or_mark_site(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {
                    "account_index": 7,
                    "name": "first",
                    "enabled": True,
                    "base_url": "https://example.test",
                    "new_api_user": "7",
                    "session": "session-value-that-is-long-enough",
                },
                {
                    "account_index": 8,
                    "name": "second",
                    "enabled": True,
                    "base_url": "https://example.test",
                    "new_api_user": "8",
                    "session": "another-session-value-long-enough",
                },
            ]
        },
    )
    last_success = {
        "account": "first",
        "account_index": 7,
        "status_state": "VALID",
        "session_valid": True,
        "quota": {"quota": 123},
        "system_status": {"checkin_enabled": True},
    }
    write_json(app.STATUS_CACHE_PATH, {"accounts": {"7": last_success}})
    monkeypatch.setattr(app, "fetch_public_status", lambda base_url=None: {"ok": True, "checkin_enabled": False})
    monkeypatch.setattr(
        app,
        "check_status",
        lambda account, system_status=None: {
            "account": account["name"],
            "account_index": account["account_index"],
            "status_state": "API_ERROR",
            "session_valid": False,
            "api_error": "boom",
            "system_status": system_status,
        },
    )

    with app.app.test_client() as client:
        response = client.post("/api/accounts/7/status", json={})

    assert response.status_code == 200
    assert response.get_json()["result"]["status_state"] == "API_ERROR"
    assert app.get_status_cache("7") == last_success
    assert app.get_signin_status_today("7") == UNSIGNED
    assert app.get_signin_status_today("8") == UNSIGNED
    assert app.get_site_info("https://example.test")["checkin_mode"] == "auto"


def test_status_failure_persists_latest_error_while_preserving_last_success(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {
                    "account_index": 7,
                    "name": "first",
                    "enabled": True,
                    "base_url": "https://example.test",
                    "new_api_user": "7",
                    "session": "session-value-that-is-long-enough",
                }
            ]
        },
    )
    last_success = {
        "account": "first",
        "account_index": 7,
        "status_state": "VALID",
        "session_valid": True,
        "quota": {"quota": 123},
    }
    latest_error = {
        "account": "first",
        "account_index": 7,
        "status_state": "API_ERROR",
        "session_valid": False,
        "api_error": "boom",
    }
    write_json(app.STATUS_CACHE_PATH, {"accounts": {"7": last_success}})
    monkeypatch.setattr(app, "fetch_public_status", lambda base_url=None: {"ok": True})
    monkeypatch.setattr(app, "check_status", lambda account, system_status=None: dict(latest_error))

    with app.app.test_client() as client:
        response = client.post("/api/accounts/7/status", json={})
        accounts_response = client.get("/api/accounts")

    assert response.status_code == 200
    assert app.get_status_cache("7") == last_success
    assert app.get_latest_status_cache("7")["status_state"] == "API_ERROR"
    account = accounts_response.get_json()["accounts"][0]
    assert account["last_status"]["status_state"] == "VALID"
    assert account["latest_status"]["status_state"] == "API_ERROR"


def test_manual_marker_for_forced_unsupported_site_preserves_mode_and_public_status(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    base_url = "https://api.e2ez.com"
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {
                    "account_index": 7,
                    "name": "forced manual",
                    "enabled": True,
                    "base_url": base_url,
                    "new_api_user": "7",
                    "session": "session-value-that-is-long-enough",
                    "api_keys": [],
                }
            ]
        },
    )
    write_json(app.SITE_INFO_PATH, {"sites": {base_url: {"checkin_mode": "manual"}}})

    with app.app.test_client() as client:
        response = client.post("/api/sites/manual-signin", json={"base_url": base_url, "signed": True})
        accounts_response = client.get("/api/accounts")

    assert response.status_code == 200
    assert response.get_json()["site"]["checkin_mode"] == "manual"
    assert response.get_json()["site"]["daily_signin_marked"] is True
    assert accounts_response.get_json()["accounts"][0]["signin_status"] == UNSUPPORTED


def test_manual_marker_for_disabled_site_preserves_mode_and_public_status(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    base_url = "https://disabled.example.test"
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {
                    "account_index": 8,
                    "name": "disabled account",
                    "enabled": True,
                    "base_url": base_url,
                    "new_api_user": "8",
                    "session": "another-session-value-long-enough",
                    "api_keys": [],
                }
            ]
        },
    )
    write_json(app.SITE_INFO_PATH, {"sites": {base_url: {"checkin_mode": "disabled"}}})

    with app.app.test_client() as client:
        response = client.post("/api/sites/manual-signin", json={"base_url": base_url, "signed": True})
        site_response = client.get("/api/sites/info", query_string={"base_url": base_url})

    assert response.status_code == 200
    assert response.get_json()["site"]["checkin_mode"] == "disabled"
    assert site_response.get_json()["site"]["daily_signin_marked"] is True
    assert response.get_json()["accounts"][0]["signin_status"] == UNSUPPORTED


def test_manual_marker_for_manual_site_preserves_public_unsupported_status(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    base_url = "https://manual.example.test"
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {
                    "account_index": 9,
                    "name": "manual account",
                    "enabled": True,
                    "base_url": base_url,
                    "new_api_user": "9",
                    "session": "manual-session-value-long-enough",
                    "api_keys": [],
                }
            ]
        },
    )
    write_json(app.SITE_INFO_PATH, {"sites": {base_url: {"checkin_mode": "manual"}}})

    with app.app.test_client() as client:
        response = client.post("/api/sites/manual-signin", json={"base_url": base_url, "signed": True})

    assert response.status_code == 200
    assert response.get_json()["site"]["daily_signin_marked"] is True
    assert response.get_json()["accounts"][0]["signin_status"] == UNSUPPORTED


def test_site_daily_signin_marker_requires_every_site_account_signed(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    base_url = "https://multi.example.test"
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {"account_index": 11, "name": "first", "enabled": True, "base_url": base_url},
                {"account_index": 12, "name": "second", "enabled": True, "base_url": base_url},
            ]
        },
    )

    assert app.site_daily_signin_marked(base_url) is False

    app.set_signin_status_today("11", SIGNED)

    assert app.site_daily_signin_marked(base_url) is False

    app.set_signin_status_today("12", SIGNED)

    assert app.site_daily_signin_marked(base_url) is True


def test_site_manual_signin_rejects_empty_site(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(app.CONFIG_PATH, {"accounts": []})

    with app.app.test_client() as client:
        response = client.post("/api/sites/manual-signin", json={"base_url": "https://empty.example.test", "signed": True})

    assert response.status_code == 404
    assert response.get_json()["error"] == "site has no accounts"


def test_site_manual_signin_unmark_clears_only_signed_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    base_url = "https://unmark.example.test"
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {"account_index": 21, "name": "signed", "enabled": True, "base_url": base_url},
                {"account_index": 22, "name": "unsupported", "enabled": True, "base_url": base_url},
            ]
        },
    )
    app.set_signin_status_today("21", SIGNED)
    app.set_signin_status_today("22", UNSUPPORTED)

    with app.app.test_client() as client:
        response = client.post("/api/sites/manual-signin", json={"base_url": base_url, "signed": False})

    assert response.status_code == 200
    assert response.get_json()["site"]["daily_signin_marked"] is False
    assert app.get_signin_status_today("21") == UNSIGNED
    assert app.get_signin_status_today("22") == UNSUPPORTED


def test_site_checkin_status_preserves_explicit_manual_mode_and_daily_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    base_url = "https://manual-detect.example.test"
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {"account_index": 31, "name": "manual", "enabled": True, "base_url": base_url},
            ]
        },
    )
    write_json(app.SITE_INFO_PATH, {"sites": {base_url: {"checkin_mode": "manual"}}})
    app.set_signin_status_today("31", SIGNED)
    monkeypatch.setattr(app, "fetch_public_status", lambda base_url=None: {"ok": True, "checkin_enabled": False})

    with app.app.test_client() as client:
        response = client.post("/api/sites/checkin-status", json={"base_url": base_url})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["site"]["checkin_mode"] == "manual"
    assert payload["site"]["daily_signin_marked"] is True
    assert app.get_signin_status_today("31") == SIGNED


def test_site_checkin_status_preserves_explicit_disabled_mode_and_daily_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    base_url = "https://disabled-detect.example.test"
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {"account_index": 32, "name": "disabled", "enabled": True, "base_url": base_url},
            ]
        },
    )
    write_json(app.SITE_INFO_PATH, {"sites": {base_url: {"checkin_mode": "disabled"}}})
    app.set_signin_status_today("32", SIGNED)
    monkeypatch.setattr(app, "fetch_public_status", lambda base_url=None: {"ok": True, "checkin_enabled": True})

    with app.app.test_client() as client:
        response = client.post("/api/sites/checkin-status", json={"base_url": base_url})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["site"]["checkin_mode"] == "disabled"
    assert payload["site"]["daily_signin_marked"] is True
    assert app.get_signin_status_today("32") == SIGNED


def test_site_checkin_status_updates_enabled_mode_from_detection(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    base_url = "https://enabled-detect.example.test"
    write_json(app.CONFIG_PATH, {"accounts": [{"account_index": 33, "name": "enabled", "enabled": True, "base_url": base_url}]})
    write_json(app.SITE_INFO_PATH, {"sites": {base_url: {"checkin_mode": "enabled"}}})
    monkeypatch.setattr(app, "fetch_public_status", lambda base_url=None: {"ok": True, "checkin_enabled": False})

    with app.app.test_client() as client:
        response = client.post("/api/sites/checkin-status", json={"base_url": base_url})

    assert response.status_code == 200
    assert response.get_json()["site"]["checkin_mode"] == "disabled"


def test_frontend_disables_unsupported_group_checkin_and_uses_chevron_icon():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "function accountCheckinUnsupported" in template
    assert "function isGroupCheckinUnsupported" in template
    assert "function markAccountCheckinUnsupported" in template
    assert "rowSum.checkinText = '不可签到';" in template
    assert "=== '未签到'" in template
    assert "data.skipped_signed" in template
    assert "不可签到" in template
    assert "fold-icon" in template
    assert "manual-signin-chip" not in template
    assert "manual_signin_required" not in template
    assert "'▶'" not in template
    assert "'▼'" not in template


def test_frontend_manual_and_disabled_sites_show_marker_while_rows_stay_unsupported():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "siteInfoForBaseUrl(baseUrl).daily_signin_marked === true" in template
    assert "siteCheckinManual(baseUrl)) return true" in template
    assert "checkinMode !== 'enabled'" in template


def test_frontend_current_status_error_overrides_last_success_for_group_counts():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "return state.statusErrors[key] || state.statusResults[key] || acc?.last_status || null;" in template


def test_frontend_restores_latest_status_errors_after_refresh():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "acc.latest_status" in template
    assert "state.statusErrors[key] = acc.latest_status" in template


def test_batch_defaults_are_tuned_for_parallel_network_work():
    assert app.MAX_BATCH_WORKERS >= 16
    assert app.TIMEOUT_SECONDS <= 12
    assert app.HTTP_RETRY_ATTEMPTS <= 2


def test_detail_address_and_site_detail_interactions():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert 'class="hero-meta"' in template
    assert 'class="hero-address-row"' in template
    assert 'data-copy-address' in template
    assert "function selectSite(baseUrl)" in template
    assert "function renderSiteDetail()" in template
    assert "data-site-remark" in template
    assert "data-refresh-site-models" in template
    assert "tr.addEventListener('dblclick'" in template
    assert 'id="f-remark"' in template
    assert 'id="m-remark"' in template
    assert '<label for="f-user">用户标识</label>' in template
    assert "copyText(acc.base_url || '', '地址已复制')" in template
    assert "function copyTextFallback(value)" in template
