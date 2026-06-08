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


def test_classify_checkin_uses_cached_disabled_capability(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
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

    def fail_post(*args, **kwargs):
        raise AssertionError("disabled website should not call check-in endpoint")

    monkeypatch.setattr(app.requests, "post", fail_post)
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


def test_checkin_one_marks_all_accounts_on_same_site_unsupported(tmp_path, monkeypatch):
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
    assert app.get_signin_status_today("8") == UNSUPPORTED


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
    assert checked_accounts == [9]
    assert [result["state"] for result in results] == ["SIGNED_NOW"]
    assert payload["eligible_count"] == 1
    assert payload["skipped_signed"] == 1
    assert payload["skipped_unsupported"] == 2
    assert app.get_signin_status_today("8") == UNSUPPORTED


def test_frontend_disables_unsupported_group_checkin_and_uses_chevron_icon():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "function accountCheckinUnsupported" in template
    assert "function isGroupCheckinUnsupported" in template
    assert "function markAccountSiteCheckinUnsupported" in template
    assert "rowSum.checkinText = '不可签到';" in template
    assert "=== '未签到'" in template
    assert "data.skipped_signed" in template
    assert "不可签到" in template
    assert "fold-icon" in template
    assert "'▶'" not in template
    assert "'▼'" not in template


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
    assert 'id="f-remark"' not in template
    assert 'id="m-remark"' not in template
    assert "new_api_user（可选）" in template
    assert "copyText(acc.base_url || '', '地址已复制')" in template
    assert "function copyTextFallback(value)" in template
