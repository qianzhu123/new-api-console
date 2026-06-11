import json

import pytest

import app


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def account_config():
    return {
        "accounts": [
            {
                "account_index": 7,
                "name": "token account",
                "enabled": True,
                "base_url": "https://example.test",
                "new_api_user": "3134",
                "session": "session-value-that-is-long-enough",
                "api_keys": [],
            }
        ]
    }


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def isolate_config_and_token_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "TOKEN_CACHE_PATH", tmp_path / "token_cache.json")


def test_token_groups_use_account_credentials(tmp_path, monkeypatch):
    write_json(app.CONFIG_PATH, account_config())
    calls = []

    def fake_get(url, cookies=None, headers=None, timeout=None):
        calls.append({"url": url, "cookies": cookies, "headers": headers, "timeout": timeout})
        return FakeResponse(
            {
                "success": True,
                "data": {
                    "awsq": {"desc": "awsq desc", "ratio": 1.89},
                    "default": {"desc": "default desc", "ratio": 1.5},
                },
            }
        )

    monkeypatch.setattr(app.requests, "get", fake_get)

    with app.app.test_client() as client:
        response = client.get("/api/accounts/7/token-groups")

    assert response.status_code == 200
    assert response.get_json()["groups"] == [
        {"id": "awsq", "name": "awsq desc", "desc": "awsq desc", "ratio": 1.89, "platform": None},
        {"id": "default", "name": "default desc", "desc": "default desc", "ratio": 1.5, "platform": None},
    ]
    assert calls[0]["url"] == "https://example.test/api/user/self/groups"
    assert calls[0]["cookies"] == {"session": "session-value-that-is-long-enough"}
    assert calls[0]["headers"]["new-api-user"] == "3134"
    assert calls[0]["headers"]["referer"] == "https://example.test/console/token"


def test_token_groups_use_local_cache_without_remote_request(monkeypatch):
    cfg = account_config()
    account = cfg["accounts"][0]
    write_json(app.CONFIG_PATH, cfg)
    write_json(
        app.TOKEN_CACHE_PATH,
        {
            "accounts": {
                app.token_cache_key(account): {
                    "groups": [{"id": "cached", "desc": "cached desc", "ratio": 1.2}],
                    "tokens": [],
                }
            }
        },
    )

    def fail_get(*args, **kwargs):
        raise AssertionError("remote groups should not be requested when cache exists")

    monkeypatch.setattr(app.requests, "get", fail_get)

    with app.app.test_client() as client:
        response = client.get("/api/accounts/7/token-groups")

    assert response.status_code == 200
    assert response.get_json()["source"] == "cache"
    assert response.get_json()["groups"] == [{"id": "cached", "desc": "cached desc", "ratio": 1.2}]


def test_token_groups_force_refresh_updates_local_cache(monkeypatch):
    cfg = account_config()
    account = cfg["accounts"][0]
    write_json(app.CONFIG_PATH, cfg)
    write_json(
        app.TOKEN_CACHE_PATH,
        {"accounts": {app.token_cache_key(account): {"groups": [{"id": "old", "desc": "", "ratio": 1}]}}},
    )
    calls = []

    def fake_get(url, cookies=None, headers=None, timeout=None):
        calls.append(url)
        return FakeResponse({"success": True, "data": {"fresh": {"desc": "fresh desc", "ratio": 2}}})

    monkeypatch.setattr(app.requests, "get", fake_get)

    with app.app.test_client() as client:
        response = client.get("/api/accounts/7/token-groups?force=1")

    assert response.status_code == 200
    assert response.get_json()["source"] == "remote"
    assert response.get_json()["groups"] == [
        {"id": "fresh", "name": "fresh desc", "desc": "fresh desc", "ratio": 2, "platform": None}
    ]
    assert calls == ["https://example.test/api/user/self/groups"]
    cached = json.loads(app.TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    assert cached["accounts"][app.token_cache_key(account)]["groups"][0]["id"] == "fresh"


def test_create_token_posts_selected_group_and_name(tmp_path, monkeypatch):
    write_json(app.CONFIG_PATH, account_config())
    calls = []

    def fake_post(url, cookies=None, headers=None, json=None, timeout=None):
        calls.append({"url": url, "cookies": cookies, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse({"success": True, "message": "", "data": {"key": "sk-created"}})

    monkeypatch.setattr(app.requests, "post", fake_post)

    with app.app.test_client() as client:
        response = client.post("/api/accounts/7/tokens", json={"name": "daily", "group": "awsq"})

    assert response.status_code == 200
    assert response.get_json()["token"]["key"] == "sk-created"
    assert calls[0]["url"] == "https://example.test/api/token/"
    assert calls[0]["json"] == {
        "remain_quota": 0,
        "remain_amount": 0,
        "expired_time": -1,
        "unlimited_quota": True,
        "model_limits_enabled": False,
        "model_limits": "",
        "cross_group_retry": False,
        "name": "daily",
        "group": "awsq",
        "allow_ips": "",
    }
    cached = json.loads(app.TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    token = cached["accounts"][app.token_cache_key(account_config()["accounts"][0])]["tokens"][0]
    assert token["name"] == "daily"
    assert token["group"] == "awsq"
    assert token["key"] == ""


def test_create_token_group_error_refreshes_group_cache(monkeypatch):
    write_json(app.CONFIG_PATH, account_config())
    calls = []

    def fake_post(url, cookies=None, headers=None, json=None, timeout=None):
        calls.append(("post", url))
        return FakeResponse({"success": False, "message": "分组不存在"})

    def fake_get(url, cookies=None, headers=None, timeout=None):
        calls.append(("get", url))
        return FakeResponse({"success": True, "data": {"new-group": {"desc": "new desc", "ratio": 3}}})

    monkeypatch.setattr(app.requests, "post", fake_post)
    monkeypatch.setattr(app.requests, "get", fake_get)

    with app.app.test_client() as client:
        response = client.post("/api/accounts/7/tokens", json={"name": "daily", "group": "gone"})

    assert response.status_code == 502
    payload = response.get_json()
    assert payload["groups_refreshed"] is True
    assert payload["groups"] == [
        {"id": "new-group", "name": "new desc", "desc": "new desc", "ratio": 3, "platform": None}
    ]
    assert calls == [
        ("post", "https://example.test/api/token/"),
        ("get", "https://example.test/api/user/self/groups"),
    ]


def test_list_tokens_normalizes_records(tmp_path, monkeypatch):
    write_json(app.CONFIG_PATH, account_config())

    def fake_get(url, cookies=None, headers=None, timeout=None):
        return FakeResponse(
            {
                "success": True,
                "data": {
                    "items": [
                        {"id": 4898, "name": "daily", "key": "sk-token", "group": "awsq"},
                        {"id": 4899, "name": "backup", "token": "backup", "group": "default"},
                    ]
                },
            }
        )

    monkeypatch.setattr(app.requests, "get", fake_get)

    with app.app.test_client() as client:
        response = client.get("/api/accounts/7/tokens")

    assert response.status_code == 200
    assert response.get_json()["tokens"] == [
        {"id": 4898, "name": "daily", "key": "sk-token", "group": "awsq"},
        {"id": 4899, "name": "backup", "key": "sk-backup", "group": "default"},
    ]
    cached = json.loads(app.TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    assert cached["accounts"][app.token_cache_key(account_config()["accounts"][0])]["tokens"][0]["key"] == ""


def test_list_tokens_uses_local_cache_without_remote_request(monkeypatch):
    cfg = account_config()
    account = cfg["accounts"][0]
    write_json(app.CONFIG_PATH, cfg)
    write_json(
        app.TOKEN_CACHE_PATH,
        {
            "accounts": {
                app.token_cache_key(account): {
                    "groups": [],
                    "tokens": [{"id": 1, "name": "cached-token", "key": "", "group": "cached"}],
                }
            }
        },
    )

    def fail_get(*args, **kwargs):
        raise AssertionError("remote tokens should not be requested when cache exists")

    monkeypatch.setattr(app.requests, "get", fail_get)

    with app.app.test_client() as client:
        response = client.get("/api/accounts/7/tokens")

    assert response.status_code == 200
    assert response.get_json()["source"] == "cache"
    assert response.get_json()["tokens"] == [{"id": 1, "name": "cached-token", "key": "", "group": "cached"}]


def test_empty_cached_token_list_is_not_refetched(monkeypatch):
    cfg = account_config()
    account = cfg["accounts"][0]
    write_json(app.CONFIG_PATH, cfg)
    write_json(app.TOKEN_CACHE_PATH, {"accounts": {app.token_cache_key(account): {"tokens": []}}})

    def fail_get(*args, **kwargs):
        raise AssertionError("empty cached token list should still be treated as cached")

    monkeypatch.setattr(app.requests, "get", fail_get)

    with app.app.test_client() as client:
        response = client.get("/api/accounts/7/tokens")

    assert response.status_code == 200
    assert response.get_json()["source"] == "cache"
    assert response.get_json()["tokens"] == []


def test_delete_token_uses_account_credentials(tmp_path, monkeypatch):
    cfg = account_config()
    account = cfg["accounts"][0]
    write_json(app.CONFIG_PATH, cfg)
    write_json(
        app.TOKEN_CACHE_PATH,
        {
            "accounts": {
                app.token_cache_key(account): {
                    "tokens": [
                        {"id": 4898, "name": "delete-me", "key": "", "group": "awsq"},
                        {"id": 4899, "name": "keep-me", "key": "", "group": "awsq"},
                    ]
                }
            }
        },
    )
    calls = []

    def fake_delete(url, cookies=None, headers=None, timeout=None):
        calls.append({"url": url, "cookies": cookies, "headers": headers, "timeout": timeout})
        return FakeResponse({"success": True, "message": ""})

    monkeypatch.setattr(app.requests, "delete", fake_delete)

    with app.app.test_client() as client:
        response = client.delete("/api/accounts/7/tokens/4898")

    assert response.status_code == 200
    assert calls[0]["url"] == "https://example.test/api/token/4898"
    assert calls[0]["cookies"] == {"session": "session-value-that-is-long-enough"}
    cached = json.loads(app.TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    assert [item["id"] for item in cached["accounts"][app.token_cache_key(account)]["tokens"]] == [4899]


def test_reveal_token_key_posts_to_key_endpoint(tmp_path, monkeypatch):
    write_json(app.CONFIG_PATH, account_config())
    calls = []

    def fake_post(url, cookies=None, headers=None, json=None, timeout=None):
        calls.append({"url": url, "cookies": cookies, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse({"success": True, "message": "", "data": {"key": "full-token-key"}})

    monkeypatch.setattr(app.requests, "post", fake_post)

    with app.app.test_client() as client:
        response = client.post("/api/accounts/7/tokens/4899/key", json={})

    assert response.status_code == 200
    assert response.get_json()["key"] == "sk-full-token-key"
    assert calls[0]["url"] == "https://example.test/api/token/4899/key"
    assert calls[0]["cookies"] == {"session": "session-value-that-is-long-enough"}
    assert calls[0]["headers"]["new-api-user"] == "3134"


def test_token_key_prefix_is_not_duplicated():
    assert app.format_token_key("abc123") == "sk-abc123"
    assert app.format_token_key("sk-abc123") == "sk-abc123"
    assert app.format_token_key("sk-abcd********wxyz") == ""
    assert app.format_token_key("") == ""


def test_data_layout_creates_empty_token_cache():
    app.ensure_data_layout()

    assert app.TOKEN_CACHE_PATH.exists()
    assert json.loads(app.TOKEN_CACHE_PATH.read_text(encoding="utf-8")) == {"accounts": {}}


def test_frontend_contains_token_panel_and_no_api_key_editor():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "添加令牌" in template
    assert "token-groups" in template
    assert "token-modal" in template
    assert "confirm-modal" in template
    assert "showConfirmDialog" in template
    assert "confirm(" not in template
    assert "formatTokenKey" in template
    assert "isMaskedTokenKey" in template
    assert "revealTokenKey" in template
    assert "revealTokenKeysInBackground" in template
    assert "loadTokenGroups" in template
    assert "完整令牌未展开" in template
    assert "function tokenGroupsReady" in template
    assert "el.btnTokenModalSave.disabled = !tokenGroupsReady(key);" in template
    assert "请等待分组加载完成后再创建" in template
    assert "API Key（每行一个）" not in template


def test_frontend_normalizes_cny_currency_symbol():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "['CNY', 'RMB', 'CNH'].includes(displayType)" in template
    assert "return '￥';" in template
    assert "customSymbol !== '¤'" in template


def test_frontend_create_token_closes_modal_before_network_request():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    create_start = template.index("async function createTokenForAccount")
    close_index = template.index("closeTokenModal();", create_start)
    api_index = template.index("const data = await api", create_start)

    assert close_index < api_index


def test_frontend_token_scroll_and_row_actions_are_constrained():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "overscroll-behavior: contain;" in template
    assert "--action-col: 168px;" in template
    assert ".grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(480px, .9fr); gap: 12px;" in template
    assert ".row-actions { display: flex; gap: 6px;" in template
    assert ".row-actions { justify-content: flex-start;" in template
    assert ".group-box { display:grid;" in template
    assert "min-height: 94px;" in template
    assert "function fitMetricValues()" in template
    assert "node.scrollWidth > node.clientWidth" in template
