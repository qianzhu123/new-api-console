import json

import pytest

import app


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def patch_storage_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    monkeypatch.setattr(app, "TOKEN_CACHE_PATH", tmp_path / "token_cache.json")
    monkeypatch.setattr(app, "HISTORY_PATH", tmp_path / "quota_history.json")


def credless_extension_import_json(title="小学生公益站", host="xxs.example"):
    return {
        "format": "qiandao-account-import",
        "version": 4,
        "collector": "chrome-extension",
        "compatibility": ["new-api", "sub2api"],
        "origin": f"https://{host}",
        "base_url": f"https://{host}",
        "page": f"https://{host}/dashboard/overview",
        "title": title,
        "time": "2026-09-14T12:26:38.354Z",
        "storageScan": {
            "localStorage": {
                "items": [
                    {"key": "i18nextLng", "value": "zhCN"},
                    {"key": "app:rev", "value": "rv.0000.2k6e8r7p"},
                ],
                "matchedCount": 2,
                "storageName": "localStorage",
            },
            "sessionStorage": {"items": [], "matchedCount": 0, "storageName": "sessionStorage"},
        },
        "cookieEditorCookies": [
            {"domain": host, "name": "new_api_has_session", "path": "/", "value": "1"}
        ],
        "cookies": [
            {"domain": host, "name": "new_api_has_session", "path": "/", "value": "1"}
        ],
        "detected": {
            "provider": "未识别",
            "name": "",
            "userId": "",
            "sessionField": "未找到",
            "hasSession": False,
            "account": None,
        },
        "apiScan": {"matchedCount": 0, "matched": [], "allResultsSummary": []},
        "qiandaoAccount": None,
    }


def test_credless_import_falls_back_to_unsupported_placeholder():
    account, notes = app.build_auth_account_from_import_json(
        credless_extension_import_json()
    )

    assert account["provider"] == "unsupported"
    assert account["name"] == "小学生公益站"
    assert account["base_url"] == "https://xxs.example"
    assert account["session"] == ""
    assert any("new-api 特征" in note for note in notes)


def test_credless_import_without_title_uses_host():
    import_json = credless_extension_import_json(title="")
    account, _ = app.build_auth_account_from_import_json(import_json)

    assert account["provider"] == "unsupported"
    assert account["name"] == "xxs.example"


def test_import_route_returns_unsupported_account_for_modal_confirmation(tmp_path, monkeypatch):
    patch_storage_paths(tmp_path, monkeypatch)
    write_json(app.CONFIG_PATH, {"base_url": "https://xxs.example", "accounts": []})

    with app.app.test_client() as client:
        response = client.post(
            "/api/auth/import-json",
            json={"json": json.dumps(credless_extension_import_json(), ensure_ascii=False)},
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["updated"] is False
    assert data["account"]["provider"] == "unsupported"
    assert data["account"]["name"] == "小学生公益站"
    # 未确认创建前不写本地配置
    config = json.loads(app.CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["accounts"] == []


def test_import_route_keeps_existing_account_when_placeholder_matches(tmp_path, monkeypatch):
    patch_storage_paths(tmp_path, monkeypatch)
    existing = {
        "account_index": 5,
        "name": "小学生公益站",
        "provider": "new-api",
        "base_url": "https://xxs.example",
        "new_api_user": "9",
        "session": "session-value-that-is-long-enough",
        "cookie": "",
        "remark": "keep",
        "enabled": True,
        "api_keys": [],
    }
    write_json(app.CONFIG_PATH, {"base_url": "https://xxs.example", "accounts": [existing]})

    with app.app.test_client() as client:
        response = client.post(
            "/api/auth/import-json",
            json={"json": json.dumps(credless_extension_import_json(), ensure_ascii=False)},
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["account"]["session"] == "session-value-that-is-long-enough"
    assert any("已保留原账号信息" in note for note in data["notes"])
    config = json.loads(app.CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["accounts"][0]["session"] == "session-value-that-is-long-enough"


def test_merge_imported_account_rejects_placeholder_over_real_account():
    existing = {
        "account_index": 5,
        "name": "小学生公益站",
        "provider": "new-api",
        "base_url": "https://xxs.example",
        "new_api_user": "9",
        "session": "session-value-that-is-long-enough",
        "cookie": "",
        "enabled": True,
        "remark": "",
        "api_keys": [],
    }
    placeholder = {
        "provider": "unsupported",
        "base_url": "https://xxs.example",
        "name": "小学生公益站",
        "new_api_user": "",
        "session": "",
        "cookie": "",
    }

    with pytest.raises(ValueError):
        app.merge_imported_account(existing, placeholder)


def test_merge_imported_account_preserves_credentials_for_identity_only_import():
    existing = {
        "account_index": 5,
        "name": "老账号",
        "provider": "new-api",
        "base_url": "https://xxs.example",
        "new_api_user": "9",
        "session": "session-value-that-is-long-enough",
        "cookie": "a=1",
        "enabled": True,
        "remark": "",
        "api_keys": [],
    }
    imported = {
        "provider": "new-api",
        "base_url": "https://xxs.example",
        "name": "老账号",
        "new_api_user": "",
        "session": "",
        "cookie": "",
    }

    merged = app.merge_imported_account(existing, imported)

    assert merged["session"] == "session-value-that-is-long-enough"
    assert merged["cookie"] == "a=1"
    assert merged["new_api_user"] == "9"


def test_classify_checkin_unsupported_provider_needs_no_network(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(app.SITE_INFO_PATH, {"sites": {}})

    def fail_request(*args, **kwargs):
        raise AssertionError("network request should not happen")

    monkeypatch.setattr(app.requests, "post", fail_request)
    monkeypatch.setattr(app.requests, "get", fail_request)

    result = app.classify_checkin(
        {
            "account_index": 12,
            "name": "placeholder",
            "provider": "unsupported",
            "base_url": "https://xxs.example",
            "new_api_user": "",
            "session": "",
        }
    )

    assert result["state"] == "UNSUPPORTED"
    assert "不可导入" in result["message"]


def test_check_status_unsupported_provider_reports_invalid_session(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(app.SITE_INFO_PATH, {"sites": {}})

    def fail_request(*args, **kwargs):
        raise AssertionError("network request should not happen")

    monkeypatch.setattr(app.requests, "post", fail_request)
    monkeypatch.setattr(app.requests, "get", fail_request)

    result = app.check_status(
        {
            "account_index": 12,
            "name": "placeholder",
            "provider": "unsupported",
            "base_url": "https://xxs.example",
            "new_api_user": "",
            "session": "",
        }
    )

    assert result["status_state"] == "INVALID_SESSION"
    assert result["session_valid"] is False
    assert "不可导入" in result["api_error"]


def test_add_account_accepts_unsupported_provider(tmp_path, monkeypatch):
    patch_storage_paths(tmp_path, monkeypatch)
    write_json(app.CONFIG_PATH, {"base_url": "https://xxs.example", "accounts": []})

    with app.app.test_client() as client:
        response = client.post(
            "/api/accounts",
            json={
                "name": "小学生公益站",
                "base_url": "https://xxs.example",
                "provider": "unsupported",
                "new_api_user": "",
                "session": "",
                "enabled": True,
            },
        )

    assert response.status_code == 200
    account = response.get_json()["account"]
    assert account["provider"] == "unsupported"
    assert account["session"] == ""


def test_unsupported_provider_token_fetch_returns_empty_readonly():
    account = {
        "account_index": 3,
        "name": "placeholder",
        "provider": "unsupported",
        "base_url": "https://xxs.example",
        "session": "",
        "cookie": "",
    }

    tokens, payload = app.fetch_remote_tokens(account)
    groups, groups_payload = app.fetch_remote_token_groups(account)

    assert tokens == []
    assert groups == []
    assert payload.get("unsupported") is True
    assert groups_payload.get("unsupported") is True


def test_credless_import_with_refresh_cookie_notes_captured_credential():
    import_json = credless_extension_import_json()
    import_json["cookieEditorCookies"] = [
        {"domain": "xxs.example", "name": "new_api_refresh", "path": "/api/user/auth", "value": "refresh-token-value"}
    ]
    import_json["cookies"] = import_json["cookieEditorCookies"]

    account, notes = app.build_auth_account_from_import_json(import_json)

    assert account["provider"] == "unsupported"
    assert account["session"] == ""
    assert any("new_api_refresh" in note for note in notes)


def test_unsupported_account_with_identity_imports_real_name_and_user():
    import_json = credless_extension_import_json()
    import_json["qiandaoAccount"] = {
        "provider": "unsupported",
        "base_url": "https://xxs.example",
        "name": "gererh",
        "new_api_user": "574",
        "session": "",
        "cookie": "new_api_refresh=token-value",
        "identity": {"id": 574, "username": "gererh", "display_name": "gererh"},
    }

    account, notes = app.build_auth_account_from_import_json(import_json)

    assert account["provider"] == "unsupported"
    assert account["name"] == "gererh"
    assert account["new_api_user"] == "574"
    assert account["cookie"] == "new_api_refresh=token-value"
    assert account["identity"]["id"] == 574
    assert any("用户 ID 574" in note for note in notes)


def test_unsupported_account_falls_back_to_site_title_without_identity():
    import_json = credless_extension_import_json()
    import_json["qiandaoAccount"] = {"provider": "unsupported", "base_url": "https://xxs.example", "name": "", "session": ""}

    account, notes = app.build_auth_account_from_import_json(import_json)

    assert account["provider"] == "unsupported"
    assert account["name"] == "小学生公益站"
    assert account["new_api_user"] == ""
    assert not any("用户 ID" in note for note in notes)


def test_credless_import_honors_extension_new_api_detection():
    import_json = credless_extension_import_json()
    import_json["detected"]["provider"] = "new-api（未采集到凭据）"
    import_json["cookieEditorCookies"] = []
    import_json["cookies"] = []
    import_json["storageScan"]["localStorage"]["items"] = [{"key": "i18nextLng", "value": "zhCN"}]

    account, notes = app.build_auth_account_from_import_json(import_json)

    assert account["provider"] == "unsupported"
    assert any("new-api 特征" in note for note in notes)


def test_sync_route_creates_unsupported_record_without_background_detection(tmp_path, monkeypatch):
    patch_storage_paths(tmp_path, monkeypatch)
    write_json(app.CONFIG_PATH, {"base_url": "https://xxs.example", "accounts": []})
    scheduled = []
    monkeypatch.setattr(
        app,
        "schedule_synced_account_background_tasks",
        lambda account, created: scheduled.append((account.get("name"), created)),
    )

    import_json = credless_extension_import_json()
    import_json["qiandaoAccount"] = {
        "provider": "unsupported",
        "base_url": "https://xxs.example",
        "name": "qianzhu",
        "new_api_user": "574",
        "session": "",
        "cookie": "new_api_refresh=token-value",
        "identity": {"id": 574, "username": "qianzhu"},
    }

    with app.app.test_client() as client:
        response = client.post(
            "/api/auth/sync-account",
            json={"json": json.dumps(import_json, ensure_ascii=False)},
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["created"] is True
    assert data["detection_pending"] is False
    assert data["account"]["provider"] == "unsupported"
    assert data["account"]["name"] == "qianzhu"
    assert data["account"]["new_api_user"] == "574"
    assert scheduled == []
    config = json.loads(app.CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["accounts"][0]["name"] == "qianzhu"
    assert config["accounts"][0]["provider"] == "unsupported"


def test_sync_route_updates_existing_unsupported_record_in_place(tmp_path, monkeypatch):
    patch_storage_paths(tmp_path, monkeypatch)
    existing = {
        "account_index": 3,
        "name": "qianzhu",
        "provider": "unsupported",
        "base_url": "https://xxs.example",
        "new_api_user": "574",
        "session": "",
        "cookie": "new_api_refresh=old-value",
        "remark": "keep",
        "enabled": True,
        "api_keys": [],
    }
    write_json(app.CONFIG_PATH, {"base_url": "https://xxs.example", "accounts": [existing]})
    monkeypatch.setattr(app, "schedule_synced_account_background_tasks", lambda *a, **k: None)

    import_json = credless_extension_import_json()
    import_json["qiandaoAccount"] = {
        "provider": "unsupported",
        "base_url": "https://xxs.example",
        "name": "qianzhu",
        "new_api_user": "574",
        "session": "",
        "cookie": "new_api_refresh=new-value",
        "identity": {"id": 574, "username": "qianzhu"},
    }

    with app.app.test_client() as client:
        response = client.post(
            "/api/auth/sync-account",
            json={"json": json.dumps(import_json, ensure_ascii=False)},
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data["created"] is False
    assert data["detection_pending"] is False
    config = json.loads(app.CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["accounts"][0]["account_index"] == 3
    assert config["accounts"][0]["cookie"] == "new_api_refresh=new-value"
    assert config["accounts"][0]["remark"] == "keep"


def test_frontend_supports_unsupported_provider_option():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "{ value: 'unsupported', label: '不可导入（仅记录）' }" in template
    assert "if (provider === 'unsupported') return '不可导入';" in template
    assert "requireSession && payload.provider !== 'unsupported'" in template
    assert "normalizeProvider(acc?.provider) === 'unsupported') return true" in template


def test_extension_recognizes_new_api_signature_without_credentials():
    popup_js = (
        app.ROOT / "tools" / "qiandao_account_import_extension" / "popup.js"
    ).read_text(encoding="utf-8")

    assert "function hasNewApiSignature" in popup_js
    assert "function extractNewApiRefreshUser" in popup_js
    assert "'new_api_has_session'" in popup_js
    assert "new_api_refresh" in popup_js
    assert "/api/user/auth/refresh" in popup_js
    assert "new-api（JWT 刷新凭据）" in popup_js
    assert "new-api（未采集到凭据）" in popup_js
    assert "!summary.hasSession && !summary.account" in popup_js
    assert "已保存不可导入记录" in popup_js
    assert "不可导入" in popup_js
