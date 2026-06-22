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


def test_normalize_account_preserves_account_remark():
    normalized = app.normalize_account(
        {
            "name": "account",
            "remark": "  account note  ",
            "base_url": "https://example.test",
            "new_api_user": "",
            "session": "session-value-that-is-long-enough",
        }
    )

    assert normalized["remark"] == "account note"


def test_account_remark_is_returned_and_saved_in_account_config(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    write_json(app.CONFIG_PATH, {"base_url": "https://example.test", "accounts": []})

    with app.app.test_client() as client:
        response = client.post(
            "/api/accounts",
            json={
                "name": "remarked account",
                "base_url": "https://example.test",
                "new_api_user": "",
                "session": "session-value-that-is-long-enough",
                "remark": "私人账号备注",
                "enabled": True,
            },
        )

    assert response.status_code == 200
    assert response.get_json()["account"]["remark"] == "私人账号备注"
    config = json.loads(app.CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["accounts"][0]["remark"] == "私人账号备注"


def test_account_remark_is_optional_and_limited_to_500_characters():
    base_payload = {
        "name": "account",
        "base_url": "https://example.test",
        "new_api_user": "",
        "session": "session-value-that-is-long-enough",
        "enabled": True,
    }

    assert app.parse_account_payload(base_payload)["remark"] == ""

    try:
        app.parse_account_payload({**base_payload, "remark": "x" * 501})
    except ValueError as exc:
        assert "500" in str(exc)
    else:
        raise AssertionError("account remark longer than 500 characters should be rejected")


def test_import_update_preserves_existing_account_remark():
    existing = {
        "account_index": 7,
        "name": "account",
        "remark": "保留这条备注",
        "enabled": False,
        "base_url": "https://example.test",
        "new_api_user": "100",
        "session": "old-session-value-that-is-long-enough",
    }
    imported = {
        "name": "account",
        "base_url": "https://example.test",
        "new_api_user": "100",
        "session": "new-session-value-that-is-long-enough",
    }

    merged = app.merge_imported_account(existing, imported)

    assert merged["account_index"] == 7
    assert merged["enabled"] is False
    assert merged["remark"] == "保留这条备注"
    assert merged["session"] == "new-session-value-that-is-long-enough"


def test_refresh_auth_updates_account_by_index_and_runs_status(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(
        app.CONFIG_PATH,
        {
            "base_url": "https://example.test",
            "accounts": [
                {
                    "account_index": 7,
                    "name": "old name",
                    "enabled": True,
                    "remark": "keep remark",
                    "base_url": "https://example.test",
                    "new_api_user": "100",
                    "session": "old-session-value-that-is-long-enough",
                }
            ],
        },
    )
    import_json = {
        "base_url": "https://example.test",
        "storageScan": {
            "localStorage": {
                "items": [
                    {
                        "key": "user",
                        "value": json.dumps({"id": 3134, "username": "new name"}, ensure_ascii=False),
                    }
                ]
            },
            "sessionStorage": {"items": []},
        },
        "cookieEditorCookies": [
            {
                "domain": "example.test",
                "name": "session",
                "value": "new-session-value-that-is-long-enough",
            }
        ],
    }
    seen = {}
    monkeypatch.setattr(app, "fetch_public_status", lambda base_url=None: {"ok": True, "quota_per_unit": 500000})

    def fake_check_status(account, system_status=None):
        seen["account"] = dict(account)
        return {
            "account": account["name"],
            "account_index": account["account_index"],
            "status_state": "VALID",
            "session_valid": True,
            "quota": {"quota": 1000000},
            "system_status": system_status,
        }

    monkeypatch.setattr(app, "check_status", fake_check_status)

    with app.app.test_client() as client:
        response = client.post("/api/accounts/7/refresh-auth", json={"json": import_json})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["account"]["account_index"] == 7
    assert payload["account"]["session"] == "new-session-value-that-is-long-enough"
    assert payload["account"]["new_api_user"] == "3134"
    assert payload["account"]["remark"] == "keep remark"
    assert payload["result"]["session_valid"] is True
    assert seen["account"]["session"] == "new-session-value-that-is-long-enough"
    saved = json.loads(app.CONFIG_PATH.read_text(encoding="utf-8"))
    assert saved["accounts"][0]["session"] == "new-session-value-that-is-long-enough"
    assert app.get_status_cache("7")["session_valid"] is True


def test_refresh_auth_rejects_mismatched_site(tmp_path, monkeypatch):
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
                    "name": "account",
                    "enabled": True,
                    "base_url": "https://example.test",
                    "new_api_user": "100",
                    "session": "old-session-value-that-is-long-enough",
                }
            ]
        },
    )

    with app.app.test_client() as client:
        response = client.post(
            "/api/accounts/7/refresh-auth",
            json={
                "json": {
                    "base_url": "https://other.test",
                    "storageScan": {"localStorage": {"items": []}, "sessionStorage": {"items": []}},
                    "cookieEditorCookies": [{"domain": "other.test", "name": "session", "value": "new-session-value-that-is-long-enough"}],
                }
            },
        )

    assert response.status_code == 400
    assert "不匹配" in response.get_json()["error"]


def test_sync_import_updates_existing_account_by_base_url_and_user_id(tmp_path, monkeypatch):
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
                    "name": "local alias",
                    "enabled": True,
                    "remark": "keep",
                    "base_url": "https://example.test",
                    "new_api_user": "3134",
                    "session": "old-session-value-that-is-long-enough",
                }
            ]
        },
    )
    monkeypatch.setattr(app, "fetch_public_status", lambda base_url=None: {"ok": True})
    monkeypatch.setattr(
        app,
        "check_status",
        lambda account, system_status=None: {
            "account": account["name"],
            "account_index": account["account_index"],
            "status_state": "VALID",
            "session_valid": True,
            "system_status": system_status,
        },
    )

    with app.app.test_client() as client:
        response = client.post(
            "/api/auth/sync-account",
            json={
                "json": {
                    "qiandaoAccount": {
                        "provider": "new-api",
                        "base_url": "https://example.test",
                        "name": "remote name changed",
                        "new_api_user": "3134",
                        "session": "new-session-value-that-is-long-enough",
                    }
                }
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["created"] is False
    assert payload["account"]["account_index"] == 7
    assert payload["account"]["session"] == "new-session-value-that-is-long-enough"
    assert payload["account"]["remark"] == "keep"
    assert payload["result"]["session_valid"] is True
    assert payload["checkin_result"] is None
    saved = json.loads(app.CONFIG_PATH.read_text(encoding="utf-8"))
    assert len(saved["accounts"]) == 1


def test_sync_import_adds_new_account_then_checks_in_and_detects(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(app.CONFIG_PATH, {"accounts": []})
    monkeypatch.setattr(app, "fetch_public_status", lambda base_url=None: {"ok": True})
    monkeypatch.setattr(
        app,
        "classify_checkin",
        lambda account: {
            "account": account["name"],
            "account_index": account["account_index"],
            "state": "SIGNED_NOW",
            "message": "ok",
            "timestamp": app.now_ts(),
        },
    )
    monkeypatch.setattr(
        app,
        "check_status",
        lambda account, system_status=None: {
            "account": account["name"],
            "account_index": account["account_index"],
            "status_state": "VALID",
            "session_valid": True,
            "system_status": system_status,
        },
    )

    with app.app.test_client() as client:
        response = client.post(
            "/api/auth/sync-account",
            json={
                "json": {
                    "qiandaoAccount": {
                        "provider": "new-api",
                        "base_url": "https://example.test",
                        "name": "new account",
                        "new_api_user": "3134",
                        "session": "new-session-value-that-is-long-enough",
                    }
                }
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["created"] is True
    assert payload["account"]["account_index"] == 1
    assert payload["checkin_result"]["state"] == "SIGNED_NOW"
    assert payload["result"]["session_valid"] is True
    assert app.get_signin_status_today("1") == "已签到"
    saved = json.loads(app.CONFIG_PATH.read_text(encoding="utf-8"))
    assert len(saved["accounts"]) == 1


def test_frontend_contains_account_remark_fields_and_detail():
    html = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert 'id="f-remark"' in html
    assert 'id="m-remark"' in html
    assert 'class="site-section account-remark-section"' in html
    assert "data-account-remark" in html
    assert "data-save-account-remark" in html
    assert "function saveAccountRemark()" in html
    assert "data-focus-account-remark" not in html
    assert "remark: fields.remark.value.trim()" in html


def test_frontend_contains_abnormal_auth_refresh_entrypoint():
    html = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "data-refresh-auth-site" in html
    assert "打开网站更新登录" in html
    assert "qiandao-account" in html
    assert "qiandao-auth-refreshed" in html
    assert "/login" in html


def test_extension_contains_refresh_to_local_action():
    manifest = (app.ROOT / "tools" / "qiandao_account_import_extension" / "manifest.json").read_text(encoding="utf-8")
    popup_html = (app.ROOT / "tools" / "qiandao_account_import_extension" / "popup.html").read_text(encoding="utf-8")
    popup_js = (app.ROOT / "tools" / "qiandao_account_import_extension" / "popup.js").read_text(encoding="utf-8")

    assert 'id="updateLocalBtn"' in popup_html
    assert 'id="clearSiteBtn"' not in popup_html
    assert "refreshLocalAccount" in popup_js
    assert "/api/auth/sync-account" in popup_js
    assert "qiandao-account" in popup_js
    assert "qiandao_account" in popup_js
    assert '"background"' not in manifest
    assert '"content_scripts"' not in manifest
    assert '"storage"' not in manifest
    assert "prompt(" not in popup_js


def test_add_account_modal_is_viewport_bounded_and_scrollable():
    html = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert 'class="modal-card account-modal-card"' in html
    assert ".account-modal-card {" in html
    assert "max-height: calc(100dvh - 32px);" in html
    assert "overflow-y: auto;" in html
    assert "overscroll-behavior: contain;" in html
