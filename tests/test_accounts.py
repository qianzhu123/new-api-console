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


def test_add_account_modal_is_viewport_bounded_and_scrollable():
    html = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert 'class="modal-card account-modal-card"' in html
    assert ".account-modal-card {" in html
    assert "max-height: calc(100dvh - 32px);" in html
    assert "overflow-y: auto;" in html
    assert "overscroll-behavior: contain;" in html
