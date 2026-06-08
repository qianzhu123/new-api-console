import json
import os
import pathlib
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, render_template, request


ROOT = pathlib.Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LEGACY_CONFIG_PATH = ROOT / "session.json"
LEGACY_HISTORY_PATH = ROOT / "quota_history.json"
LEGACY_SIGNIN_PATH = ROOT / "signin_status.json"
CONFIG_PATH = DATA_DIR / "session.json"
HISTORY_PATH = DATA_DIR / "quota_history.json"
SIGNIN_PATH = DATA_DIR / "signin_status.json"
STATUS_CACHE_PATH = DATA_DIR / "status_cache.json"
TOKEN_CACHE_PATH = DATA_DIR / "token_cache.json"
SITE_INFO_PATH = DATA_DIR / "site_info.json"
DEFAULT_BASE_URL = "https://www.new-api.com"
BASE_URL_ENV_KEY = "NEW_API_BASE_URL"
CHECKIN_PATH = "/api/user/checkin"
SELF_PATH = "/api/user/self"
STATUS_PATH = "/api/status"
TOKEN_GROUPS_PATH = "/api/user/self/groups"
TOKEN_PATH = "/api/token/"
MODELS_PATH = "/api/user/models"
SUB2API_SELF_PATH = "/api/v1/auth/me"
SUB2API_GROUPS_PATH = "/api/v1/groups/available"
SUB2API_KEYS_PATH = "/api/v1/keys"
TIMEOUT_SECONDS = 20
def parse_positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or str(default))
    except ValueError:
        return default
    return max(1, value)


MAX_BATCH_WORKERS = parse_positive_int_env("QIANDAO_MAX_BATCH_WORKERS", 8)
DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "cache-control": "no-store",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "accept-language": "zh-CN,zh;q=0.9",
    "priority": "u=1, i",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
}
AUTH_KEYWORDS = [
    "unauthorized",
    "not login",
    "login",
    "expired",
    "invalid",
    "forbidden",
]
VERIFY_KEYWORDS = ["turnstile", "captcha", "verification"]
CHECKIN_UNSUPPORTED_KEYWORDS = [
    "不支持签到",
    "签到未开启",
    "未开启签到",
    "签到功能未开启",
    "签到未启用",
    "checkin disabled",
    "check-in disabled",
    "checkin is disabled",
    "check-in is disabled",
    "checkin not supported",
    "check-in not supported",
]


app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
config_lock = threading.RLock()



def get_batch_worker_count(item_count: int) -> int:
    if item_count <= 0:
        return 1
    return max(1, min(MAX_BATCH_WORKERS, item_count))


def run_batch_parallel(items: list[Any], worker: Callable[[Any], Any]) -> list[Any]:
    worker_count = get_batch_worker_count(len(items))
    if worker_count <= 1:
        return [worker(item) for item in items]
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(worker, items))


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def ensure_data_layout() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    legacy_to_new = [
        (LEGACY_CONFIG_PATH, CONFIG_PATH),
        (LEGACY_HISTORY_PATH, HISTORY_PATH),
        (LEGACY_SIGNIN_PATH, SIGNIN_PATH),
    ]
    for legacy_path, new_path in legacy_to_new:
        if new_path.exists() or not legacy_path.exists():
            continue
        os.replace(legacy_path, new_path)
    if not TOKEN_CACHE_PATH.exists():
        atomic_save_json(TOKEN_CACHE_PATH, {"accounts": {}})
    if not SITE_INFO_PATH.exists():
        atomic_save_json(SITE_INFO_PATH, {"sites": {}})


def normalize_base_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return DEFAULT_BASE_URL
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value.rstrip("/")


def get_config_base_url_value() -> str | None:
    ensure_data_layout()
    if not CONFIG_PATH.exists():
        return None
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("base_url")
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    return raw if raw else None


def get_base_url() -> str:
    env_value = str(os.getenv(BASE_URL_ENV_KEY, "") or "").strip()
    if env_value:
        return normalize_base_url(env_value)
    config_value = get_config_base_url_value()
    if config_value:
        return normalize_base_url(config_value)
    return DEFAULT_BASE_URL


def collect_known_base_urls(config: dict[str, Any] | None = None) -> list[str]:
    cfg = config if isinstance(config, dict) else load_config()
    values: list[str] = []

    def add_one(raw: Any) -> None:
        raw_value = str(raw or "").strip()
        if not raw_value:
            return
        normalized = normalize_base_url(raw_value)
        if normalized not in values:
            values.append(normalized)

    add_one(cfg.get("base_url") if isinstance(cfg, dict) else None)
    for account in cfg.get("accounts", []) if isinstance(cfg, dict) else []:
        if isinstance(account, dict):
            add_one(account.get("base_url"))

    try:
        site_store = load_site_info()
        sites = site_store.get("sites") if isinstance(site_store, dict) else {}
        if isinstance(sites, dict):
            for site_url in sites.keys():
                add_one(site_url)
    except Exception:
        pass

    add_one(get_base_url())
    return values


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def yesterday_str() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def parse_api_keys(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        keys = [str(x).strip() for x in raw]
    elif isinstance(raw, str):
        keys = [line.strip() for line in raw.splitlines()]
    else:
        keys = [str(raw).strip()]
    return [k for k in keys if k]


def preferred_account_name(identity: Any, fallback: Any = "") -> str:
    """Prefer the real account/display name over email for account labels."""
    if isinstance(identity, dict):
        for key in ("display_name", "username", "name", "nickname", "email", "id"):
            value = str(identity.get(key) or "").strip()
            if value:
                return value
    return str(fallback or "").strip()


def is_email_like(value: Any) -> bool:
    text = str(value or "").strip()
    return "@" in text and "." in text.split("@", 1)[-1]


def merge_identity_for_import(primary: Any, storage_identity: Any) -> dict[str, Any]:
    """Merge API/plugin identity with storage identity.

    Some new-api sites return only email from API, while localStorage.user contains
    the real visible account name in display_name/username.  Storage values are
    preferred for display fields, while missing fields from the API are retained.
    """
    merged: dict[str, Any] = {}
    if isinstance(primary, dict):
        merged.update(primary)
    if isinstance(storage_identity, dict):
        for key, value in storage_identity.items():
            if value is None:
                continue
            value_text = str(value).strip() if not isinstance(value, (dict, list)) else value
            if value_text == "":
                continue
            # For display fields, localStorage is usually closer to what the user sees.
            if key in ("display_name", "username", "name", "nickname"):
                merged[key] = value
            elif key not in merged or str(merged.get(key) or "").strip() == "":
                merged[key] = value
    return merged


def validate_account_fields(
    name: str,
    base_url: str,
    new_api_user: str,
    session_value: str,
    api_keys: list[str],
    require_name: bool = True,
    provider: str = "new-api",
) -> None:
    if require_name and not name:
        raise ValueError("name is required")

    if not base_url:
        raise ValueError("base_url is required")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")

    if provider not in ("new-api", "sub2api"):
        raise ValueError("provider must be new-api or sub2api")

    if provider == "new-api" and new_api_user and not new_api_user.isdigit():
        raise ValueError("new_api_user must be numeric")

    if not session_value:
        raise ValueError("session is required")
    if any(ch.isspace() for ch in session_value):
        raise ValueError("session must not contain whitespace")
    min_session_len = 20 if provider == "new-api" else 30
    if len(session_value) < min_session_len:
        raise ValueError("session looks too short")

    for key in api_keys:
        if any(ch.isspace() for ch in key):
            raise ValueError("api_keys must not contain whitespace")
        if len(key) < 10:
            raise ValueError("api_keys entry looks too short")


def normalize_account(account: dict[str, Any], fallback_base_url: str | None = None) -> dict[str, Any]:
    normalized = dict(account)
    normalized.pop("remark", None)
    account_base = str(normalized.get("base_url") or "").strip()
    if account_base:
        normalized["base_url"] = normalize_base_url(account_base)
    elif fallback_base_url:
        normalized["base_url"] = normalize_base_url(fallback_base_url)
    else:
        normalized["base_url"] = DEFAULT_BASE_URL
    normalized["name"] = str(normalized.get("name") or "").strip()
    normalized["enabled"] = bool(normalized.get("enabled", True))
    provider = str(normalized.get("provider") or "new-api").strip().lower()
    if provider not in ("new-api", "sub2api"):
        provider = "new-api"
    normalized["provider"] = provider
    normalized["new_api_user"] = str(normalized.get("new_api_user") or "").strip()
    normalized["session"] = str(normalized.get("session") or normalized.get("access_token") or "").strip()
    normalized["cookie"] = str(normalized.get("cookie") or "").strip()
    normalized["api_keys"] = parse_api_keys(normalized.get("api_keys"))
    return normalized


def normalize_config(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    normalized = dict(data)
    raw_accounts = data.get("accounts", [])
    changed = False
    top_level_base_url = normalize_base_url(str(data.get("base_url") or "").strip() or DEFAULT_BASE_URL)

    if not isinstance(raw_accounts, list):
        raw_accounts = []
        changed = True

    existing_ids: list[int] = []
    for item in raw_accounts:
        if not isinstance(item, dict):
            continue
        try:
            account_id = int(item.get("account_index", 0))
        except (TypeError, ValueError):
            account_id = 0
        if account_id > 0:
            existing_ids.append(account_id)
    next_account_id = (max(existing_ids) + 1) if existing_ids else 1
    used_account_ids: set[int] = set()

    new_accounts: list[dict[str, Any]] = []
    for item in raw_accounts:
        if not isinstance(item, dict):
            changed = True
            continue
        n = normalize_account(item, fallback_base_url=top_level_base_url)
        try:
            account_id = int(n.get("account_index", 0))
        except (TypeError, ValueError):
            account_id = 0
        if account_id <= 0 or account_id in used_account_ids:
            while next_account_id in used_account_ids:
                next_account_id += 1
            account_id = next_account_id
            next_account_id += 1
            changed = True
        n["account_index"] = account_id
        used_account_ids.add(account_id)
        if item != n:
            changed = True
        new_accounts.append(n)

    if normalized.get("base_url") != top_level_base_url:
        changed = True
    normalized["base_url"] = top_level_base_url

    if normalized.get("accounts") != new_accounts:
        changed = True
    normalized["accounts"] = new_accounts

    return normalized, changed


def load_config_raw() -> dict[str, Any]:
    ensure_data_layout()
    if not CONFIG_PATH.exists():
        return {"accounts": []}

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        return {"accounts": []}

    return data


def atomic_save_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as tf:
            temp_file = pathlib.Path(tf.name)
            json.dump(data, tf, ensure_ascii=False, indent=2)
            tf.flush()
            os.fsync(tf.fileno())

        os.replace(temp_file, path)
    finally:
        if temp_file and temp_file.exists():
            temp_file.unlink(missing_ok=True)


def load_config(normalize_and_persist: bool = True) -> dict[str, Any]:
    with config_lock:
        raw = load_config_raw()
        normalized, changed = normalize_config(raw)
        if normalize_and_persist and changed:
            atomic_save_json(CONFIG_PATH, normalized)
        return normalized


def save_config(data: dict[str, Any]) -> dict[str, Any]:
    with config_lock:
        normalized, _ = normalize_config(data)
        atomic_save_json(CONFIG_PATH, normalized)
        return normalized


def load_history() -> dict[str, Any]:
    ensure_data_layout()
    if not HISTORY_PATH.exists():
        return {"accounts": {}}
    try:
        with HISTORY_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"accounts": {}}
        accounts = data.get("accounts")
        if not isinstance(accounts, dict):
            data["accounts"] = {}
        return data
    except Exception:
        return {"accounts": {}}


def save_history(data: dict[str, Any]) -> None:
    with config_lock:
        atomic_save_json(HISTORY_PATH, data)


def _normalize_signin_store(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False
    today = today_str()
    normalized = {"date": today, "accounts": {}}

    if isinstance(data, dict):
        src_date = str(data.get("date") or "")
        src_accounts = data.get("accounts")
        if src_date == today and isinstance(src_accounts, dict):
            for name, item in src_accounts.items():
                if not isinstance(name, str):
                    changed = True
                    continue
                if not isinstance(item, dict):
                    changed = True
                    continue
                status = str(item.get("status") or "").strip()
                updated_at = str(item.get("updated_at") or "").strip()
                if not status:
                    changed = True
                    continue
                if status not in ("已签到", "不可签到"):
                    status = "未签到"
                normalized["accounts"][name] = {
                    "status": status,
                    "updated_at": updated_at,
                }
        else:
            changed = True
    else:
        changed = True

    if data != normalized:
        changed = True
    return normalized, changed


def load_signin_store(normalize_and_persist: bool = True) -> dict[str, Any]:
    with config_lock:
        ensure_data_layout()
        if SIGNIN_PATH.exists():
            try:
                with SIGNIN_PATH.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception:
                raw = {}
        else:
            raw = {}

        normalized, changed = _normalize_signin_store(raw if isinstance(raw, dict) else {})
        if normalize_and_persist and changed:
            atomic_save_json(SIGNIN_PATH, normalized)
        return normalized


def set_signin_status_today(account_name: str, status: str) -> None:
    if not account_name:
        return
    with config_lock:
        store = load_signin_store(normalize_and_persist=False)
        accounts = store.setdefault("accounts", {})
        if not isinstance(accounts, dict):
            accounts = {}
            store["accounts"] = accounts
        accounts[account_name] = {
            "status": status,
            "updated_at": now_ts(),
        }
        atomic_save_json(SIGNIN_PATH, store)


def set_base_url_signin_status_today(accounts: list[dict[str, Any]], base_url: str, status: str) -> None:
    normalized_url = normalize_base_url(base_url)
    for account in accounts:
        account_url = normalize_base_url(str(account.get("base_url") or get_base_url()))
        if account_url != normalized_url:
            continue
        account_index = int(account.get("account_index", 0) or 0)
        runtime_key = str(account_index) if account_index > 0 else str(account.get("name") or "")
        set_signin_status_today(runtime_key, status)


def get_signin_status_today(account_name: str) -> str:
    if not account_name:
        return "未签到"
    store = load_signin_store(normalize_and_persist=True)
    accounts = store.get("accounts", {})
    if not isinstance(accounts, dict):
        return "未签到"
    item = accounts.get(account_name)
    if isinstance(item, dict):
        status = str(item.get("status") or "").strip()
        if status:
            if status == "已签到":
                return "已签到"
            if status == "不可签到":
                return "不可签到"
    return "未签到"


def _normalize_status_cache(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False
    normalized = {"accounts": {}}

    if isinstance(data, dict):
        src_accounts = data.get("accounts")
        if isinstance(src_accounts, dict):
            for name, item in src_accounts.items():
                if not isinstance(name, str) or not isinstance(item, dict):
                    changed = True
                    continue
                normalized["accounts"][name] = item
        else:
            changed = True
    else:
        changed = True

    if data != normalized:
        changed = True
    return normalized, changed


def load_status_cache(normalize_and_persist: bool = True) -> dict[str, Any]:
    with config_lock:
        ensure_data_layout()
        if STATUS_CACHE_PATH.exists():
            try:
                with STATUS_CACHE_PATH.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception:
                raw = {}
        else:
            raw = {}

        normalized, changed = _normalize_status_cache(raw if isinstance(raw, dict) else {})
        if normalize_and_persist and changed:
            atomic_save_json(STATUS_CACHE_PATH, normalized)
        return normalized


def set_status_cache(account_name: str, result: dict[str, Any]) -> None:
    if not account_name or not isinstance(result, dict):
        return
    with config_lock:
        store = load_status_cache(normalize_and_persist=False)
        accounts = store.setdefault("accounts", {})
        if not isinstance(accounts, dict):
            accounts = {}
            store["accounts"] = accounts
        accounts[account_name] = result
        atomic_save_json(STATUS_CACHE_PATH, store)


def get_status_cache(account_name: str) -> dict[str, Any] | None:
    if not account_name:
        return None
    store = load_status_cache(normalize_and_persist=True)
    accounts = store.get("accounts", {})
    if not isinstance(accounts, dict):
        return None
    item = accounts.get(account_name)
    return item if isinstance(item, dict) else None


def move_runtime_entry(path: pathlib.Path, old_name: str, new_name: str) -> None:
    if old_name == new_name or not old_name or not new_name:
        return
    with config_lock:
        if path == SIGNIN_PATH:
            store = load_signin_store(normalize_and_persist=False)
        elif path == HISTORY_PATH:
            store = load_history()
        else:
            store = load_status_cache(normalize_and_persist=False)

        accounts = store.get("accounts", {})
        if not isinstance(accounts, dict) or old_name not in accounts:
            return
        if new_name not in accounts:
            accounts[new_name] = accounts[old_name]
        del accounts[old_name]
        store["accounts"] = accounts
        atomic_save_json(path, store)


def delete_runtime_entry(path: pathlib.Path, account_name: str) -> None:
    if not account_name:
        return
    with config_lock:
        if path == SIGNIN_PATH:
            store = load_signin_store(normalize_and_persist=False)
        elif path == HISTORY_PATH:
            store = load_history()
        else:
            store = load_status_cache(normalize_and_persist=False)

        accounts = store.get("accounts", {})
        if not isinstance(accounts, dict) or account_name not in accounts:
            return
        del accounts[account_name]
        store["accounts"] = accounts
        atomic_save_json(path, store)


def build_headers(
    new_api_user: str,
    referer: str | None = None,
    extra_headers: dict[str, str] | None = None,
    base_url: str | None = None,
) -> dict[str, str]:
    base_url = normalize_base_url(base_url or get_base_url())
    headers = dict(DEFAULT_HEADERS)
    headers["new-api-user"] = str(new_api_user)
    headers["origin"] = base_url
    headers["referer"] = referer or f"{base_url}/console/personal"
    if extra_headers:
        headers.update(extra_headers)
    return headers


def payload_text(payload: Any) -> str:
    if isinstance(payload, dict):
        return json.dumps(payload, ensure_ascii=False).lower()
    return str(payload).lower()


def contains_any(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


def mask_api_key(key: str) -> str:
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def get_account_by_index(account_index: int) -> dict[str, Any] | None:
    cfg = load_config()
    accounts = cfg.get("accounts", [])
    idx = get_account_index(accounts, account_index)
    if idx < 0:
        return None
    return accounts[idx]


def account_provider(account: dict[str, Any]) -> str:
    provider = str(account.get("provider") or "new-api").strip().lower()
    return provider if provider in ("new-api", "sub2api") else "new-api"


def token_cache_key(account: dict[str, Any]) -> str:
    base_url = normalize_base_url(str(account.get("base_url") or get_base_url()))
    provider = account_provider(account)
    user_id = str(account.get("new_api_user") or "").strip()
    session_hint = str(account.get("session") or "").strip()[:12] if provider == "sub2api" else user_id
    return f"{provider}|{base_url}|{session_hint}"


def load_token_cache() -> dict[str, Any]:
    ensure_data_layout()
    if not TOKEN_CACHE_PATH.exists():
        return {"accounts": {}}
    try:
        with TOKEN_CACHE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"accounts": {}}
    if not isinstance(data, dict):
        return {"accounts": {}}
    accounts = data.get("accounts")
    if not isinstance(accounts, dict):
        data["accounts"] = {}
    return data


def save_token_cache(data: dict[str, Any]) -> None:
    with config_lock:
        accounts = data.get("accounts")
        if not isinstance(accounts, dict):
            data["accounts"] = {}
        atomic_save_json(TOKEN_CACHE_PATH, data)


def token_cache_entry(account: dict[str, Any]) -> dict[str, Any]:
    store = load_token_cache()
    entry = store.get("accounts", {}).get(token_cache_key(account))
    return entry if isinstance(entry, dict) else {}


def cached_token_groups(account: dict[str, Any]) -> list[dict[str, Any]]:
    groups = token_cache_entry(account).get("groups")
    return groups if isinstance(groups, list) else []


def cached_tokens(account: dict[str, Any]) -> list[dict[str, Any]]:
    tokens = token_cache_entry(account).get("tokens")
    return tokens if isinstance(tokens, list) else []


def has_cached_tokens(account: dict[str, Any]) -> bool:
    return isinstance(token_cache_entry(account).get("tokens"), list)


def sanitize_token_for_cache(token: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": token.get("id"),
        "name": str(token.get("name") or ""),
        "key": "",
        "group": str(token.get("group") or ""),
    }


def update_token_cache(
    account: dict[str, Any],
    *,
    groups: list[dict[str, Any]] | None = None,
    tokens: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    with config_lock:
        store = load_token_cache()
        accounts = store.setdefault("accounts", {})
        if not isinstance(accounts, dict):
            accounts = {}
            store["accounts"] = accounts
        key = token_cache_key(account)
        entry = accounts.get(key)
        if not isinstance(entry, dict):
            entry = {}
            accounts[key] = entry
        if groups is not None:
            entry["groups"] = groups
            entry["groups_updated_at"] = now_ts()
        if tokens is not None:
            entry["tokens"] = [sanitize_token_for_cache(token) for token in tokens]
            entry["tokens_updated_at"] = now_ts()
        entry["updated_at"] = now_ts()
        atomic_save_json(TOKEN_CACHE_PATH, store)
        return entry


def cache_add_token(account: dict[str, Any], token: dict[str, Any]) -> None:
    tokens = cached_tokens(account)
    token_id = token.get("id")
    cached = sanitize_token_for_cache(token)
    if token_id is not None:
        tokens = [item for item in tokens if str(item.get("id")) != str(token_id)]
    update_token_cache(account, tokens=[cached, *tokens])


def cache_delete_token(account: dict[str, Any], token_id: int) -> None:
    tokens = cached_tokens(account)
    update_token_cache(account, tokens=[item for item in tokens if str(item.get("id")) != str(token_id)])


def load_site_info() -> dict[str, Any]:
    ensure_data_layout()
    if not SITE_INFO_PATH.exists():
        return {"sites": {}}
    try:
        with SITE_INFO_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"sites": {}}
    if not isinstance(data, dict):
        return {"sites": {}}
    sites = data.get("sites")
    if not isinstance(sites, dict):
        data["sites"] = {}
    return data


def get_site_info(base_url: str) -> dict[str, Any]:
    normalized_url = normalize_base_url(base_url)
    store = load_site_info()
    entry = store.get("sites", {}).get(normalized_url)
    if not isinstance(entry, dict):
        entry = {}
    models = entry.get("models")
    return {
        "base_url": normalized_url,
        "remark": str(entry.get("remark") or ""),
        "models": [str(model) for model in models if str(model).strip()] if isinstance(models, list) else [],
        "models_loaded": isinstance(models, list),
        "models_updated_at": str(entry.get("models_updated_at") or ""),
    }


def update_site_info(
    base_url: str,
    *,
    remark: str | None = None,
    models: list[str] | None = None,
) -> dict[str, Any]:
    normalized_url = normalize_base_url(base_url)
    with config_lock:
        store = load_site_info()
        sites = store.setdefault("sites", {})
        if not isinstance(sites, dict):
            sites = {}
            store["sites"] = sites
        entry = sites.get(normalized_url)
        if not isinstance(entry, dict):
            entry = {}
            sites[normalized_url] = entry
        if remark is not None:
            entry["remark"] = remark
            entry["remark_updated_at"] = now_ts()
        if models is not None:
            entry["models"] = models
            entry["models_updated_at"] = now_ts()
        entry["updated_at"] = now_ts()
        atomic_save_json(SITE_INFO_PATH, store)
    return get_site_info(normalized_url)


def first_account_for_site(base_url: str) -> dict[str, Any] | None:
    normalized_url = normalize_base_url(base_url)
    cfg = load_config()
    for account in cfg.get("accounts", []):
        account_url = normalize_base_url(str(account.get("base_url") or get_base_url()))
        if account_url == normalized_url:
            return account
    return None


def first_new_api_account_for_site(base_url: str) -> dict[str, Any] | None:
    normalized_url = normalize_base_url(base_url)
    cfg = load_config()
    for account in cfg.get("accounts", []):
        if account_provider(account) != "new-api":
            continue
        account_url = normalize_base_url(str(account.get("base_url") or get_base_url()))
        if account_url == normalized_url:
            return account
    return None


def site_has_provider(base_url: str, provider: str) -> bool:
    normalized_url = normalize_base_url(base_url)
    wanted_provider = str(provider or "").strip().lower()
    cfg = load_config()
    for account in cfg.get("accounts", []):
        account_url = normalize_base_url(str(account.get("base_url") or get_base_url()))
        if account_url == normalized_url and account_provider(account) == wanted_provider:
            return True
    return False


def filter_supported_models(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    keywords = ("gpt-image-2", "gpt", "claude", "gemini")
    models: list[str] = []
    for item in data:
        model = str(item or "").strip()
        if not model or not any(keyword in model.lower() for keyword in keywords):
            continue
        if model not in models:
            models.append(model)
    return models


def fetch_site_models(base_url: str) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    normalized_url = normalize_base_url(base_url)
    if site_has_provider(normalized_url, "sub2api"):
        info = update_site_info(normalized_url, models=[])
        return [], info, {
            "provider": "sub2api",
            "message": "sub2api sites do not use new-api model detection",
            "skipped": True,
        }
    account = first_new_api_account_for_site(normalized_url)
    if account is None:
        info = update_site_info(normalized_url, models=[])
        return [], info, {
            "provider": "unknown",
            "message": "only new-api sites support model detection",
            "skipped": True,
        }
    session_value = str(account.get("session") or "").strip()
    user_id = str(account.get("new_api_user") or "").strip()
    if not session_value:
        raise ValueError("first new-api account is missing session")
    if not user_id:
        raise ValueError("first new-api account is missing new_api_user")
    headers = build_headers(
        user_id,
        referer=f"{normalized_url}/keys",
        base_url=normalized_url,
    )
    url = normalized_url.rstrip("/") + "/" + MODELS_PATH.lstrip("/")
    resp = requests.get(
        url,
        cookies={"session": session_value},
        headers=headers,
        timeout=TIMEOUT_SECONDS,
    )
    payload = parse_api_payload(resp)
    error = api_payload_error(payload, resp)
    if error:
        raise RuntimeError(error)
    models = filter_supported_models(payload)
    info = update_site_info(normalized_url, models=models)
    return models, info, payload


def parse_cookie_header(raw_cookie: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in str(raw_cookie or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key:
            cookies[key] = value.strip()
    return cookies


def build_token_headers(account: dict[str, Any]) -> tuple[str, str, dict[str, str], dict[str, str]]:
    session_value = str(account.get("session") or "").strip()
    user_id = str(account.get("new_api_user") or "").strip()
    base_url = normalize_base_url(str(account.get("base_url") or get_base_url()))
    if account_provider(account) == "sub2api":
        headers = dict(DEFAULT_HEADERS)
        headers.update({
            "authorization": f"Bearer {session_value}",
            "origin": base_url,
            "referer": f"{base_url}/keys",
            "dnt": "1",
            "pragma": "no-cache",
            "cache-control": "no-store",
        })
        return base_url, session_value, headers, parse_cookie_header(str(account.get("cookie") or ""))
    headers = build_headers(
        user_id,
        referer=f"{base_url}/console/token",
        extra_headers={
            "dnt": "1",
            "pragma": "no-cache",
            "cache-control": "no-store",
        },
        base_url=base_url,
    )
    return base_url, session_value, headers, {"session": session_value}


def parse_api_payload(resp: requests.Response) -> dict[str, Any]:
    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text[:500]}
    if not isinstance(payload, dict):
        return {"success": False, "message": "response is not an object", "payload": payload}
    return payload


def api_payload_error(payload: dict[str, Any], resp: requests.Response) -> str | None:
    """Return API error message for both new-api and sub2api style payloads.

    new-api commonly uses {success: true/false}; sub2api uses {code: 0, message: "success"}.
    Treat any non-zero code as an error instead of accepting all HTTP 2xx responses.
    """
    message = str(payload.get("message") or payload.get("error") or "").strip()
    if not resp.ok:
        return message or f"http {resp.status_code}"
    if payload.get("success") is False:
        return message or "api returned success=false"
    if "code" in payload and str(payload.get("code")) != "0":
        return message or f"api returned code={payload.get('code')}"
    return None


def normalize_token_groups(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    groups: list[dict[str, Any]] = []
    if isinstance(data, list):
        # sub2api: {code:0, data:[{id, name, description, rate_multiplier, ...}]}
        for item in data:
            if not isinstance(item, dict):
                continue
            group_id = item.get("id")
            name = str(item.get("name") or group_id or "").strip()
            description = str(item.get("description") or "").strip()
            desc = name if not description else f"{name} - {description}"
            groups.append({
                "id": str(group_id),
                "name": name,
                "desc": desc,
                "ratio": item.get("rate_multiplier"),
                "platform": item.get("platform"),
            })
        return groups
    if not isinstance(data, dict):
        return []
    for group_id, item in data.items():
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("desc") or group_id or "").strip()
        description = str(item.get("description") or "").strip()
        groups.append({
            "id": str(group_id),
            "name": name,
            "desc": str(item.get("desc") or (name if not description else f"{name} - {description}") or ""),
            "ratio": item.get("ratio") or item.get("rate_multiplier"),
            "platform": item.get("platform"),
        })
    return groups


def token_records_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("items", "tokens", "rows", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def normalize_tokens(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tokens = []
    for item in token_records_from_payload(payload):
        token_key = item.get("key") or item.get("token") or item.get("value")
        group = item.get("group")
        if isinstance(group, dict):
            group = group.get("name") or group.get("id")
        tokens.append({
            "id": item.get("id"),
            "name": str(item.get("name") or ""),
            "key": format_token_key(token_key),
            "group": str(group or item.get("group_id") or ""),
        })
    return tokens


def group_label_from_groups(groups: list[dict[str, Any]], group_id: Any) -> str:
    wanted = str(group_id or "").strip()
    if not wanted:
        return ""
    for item in groups:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip() == wanted:
            return str(item.get("name") or item.get("desc") or wanted).strip()
    return wanted


def normalize_created_token(payload: dict[str, Any], name: str, group: str, groups: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    token_key = data.get("key") or data.get("token") or data.get("value") or payload.get("key") or payload.get("token")
    created_group = data.get("group")
    if isinstance(created_group, dict):
        created_group = created_group.get("name") or created_group.get("id")
    group_id = data.get("group_id") or group
    group_label = str(created_group or "").strip() or group_label_from_groups(groups or [], group_id)
    return {
        "id": data.get("id") or payload.get("id"),
        "name": str(data.get("name") or name),
        "key": format_token_key(token_key),
        "group": group_label,
        "group_id": str(group_id or ""),
    }


def is_masked_token_key(raw_key: Any) -> bool:
    return "*" in str(raw_key or "")


def format_token_key(raw_key: Any) -> str:
    token_key = str(raw_key or "").strip()
    if not token_key or is_masked_token_key(token_key):
        return ""
    return token_key if token_key.startswith("sk-") else f"sk-{token_key}"


def key_from_token_payload(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    token_key = data.get("key") or data.get("token") or data.get("value") or payload.get("key") or payload.get("token")
    return format_token_key(token_key)


def is_truthy_query_arg(name: str) -> bool:
    return str(request.args.get(name) or "").lower() in {"1", "true", "yes", "on"}


def token_group_error(message: str) -> bool:
    text = str(message or "").lower()
    return any(keyword in text for keyword in ("group", "分组", "模型组", "渠道组"))


def fetch_remote_token_groups(account: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base_url, session_value, headers, cookies = build_token_headers(account)
    if not session_value:
        raise ValueError("missing session")
    path = SUB2API_GROUPS_PATH if account_provider(account) == "sub2api" else TOKEN_GROUPS_PATH
    url = base_url.rstrip("/") + "/" + path.lstrip("/") + ("?timezone=Asia%2FShanghai" if account_provider(account) == "sub2api" else "")
    resp = requests.get(url, cookies=cookies, headers=headers, timeout=TIMEOUT_SECONDS)
    payload = parse_api_payload(resp)
    error = api_payload_error(payload, resp)
    if error:
        raise RuntimeError(error)
    groups = normalize_token_groups(payload)
    update_token_cache(account, groups=groups)
    return groups, payload


def fetch_remote_tokens(account: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base_url, session_value, headers, cookies = build_token_headers(account)
    if not session_value:
        raise ValueError("missing session")
    if account_provider(account) == "sub2api":
        url = base_url.rstrip("/") + "/" + SUB2API_KEYS_PATH.lstrip("/") + "?page=1&page_size=50&sort_by=created_at&sort_order=desc&timezone=Asia%2FShanghai"
    else:
        url = base_url.rstrip("/") + "/" + TOKEN_PATH.lstrip("/") + "?p=1&size=50"
    resp = requests.get(url, cookies=cookies, headers=headers, timeout=TIMEOUT_SECONDS)
    payload = parse_api_payload(resp)
    error = api_payload_error(payload, resp)
    if error:
        raise RuntimeError(error)
    tokens = normalize_tokens(payload)
    update_token_cache(account, tokens=tokens)
    return tokens, payload


def fetch_public_status(base_url: str | None = None) -> dict[str, Any]:
    base_url = normalize_base_url(base_url or get_base_url())
    url = base_url.rstrip("/") + "/" + STATUS_PATH.lstrip("/")
    headers = dict(DEFAULT_HEADERS)
    headers["origin"] = base_url
    headers["referer"] = f"{base_url}/console/personal"
    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return {"ok": False, "api_error": f"network error: {exc}"}

    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text[:500]}

    if isinstance(payload, dict):
        raw = str(payload.get("raw") or "").lstrip().lower()
        if raw.startswith("<!doctype html") or raw.startswith("<html"):
            return {
                "ok": False,
                "api_error": f"status endpoint returned HTML; check base_url ({base_url})",
                "payload": payload,
            }

    if not isinstance(payload, dict) or payload.get("success") is not True:
        message = payload.get("message", "") if isinstance(payload, dict) else ""
        return {
            "ok": False,
            "api_error": message or f"http {resp.status_code}",
            "payload": payload,
        }

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    api_info = data.get("api_info") if isinstance(data.get("api_info"), list) else []
    return {
        "ok": True,
        "system_name": data.get("system_name"),
        "version": data.get("version"),
        "checkin_enabled": data.get("checkin_enabled"),
        "turnstile_check": data.get("turnstile_check"),
        "quota_per_unit": data.get("quota_per_unit"),
        "quota_display_type": data.get("quota_display_type"),
        "display_in_currency": data.get("display_in_currency"),
        "custom_currency_symbol": data.get("custom_currency_symbol"),
        "custom_currency_exchange_rate": data.get("custom_currency_exchange_rate"),
        "usd_exchange_rate": data.get("usd_exchange_rate"),
        "price": data.get("price"),
        "api_info": api_info,
    }


def request_self_with_retry(session_value: str, user_id: str, base_url: str) -> tuple[requests.Response | None, dict[str, Any], str | None]:
    base_url = normalize_base_url(base_url)
    url = base_url.rstrip("/") + "/" + SELF_PATH.lstrip("/")
    cookies = {"session": session_value}
    headers = build_headers(
        user_id,
        referer=f"{base_url}/console",
        extra_headers={
            "dnt": "1",
            "pragma": "no-cache",
            "connection": "close",
        },
        base_url=base_url,
    )

    attempts = 3
    last_error = None
    for idx in range(1, attempts + 1):
        try:
            resp = requests.get(url, cookies=cookies, headers=headers, timeout=TIMEOUT_SECONDS)
            try:
                payload = resp.json()
            except ValueError:
                payload = {"raw": resp.text[:500]}
            return resp, payload, None
        except requests.RequestException as exc:
            last_error = f"network error: {exc}"
            if idx < attempts:
                time.sleep(0.5 * idx)

    return None, {}, last_error or "network error"


def request_sub2api_self_with_retry(account: dict[str, Any]) -> tuple[requests.Response | None, dict[str, Any], str | None]:
    base_url, session_value, headers, cookies = build_token_headers(account)
    url = base_url.rstrip("/") + "/" + SUB2API_SELF_PATH.lstrip("/") + "?timezone=Asia%2FShanghai"
    attempts = 3
    last_error = None
    for idx in range(1, attempts + 1):
        try:
            resp = requests.get(url, cookies=cookies, headers=headers, timeout=TIMEOUT_SECONDS)
            try:
                payload = resp.json()
            except ValueError:
                payload = {"raw": resp.text[:500]}
            return resp, payload, None
        except requests.RequestException as exc:
            last_error = f"network error: {exc}"
            if idx < attempts:
                time.sleep(0.5 * idx)
    return None, {}, last_error or "network error"


def get_last_quota_snapshot(account_name: str) -> dict[str, Any] | None:
    history = load_history()
    accounts = history.get("accounts", {})
    if not isinstance(accounts, dict):
        return None
    rows = accounts.get(account_name, [])
    if not isinstance(rows, list) or not rows:
        return None
    last = rows[-1]
    if not isinstance(last, dict):
        return None
    if not isinstance(last.get("quota"), (int, float)):
        return None
    return last


def get_quota_history_rows(account_name: str) -> list[dict[str, Any]]:
    history = load_history()
    accounts = history.get("accounts", {})
    if not isinstance(accounts, dict):
        return []
    rows = accounts.get(account_name, [])
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("quota"), (int, float)):
            out.append(row)
    return out


def get_last_quota_snapshot_for_date(account_name: str, date_value: str) -> dict[str, Any] | None:
    rows = get_quota_history_rows(account_name)
    matched: list[dict[str, Any]] = []
    for row in rows:
        ts = str(row.get("timestamp") or "").strip()
        if ts.startswith(f"{date_value} "):
            matched.append(row)
    if not matched:
        return None
    return matched[-1]


def record_quota_snapshot_and_get_previous_change(account_name: str, quota: int | float) -> dict[str, Any]:
    snapshot = {
        "timestamp": now_ts(),
        "quota": quota,
    }

    with config_lock:
        history = load_history()
        accounts = history.setdefault("accounts", {})
        if not isinstance(accounts, dict):
            accounts = {}
            history["accounts"] = accounts

        rows = accounts.get(account_name, [])
        if not isinstance(rows, list):
            rows = []

        previous = rows[-1] if rows else None
        rows.append(snapshot)
        if len(rows) > 2000:
            rows = rows[-2000:]
        accounts[account_name] = rows
        atomic_save_json(HISTORY_PATH, history)

    prev_quota = None
    prev_timestamp = None
    if isinstance(previous, dict) and isinstance(previous.get("quota"), (int, float)):
        prev_quota = previous.get("quota")
        prev_timestamp = previous.get("timestamp")

    change = quota - prev_quota if isinstance(prev_quota, (int, float)) else None
    return {
        "current_quota": quota,
        "previous_quota": prev_quota,
        "previous_timestamp": prev_timestamp,
        "change_from_previous": change,
        "timestamp": snapshot["timestamp"],
    }


def build_yesterday_delta(account_name: str, current_quota: int | float | None) -> dict[str, Any]:
    yesterday = yesterday_str()
    snapshot = get_last_quota_snapshot_for_date(account_name, yesterday)
    if not snapshot:
        return {
            "reference_date": yesterday,
            "reference_quota": None,
            "reference_timestamp": None,
            "change_from_yesterday_last": None,
        }

    ref_quota = snapshot.get("quota")
    if not isinstance(ref_quota, (int, float)) or not isinstance(current_quota, (int, float)):
        change = None
    else:
        change = current_quota - ref_quota

    return {
        "reference_date": yesterday,
        "reference_quota": ref_quota,
        "reference_timestamp": snapshot.get("timestamp"),
        "change_from_yesterday_last": change,
    }


def cached_checkin_disabled(account_index: int) -> bool:
    if account_index <= 0:
        return False
    cached = get_status_cache(str(account_index))
    system_status = cached.get("system_status") if isinstance(cached, dict) else None
    return isinstance(system_status, dict) and system_status.get("checkin_enabled") is False


def checkin_response_unsupported(status_code: int, text: str) -> bool:
    if status_code in (404, 405):
        return True
    return contains_any(text, CHECKIN_UNSUPPORTED_KEYWORDS)


def classify_checkin(account: dict[str, Any]) -> dict[str, Any]:
    name = account.get("name") or "unknown"
    account_index = int(account.get("account_index", 0) or 0)
    session_value = (account.get("session") or "").strip()
    user_id = (account.get("new_api_user") or "").strip()
    base_url = normalize_base_url(str(account.get("base_url") or get_base_url()))
    provider = account_provider(account)

    if provider == "sub2api":
        return {
            "account": name,
            "account_index": account_index,
            "state": "UNSUPPORTED",
            "message": "sub2api 暂未配置签到接口",
            "timestamp": now_ts(),
        }

    if cached_checkin_disabled(account_index):
        return {
            "account": name,
            "account_index": account_index,
            "state": "UNSUPPORTED",
            "message": "该网站未开启签到功能",
            "timestamp": now_ts(),
        }
    if not session_value:
        return {
            "account": name,
            "account_index": account_index,
            "state": "FAILED",
            "message": "missing session",
            "timestamp": now_ts(),
        }
    if not user_id:
        return {
            "account": name,
            "state": "FAILED",
            "message": "missing new_api_user",
            "timestamp": now_ts(),
        }

    url = base_url.rstrip("/") + "/" + CHECKIN_PATH.lstrip("/")
    cookies = {"session": session_value}
    headers = build_headers(user_id, base_url=base_url)

    try:
        resp = requests.post(url, cookies=cookies, headers=headers, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return {
            "account": name,
            "state": "FAILED",
            "message": f"network error: {exc}",
            "timestamp": now_ts(),
        }

    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text[:500]}

    text = payload_text(data)
    message = str(data.get("message", "")).strip() if isinstance(data, dict) else ""

    if checkin_response_unsupported(resp.status_code, text):
        state = "UNSUPPORTED"
        message = message or "该网站不支持签到"
    elif "\u4eca\u65e5\u5df2\u7b7e\u5230" in message or "already" in message.lower():
        state = "ALREADY_SIGNED"
    elif "\u7b7e\u5230\u6210\u529f" in message or (isinstance(data, dict) and data.get("success") is True):
        state = "SIGNED_NOW"
    elif resp.status_code in (401, 403) or contains_any(text, AUTH_KEYWORDS + VERIFY_KEYWORDS):
        state = "FAILED"
        if contains_any(text, VERIFY_KEYWORDS):
            message = message or "verification required"
        else:
            message = message or "session invalid or expired"
    elif resp.ok:
        state = "FAILED"
        message = message or "unknown check-in response"
    else:
        state = "FAILED"
        message = message or f"http {resp.status_code}"

    return {
        "account": name,
        "account_index": account_index,
        "state": state,
        "message": message,
        "http_status": resp.status_code,
        "payload": data,
        "timestamp": now_ts(),
    }


def check_status(account: dict[str, Any], system_status: dict[str, Any] | None = None) -> dict[str, Any]:
    name = account.get("name") or "unknown"
    account_index = int(account.get("account_index", 0) or 0)
    runtime_key = str(account_index) if account_index > 0 else str(name)
    session_value = (account.get("session") or "").strip()
    user_id = (account.get("new_api_user") or "").strip()
    base_url = normalize_base_url(str(account.get("base_url") or get_base_url()))
    provider = account_provider(account)

    if not session_value:
        return {
            "account": name,
            "account_index": account_index,
            "status_state": "INVALID_SESSION",
            "session_valid": False,
            "needs_verification": False,
            "api_error": "missing session",
            "system_status": system_status,
            "timestamp": now_ts(),
        }
    if provider == "new-api" and not user_id:
        return {
            "account": name,
            "status_state": "INVALID_SESSION",
            "session_valid": False,
            "needs_verification": False,
            "api_error": "missing new_api_user",
            "system_status": system_status,
            "timestamp": now_ts(),
        }
    if provider == "sub2api":
        resp, payload, network_error = request_sub2api_self_with_retry(account)
    else:
        resp, payload, network_error = request_self_with_retry(session_value, user_id, base_url=base_url)
    if network_error:
        return {
            "account": name,
            "account_index": account_index,
            "status_state": "NETWORK_ERROR",
            "session_valid": False,
            "needs_verification": False,
            "api_error": network_error,
            "system_status": system_status,
            "timestamp": now_ts(),
        }

    text = payload_text(payload)
    message = str(payload.get("message", "")).strip() if isinstance(payload, dict) else ""
    message_lower = message.lower()

    if resp is None:
        return {
            "account": name,
            "status_state": "NETWORK_ERROR",
            "session_valid": False,
            "needs_verification": False,
            "api_error": "network error",
            "system_status": system_status,
            "timestamp": now_ts(),
        }

    if resp.status_code in (401, 403):
        return {
            "account": name,
            "status_state": "INVALID_SESSION",
            "session_valid": False,
            "needs_verification": False,
            "api_error": f"http {resp.status_code}",
            "system_status": system_status,
            "payload": payload,
            "timestamp": now_ts(),
        }

    raw = str(payload.get("raw") or "").lstrip().lower() if isinstance(payload, dict) else ""
    if raw.startswith("<!doctype html") or raw.startswith("<html"):
        return {
            "account": name,
            "status_state": "API_ERROR",
            "session_valid": False,
            "needs_verification": False,
            "api_error": f"self endpoint returned HTML; check base_url ({base_url})",
            "system_status": system_status,
            "payload": payload,
            "timestamp": now_ts(),
        }

    payload_ok = isinstance(payload, dict) and (payload.get("success") is True or payload.get("code") == 0)
    if payload_ok and isinstance(payload.get("data"), dict):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        quota = data.get("quota")
        if provider == "sub2api" and not isinstance(quota, (int, float)):
            balance = data.get("balance")
            if isinstance(balance, (int, float)):
                quota = balance
        if provider == "sub2api":
            base_system_status = system_status if isinstance(system_status, dict) else {}
            system_status = {
                **base_system_status,
                "ok": True,
                "quota_per_unit": 1,
                "quota_display_type": "USD",
                "checkin_enabled": False,
            }
        quota_delta = None
        quota_source = "live"
        if isinstance(quota, (int, float)):
            quota_delta = record_quota_snapshot_and_get_previous_change(runtime_key, quota)
            yesterday_delta = build_yesterday_delta(runtime_key, quota)
        else:
            last = get_last_quota_snapshot(runtime_key)
            if isinstance(last, dict):
                quota = last.get("quota")
                quota_source = "cache"
                quota_delta = {
                    "current_quota": quota,
                    "previous_quota": quota,
                    "previous_timestamp": last.get("timestamp"),
                    "change_from_previous": 0,
                    "timestamp": now_ts(),
                }
                yesterday_delta = build_yesterday_delta(runtime_key, quota if isinstance(quota, (int, float)) else None)
            else:
                quota_source = "missing"
                quota_delta = {
                    "current_quota": None,
                    "previous_quota": None,
                    "previous_timestamp": None,
                    "change_from_previous": None,
                    "timestamp": now_ts(),
                }
                yesterday_delta = {
                    "reference_date": yesterday_str(),
                    "reference_quota": None,
                    "reference_timestamp": None,
                    "change_from_yesterday_last": None,
                }

        return {
            "account": name,
            "account_index": account_index,
            "status_state": "VALID",
            "session_valid": True,
            "needs_verification": False,
            "api_error": None,
            "system_status": system_status,
            "timestamp": now_ts(),
            "identity": {
                "id": data.get("id"),
                "username": data.get("username"),
                "display_name": data.get("display_name") or data.get("username"),
                "email": data.get("email"),
                "status": data.get("status"),
                "group": data.get("group"),
                "role": data.get("role"),
            },
            "quota": {"quota": quota},
            "quota_delta": quota_delta,
            "yesterday_delta": yesterday_delta,
            "quota_source": quota_source,
            "raw": payload,
        }

    if contains_any(message_lower, VERIFY_KEYWORDS):
        return {
            "account": name,
            "status_state": "VERIFICATION_REQUIRED",
            "session_valid": False,
            "needs_verification": True,
            "api_error": message or "verification required",
            "system_status": system_status,
            "payload": payload,
            "timestamp": now_ts(),
        }

    if contains_any(message_lower, AUTH_KEYWORDS):
        return {
            "account": name,
            "status_state": "INVALID_SESSION",
            "session_valid": False,
            "needs_verification": False,
            "api_error": message or "session invalid or expired",
            "system_status": system_status,
            "payload": payload,
            "timestamp": now_ts(),
        }

    if not isinstance(payload, dict) or payload.get("success") is not True:
        return {
            "account": name,
            "status_state": "API_ERROR",
            "session_valid": False,
            "needs_verification": False,
            "api_error": message or "unexpected self response",
            "system_status": system_status,
            "payload": payload,
            "timestamp": now_ts(),
        }

    return {
        "account": name,
        "status_state": "API_ERROR",
        "session_valid": False,
        "needs_verification": False,
        "api_error": message or "unexpected response",
        "system_status": system_status,
        "payload": payload,
        "timestamp": now_ts(),
    }


def get_account_index(accounts: list[dict[str, Any]], account_index: int | str) -> int:
    try:
        wanted = int(account_index)
    except (TypeError, ValueError):
        return -1
    for idx, acc in enumerate(accounts):
        try:
            current = int(acc.get("account_index", 0))
        except (TypeError, ValueError):
            current = 0
        if current == wanted:
            return idx
    return -1


def get_next_account_index(accounts: list[dict[str, Any]]) -> int:
    max_id = 0
    for acc in accounts:
        try:
            max_id = max(max_id, int(acc.get("account_index", 0)))
        except (TypeError, ValueError):
            continue
    return max_id + 1


def to_public_account(account: dict[str, Any], signin_status: str = "未签到", last_status: dict[str, Any] | None = None) -> dict[str, Any]:
    api_keys = parse_api_keys(account.get("api_keys"))
    public_signin_status = signin_status if signin_status in ("已签到", "不可签到") else "未签到"
    return {
        "account_index": int(account.get("account_index", 0) or 0),
        "name": account.get("name", ""),
        "enabled": bool(account.get("enabled", True)),
        "base_url": normalize_base_url(str(account.get("base_url") or get_base_url())),
        "provider": account_provider(account),
        "new_api_user": str(account.get("new_api_user", "")),
        "session": str(account.get("session", "")),
        "cookie": str(account.get("cookie", "")),
        "api_keys": api_keys,
        "api_keys_masked": [mask_api_key(k) for k in api_keys],
        "signin_status": public_signin_status,
        "last_status": last_status if isinstance(last_status, dict) else None,
    }


def parse_account_payload(data: dict[str, Any], require_name: bool = True) -> dict[str, Any]:
    name = str(data.get("name") or "").strip()
    raw_base_url = str(data.get("base_url") or "").strip()
    base_url = normalize_base_url(raw_base_url)
    provider = str(data.get("provider") or "new-api").strip().lower()
    if provider not in ("new-api", "sub2api"):
        provider = "new-api"
    new_api_user = str(data.get("new_api_user") or "").strip()
    session_value = str(data.get("session") or "").strip()
    cookie = str(data.get("cookie") or "").strip()
    enabled = bool(data.get("enabled", True))
    api_keys = parse_api_keys(data.get("api_keys"))

    validate_account_fields(
        name=name,
        base_url=raw_base_url,
        new_api_user=new_api_user,
        session_value=session_value,
        api_keys=api_keys,
        require_name=require_name,
        provider=provider,
    )

    return {
        "account_index": int(data.get("account_index", 0) or 0),
        "name": name,
        "enabled": enabled,
        "provider": provider,
        "base_url": base_url,
        "new_api_user": new_api_user,
        "session": session_value,
        "cookie": cookie,
        "api_keys": api_keys,
    }


def find_duplicate_account(
    accounts: list[dict[str, Any]],
    new_account: dict[str, Any],
    *,
    ignore_account_index: int = 0,
) -> dict[str, Any] | None:
    wanted_url = normalize_base_url(str(new_account.get("base_url") or ""))
    wanted_name = str(new_account.get("name") or "").strip().lower()
    if not wanted_url or not wanted_name:
        return None
    for account in accounts:
        if not isinstance(account, dict):
            continue
        try:
            current_index = int(account.get("account_index", 0) or 0)
        except (TypeError, ValueError):
            current_index = 0
        if ignore_account_index and current_index == ignore_account_index:
            continue
        account_url = normalize_base_url(str(account.get("base_url") or get_base_url()))
        account_name = str(account.get("name") or "").strip().lower()
        if account_url == wanted_url and account_name == wanted_name:
            return account
    return None


def ensure_unique_account(
    accounts: list[dict[str, Any]],
    new_account: dict[str, Any],
    *,
    ignore_account_index: int = 0,
) -> None:
    duplicate = find_duplicate_account(accounts, new_account, ignore_account_index=ignore_account_index)
    if duplicate is not None:
        base_url = normalize_base_url(str(new_account.get("base_url") or ""))
        name = str(new_account.get("name") or "").strip()
        raise ValueError(f"账号已存在：相同网站地址和账户名已导入（{base_url} / {name}）")


def build_public_accounts(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signin_store = load_signin_store(normalize_and_persist=True)
    signin_map = signin_store.get("accounts", {}) if isinstance(signin_store.get("accounts"), dict) else {}
    status_store = load_status_cache(normalize_and_persist=True)
    status_map = status_store.get("accounts", {}) if isinstance(status_store.get("accounts"), dict) else {}
    name_counts: dict[str, int] = {}
    for acc in accounts:
        name = str(acc.get("name") or "")
        if name:
            name_counts[name] = name_counts.get(name, 0) + 1
    out: list[dict[str, Any]] = []
    for acc in accounts:
        account_index = int(acc.get("account_index", 0) or 0)
        name = str(acc.get("name") or "")
        runtime_key = str(account_index) if account_index > 0 else name
        item = signin_map.get(runtime_key)
        if item is None and name_counts.get(name) == 1:
            item = signin_map.get(name)
        status = item.get("status") if isinstance(item, dict) else "未签到"
        last_status = status_map.get(runtime_key) if isinstance(status_map.get(runtime_key), dict) else None
        if last_status is None and name_counts.get(name) == 1:
            last_status = status_map.get(name) if isinstance(status_map.get(name), dict) else None
        out.append(to_public_account(acc, signin_status=status or "未签到", last_status=last_status))
    return out


def extract_cookie_header(cookies: list[dict[str, Any]]) -> str:
    return "; ".join(
        f"{item.get('name')}={item.get('value')}"
        for item in cookies
        if item.get("name") and item.get("value") is not None
    )


def cookie_value(cookies: list[dict[str, Any]], name: str) -> str:
    for item in cookies:
        if item.get("name") == name:
            return str(item.get("value") or "").strip()
    return ""


def cookie_header_to_list(cookie_header: str) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    for part in str(cookie_header or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            cookies.append({"name": name, "value": value.strip()})
    return cookies


def flatten_storage_values(storage: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for store_name in ("localStorage", "sessionStorage"):
        store = storage.get(store_name)
        if isinstance(store, dict):
            for key, value in store.items():
                values.append(str(key))
                values.append(str(value))
    return values


def find_auth_token_from_storage(storage: dict[str, Any]) -> str:
    preferred_keys = ("token", "access_token", "auth_token", "jwt", "authorization")
    for store_name in ("localStorage", "sessionStorage"):
        store = storage.get(store_name)
        if not isinstance(store, dict):
            continue
        for key, value in store.items():
            key_l = str(key).lower()
            value_s = str(value or "").strip()
            if not value_s:
                continue
            if any(k in key_l for k in preferred_keys):
                if value_s.lower().startswith("bearer "):
                    value_s = value_s.split(None, 1)[1].strip()
                if len(value_s) >= 20:
                    return value_s
            try:
                parsed = json.loads(value_s)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                for nested_key in preferred_keys:
                    nested = parsed.get(nested_key)
                    if isinstance(nested, str) and len(nested.strip()) >= 20:
                        nested = nested.strip()
                        return nested.split(None, 1)[1].strip() if nested.lower().startswith("bearer ") else nested
    return ""


def find_user_id_from_storage(storage: dict[str, Any]) -> str:
    keys = ("new_api_user", "new-api-user", "user_id", "userid", "id")
    for store_name in ("localStorage", "sessionStorage"):
        store = storage.get(store_name)
        if not isinstance(store, dict):
            continue
        for key, value in store.items():
            key_l = str(key).lower()
            value_s = str(value or "").strip()
            if any(k == key_l or k in key_l for k in keys) and value_s.isdigit():
                return value_s
            try:
                parsed = json.loads(value_s)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                for nested_key in ("id", "user_id", "userId", "new_api_user"):
                    nested = parsed.get(nested_key)
                    if str(nested or "").strip().isdigit():
                        return str(nested).strip()
    return ""


def request_new_api_self_for_auth(base_url: str, session_value: str, user_id: str) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    headers = build_headers(user_id, referer=f"{base_url}/console", base_url=base_url)
    url = base_url.rstrip("/") + "/" + SELF_PATH.lstrip("/")
    try:
        resp = requests.get(url, cookies={"session": session_value}, headers=headers, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return {}, None, f"network error: {exc}"
    payload = parse_api_payload(resp)
    if not resp.ok or payload.get("success") is False:
        return payload, None, api_payload_error(payload, resp)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    return payload, data, None


def request_sub2api_self_for_auth(base_url: str, token: str, cookie_header: str) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    account = {"provider": "sub2api", "base_url": base_url, "session": token, "cookie": cookie_header}
    resp, payload, network_error = request_sub2api_self_with_retry(account)
    if network_error:
        return {}, None, network_error
    if resp is None:
        return payload, None, "network error"
    if not resp.ok or payload.get("success") is False:
        return payload, None, api_payload_error(payload, resp)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    return payload, data, None


def build_auth_account(base_url: str, cookies: list[dict[str, Any]], storage: dict[str, Any], *, verify_remote: bool = True) -> dict[str, Any]:
    base_url = normalize_base_url(base_url)
    cookie_header = extract_cookie_header(cookies)
    session_value = cookie_value(cookies, "session")
    user_id = find_user_id_from_storage(storage)
    token = find_auth_token_from_storage(storage)
    notes: list[str] = []

    if session_value:
        payload: dict[str, Any] = {}
        identity: dict[str, Any] | None = None
        error: str | None = None
        if verify_remote:
            payload, identity, error = request_new_api_self_for_auth(base_url, session_value, user_id)
            if identity is None and not user_id:
                for candidate in flatten_storage_values(storage):
                    if candidate.isdigit():
                        payload, identity, error = request_new_api_self_for_auth(base_url, session_value, candidate)
                        if identity:
                            user_id = candidate
                            break
        else:
            identity = find_identity_from_storage(storage)
        if identity:
            user_id = str(identity.get("id") or user_id or "").strip()
            display = preferred_account_name(identity, user_id)
            return {"provider": "new-api", "base_url": base_url, "name": display or f"new-api-{user_id or 'account'}", "new_api_user": user_id, "session": session_value, "cookie": "", "identity": identity, "payload": payload, "notes": notes}
        if not verify_remote:
            host = base_url.split("://", 1)[-1].split("/", 1)[0]
            fallback_name = f"new-api-{user_id}" if user_id else f"new-api-{host or 'account'}"
            notes.append("已读取 new-api session Cookie；JSON 中没有用户身份信息时，需要手动确认或补充 new_api_user。")
            return {"provider": "new-api", "base_url": base_url, "name": fallback_name, "new_api_user": user_id, "session": session_value, "cookie": "", "identity": identity or {}, "payload": {}, "notes": notes}
        notes.append(error or "new-api self endpoint did not return identity")

    if token:
        payload: dict[str, Any] = {}
        identity: dict[str, Any] | None = None
        error: str | None = None
        if verify_remote:
            payload, identity, error = request_sub2api_self_for_auth(base_url, token, cookie_header)
        else:
            identity = find_identity_from_storage(storage)
        if identity:
            display = preferred_account_name(identity)
            return {"provider": "sub2api", "base_url": base_url, "name": display or "sub2api-account", "new_api_user": "", "session": token, "cookie": cookie_header, "identity": identity, "payload": payload, "notes": notes}
        if not verify_remote:
            return {"provider": "sub2api", "base_url": base_url, "name": "sub2api-account", "new_api_user": "", "session": token, "cookie": cookie_header, "identity": {}, "payload": {}, "notes": notes}
        notes.append(error or "sub2api self endpoint did not return identity")

    raise ValueError("Could not detect a supported login session. Please make sure login is complete, then try capture again. " + " | ".join(notes))


def parse_possible_json_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if text[0] not in "[{\"" and text.lower() not in ("true", "false", "null"):
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def find_identity_from_storage(storage: dict[str, Any]) -> dict[str, Any] | None:
    preferred_keys = ("user", "auth_user", "current_user", "profile", "account")
    for store_name in ("localStorage", "sessionStorage"):
        store = storage.get(store_name)
        if not isinstance(store, dict):
            continue
        for key, value in store.items():
            parsed = parse_possible_json_value(value)
            if isinstance(parsed, dict):
                key_l = str(key).lower()
                if key_l in preferred_keys or any(k in key_l for k in preferred_keys):
                    if any(str(parsed.get(k) or "").strip() for k in ("id", "email", "username", "display_name", "name")):
                        return parsed
        for value in store.values():
            parsed = parse_possible_json_value(value)
            if isinstance(parsed, dict) and any(str(parsed.get(k) or "").strip() for k in ("id", "email", "username", "display_name", "name")):
                return parsed
    return None


def json_import_storage_items(import_json: dict[str, Any]) -> dict[str, Any]:
    storage_scan = import_json.get("storageScan") if isinstance(import_json, dict) else {}
    storage: dict[str, Any] = {"localStorage": {}, "sessionStorage": {}, "href": str(import_json.get("page") or "")}
    for source_name, target_name in (("localStorage", "localStorage"), ("sessionStorage", "sessionStorage")):
        source = storage_scan.get(source_name) if isinstance(storage_scan, dict) else {}
        items = source.get("items") if isinstance(source, dict) else None
        out: dict[str, str] = {}
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip()
                if not key:
                    continue
                value = item.get("value")
                if isinstance(value, (dict, list)):
                    out[key] = json.dumps(value, ensure_ascii=False)
                else:
                    out[key] = str(value or "")
        elif isinstance(source, dict):
            for key, value in source.items():
                if key in ("storageName", "matchedCount", "items"):
                    continue
                out[str(key)] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
        storage[target_name] = out
    return storage


def json_import_cookie_sources(import_json: Any) -> list[Any]:
    if isinstance(import_json, list):
        return [import_json]
    if not isinstance(import_json, dict):
        return []
    sources: list[Any] = []
    # Cookie Editor common exports: a top-level list, {cookies:[...]}, or browser/site export containers.
    # Also supports enhanced userscript export fields:
    # cookieEditorCookies / httpOnlyCookies / importCookies / cookieHeader / rawCookie.
    for key in (
        "cookies",
        "cookie",
        "cookieStore",
        "cookie_store",
        "cookieEditorCookies",
        "httpOnlyCookies",
        "importCookies",
        "manualCookies",
        "cookieHeader",
        "rawCookie",
    ):
        value = import_json.get(key)
        if isinstance(value, (list, str, dict)):
            sources.append(value)
    visible = import_json.get("visibleCookies")
    if isinstance(visible, dict) and isinstance(visible.get("cookies"), list):
        sources.append(visible.get("cookies"))
    # Some extensions export per-domain maps or nested stores.
    for key in ("domains", "sites", "store", "stores"):
        value = import_json.get(key)
        if isinstance(value, dict):
            for nested in value.values():
                if isinstance(nested, dict):
                    for nested_key in ("cookies", "cookie"):
                        if isinstance(nested.get(nested_key), (list, str, dict)):
                            sources.append(nested.get(nested_key))
                elif isinstance(nested, list):
                    sources.append(nested)
    # Combined import format: {sessionDetector:{...}, cookieEditor:[...]}
    for key in ("sessionDetector", "detector", "scan", "scanner", "cookieEditor"):
        nested = import_json.get(key)
        if isinstance(nested, (dict, list)):
            sources.extend(json_import_cookie_sources(nested))
    return sources


def cookie_item_value(item: dict[str, Any]) -> tuple[str, str]:
    name = str(item.get("name") or item.get("key") or "").strip()
    value = item.get("value")
    if value is None:
        value = item.get("val")
    if value is None:
        value = item.get("content")
    if value is None:
        value = item.get("valuePreview")
    return name, str(value or "").strip()


def json_import_cookies(import_json: Any) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_cookie(name: str, value: str, extra: dict[str, Any] | None = None) -> None:
        name = str(name or "").strip()
        value = str(value or "").strip()
        if not name or not value:
            return
        key = (name, value)
        if key in seen:
            return
        seen.add(key)
        row = {"name": name, "value": value}
        if isinstance(extra, dict):
            for extra_key in ("domain", "path", "httpOnly", "secure", "sameSite", "expirationDate", "expires"):
                if extra_key in extra:
                    row[extra_key] = extra.get(extra_key)
        cookies.append(row)

    for source in json_import_cookie_sources(import_json):
        if isinstance(source, str):
            for item in cookie_header_to_list(source):
                add_cookie(str(item.get("name") or ""), str(item.get("value") or ""))
            continue
        if isinstance(source, dict):
            for key, value in source.items():
                if isinstance(value, (str, int, float)):
                    add_cookie(str(key), str(value))
            source = [source]
        if isinstance(source, list):
            for item in source:
                if isinstance(item, str):
                    for parsed in cookie_header_to_list(item):
                        add_cookie(str(parsed.get("name") or ""), str(parsed.get("value") or ""))
                    continue
                if not isinstance(item, dict):
                    continue
                name, value = cookie_item_value(item)
                add_cookie(name, value, item)
    return cookies


def contains_redacted_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(contains_redacted_value(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_redacted_value(v) for v in value)
    return "[REDACTED]" in str(value)


def origin_base_url_from_value(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        return normalize_base_url(value)
    try:
        parsed = urlparse(value)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    except Exception:
        pass
    return normalize_base_url(value)


def base_url_from_cookie_domains(cookies: list[dict[str, Any]]) -> str:
    for cookie in cookies:
        domain = str(cookie.get("domain") or "").strip().lstrip(".")
        if domain:
            return normalize_base_url(domain)
    return ""


def base_url_from_import_json(import_json: Any, cookies: list[dict[str, Any]] | None = None) -> str:
    if isinstance(import_json, dict):
        for key in ("origin", "base_url", "baseUrl", "site", "siteUrl", "site_url", "page", "url", "href", "currentUrl", "current_url"):
            value = str(import_json.get(key) or "").strip()
            if value:
                return origin_base_url_from_value(value)
        for key in ("sessionDetector", "detector", "scan", "scanner", "qiandaoAccount"):
            nested = import_json.get(key)
            if isinstance(nested, dict):
                nested_url = base_url_from_import_json(nested, cookies)
                if nested_url:
                    return nested_url
    cookie_url = base_url_from_cookie_domains(cookies or [])
    if cookie_url:
        return cookie_url
    return ""


def account_from_qiandao_import_field(import_json: Any, base_url: str) -> dict[str, Any] | None:
    if not isinstance(import_json, dict):
        return None
    raw = import_json.get("qiandaoAccount") or import_json.get("account")
    if not isinstance(raw, dict):
        detected = import_json.get("detected")
        raw = detected.get("account") if isinstance(detected, dict) else None
    if not isinstance(raw, dict):
        return None

    provider = str(raw.get("provider") or "").strip().lower()
    if provider not in ("new-api", "sub2api"):
        return None
    session_value = str(raw.get("session") or raw.get("access_token") or "").strip()
    if not session_value:
        return None
    if contains_redacted_value(session_value):
        raise ValueError("JSON 中的 qiandaoAccount.session 已被 [REDACTED] 脱敏，不能使用；请重新用插件复制未脱敏 JSON。")

    account_base_url = normalize_base_url(str(raw.get("base_url") or raw.get("baseUrl") or base_url or "").strip())
    if not account_base_url:
        return None
    raw_identity = raw.get("identity") if isinstance(raw.get("identity"), dict) else {}
    storage_identity = find_identity_from_storage(json_import_storage_items(import_json)) or {}
    raw_identity = merge_identity_for_import(raw_identity, storage_identity)
    name = str(raw.get("name") or "").strip()
    identity_name = preferred_account_name(raw_identity)
    # If the plugin/API produced an email as account label, prefer the real
    # display name/username from merged identity, e.g. gererh instead of x@y.com.
    if identity_name and (not name or is_email_like(name) or name == str(raw_identity.get("id") or "")):
        name = identity_name
    new_api_user = str(raw.get("new_api_user") or raw.get("newApiUser") or "").strip()
    cookie = str(raw.get("cookie") or "").strip()
    if provider == "new-api" and not name:
        name = f"new-api-{new_api_user or account_base_url.split('://', 1)[-1]}"
    if provider == "sub2api" and not name:
        name = "sub2api-account"

    return {
        "provider": provider,
        "base_url": account_base_url,
        "name": name,
        "new_api_user": new_api_user,
        "session": session_value,
        "cookie": cookie,
        "identity": raw_identity,
        "payload": {},
        "notes": ["从浏览器插件 qiandaoAccount 字段直接导入"],
    }


def build_auth_account_from_import_json(import_json: Any, fallback_base_url: str = "") -> tuple[dict[str, Any], list[str]]:
    if not isinstance(import_json, (dict, list)):
        raise ValueError("请粘贴完整 JSON 对象，或 Cookie Editor 导出的 Cookie JSON 数组")
    cookies = json_import_cookies(import_json)
    base_url = base_url_from_import_json(import_json, cookies)
    if not base_url and fallback_base_url:
        base_url = normalize_base_url(fallback_base_url)
    if not base_url:
        raise ValueError("JSON 中缺少 origin/page/url，且 Cookie 中没有 domain，无法识别域名地址")

    direct_account = account_from_qiandao_import_field(import_json, base_url)
    if direct_account:
        return direct_account, list(direct_account.get("notes") or [])

    storage = json_import_storage_items(import_json if isinstance(import_json, dict) else {})
    notes: list[str] = []
    token = find_auth_token_from_storage(storage)
    session_value = cookie_value(cookies, "session")
    identity = find_identity_from_storage(storage) or {}

    if token:
        if contains_redacted_value(token):
            raise ValueError("JSON 中的 auth_token 已被 [REDACTED] 脱敏，不能作为 Bearer Token 使用；请粘贴未脱敏的完整 JSON。")
        account = build_auth_account(base_url, cookies, storage, verify_remote=False)
        account["notes"] = ["从粘贴 JSON 导入：localStorage.auth_token 作为 sub2api Bearer Token"]
        return account, notes

    if session_value:
        if contains_redacted_value(session_value):
            raise ValueError("JSON 中的 session 已被 [REDACTED] 脱敏，不能使用；请粘贴未脱敏的完整 Cookie。")
        account = build_auth_account(base_url, cookies, storage, verify_remote=False)
        account["notes"] = ["从粘贴 JSON 导入：Cookie session 作为 new-api session"]
        return account, notes

    if identity and str(identity.get("id") or "").strip():
        user_id = str(identity.get("id") or "").strip()
        display = preferred_account_name(identity, user_id)
        account = {
            "provider": "new-api",
            "base_url": base_url,
            "name": display or f"new-api-{user_id}",
            "new_api_user": user_id,
            "session": "",
            "cookie": "",
            "identity": identity,
            "payload": {},
            "notes": [
                "JSON 中已识别到 new-api 用户信息和 new_api_user",
                "但没有 session Cookie；该 Cookie 通常是 HttpOnly，普通网页 JSON 无法读取，需要手动补充 session 后再创建账号",
            ],
        }
        notes.extend(account["notes"])
        return account, notes

    raise ValueError("没有在 JSON 中找到可用字段：new-api 需要用户信息或 Cookie session；sub2api 需要 localStorage.auth_token。")


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/api/accounts", methods=["GET"])
def list_accounts():
    cfg = load_config()
    accounts = build_public_accounts(cfg.get("accounts", []))
    return jsonify({
        "ok": True,
        "accounts": accounts,
        "default_base_url": normalize_base_url(str(cfg.get("base_url") or get_base_url())),
        "known_base_urls": collect_known_base_urls(cfg),
    })


@app.route("/api/accounts", methods=["POST"])
def add_account():
    try:
        payload = request.get_json(force=True)
        new_account = parse_account_payload(payload, require_name=True)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    cfg = load_config(normalize_and_persist=False)
    accounts = cfg.get("accounts", [])
    try:
        ensure_unique_account(accounts, new_account)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409

    new_account["account_index"] = get_next_account_index(accounts)
    accounts.append(new_account)
    cfg["accounts"] = accounts
    cfg = save_config(cfg)
    return jsonify({"ok": True, "account": to_public_account(new_account, signin_status="未签到", last_status=None), "accounts": build_public_accounts(cfg["accounts"])})


@app.route("/api/accounts/reorder", methods=["POST"])
def reorder_accounts():
    try:
        payload = request.get_json(force=True)
        ordered_ids = payload.get("ordered_ids", []) if isinstance(payload, dict) else []
        if not isinstance(ordered_ids, list) or not ordered_ids:
            raise ValueError("ordered_ids is required")
        wanted_ids = [int(x) for x in ordered_ids]
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    cfg = load_config(normalize_and_persist=False)
    accounts = cfg.get("accounts", [])
    existing_ids = []
    account_map: dict[int, dict[str, Any]] = {}
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        try:
            account_id = int(acc.get("account_index", 0))
        except (TypeError, ValueError):
            continue
        if account_id > 0:
            existing_ids.append(account_id)
            account_map[account_id] = acc

    if sorted(existing_ids) != sorted(wanted_ids):
        return jsonify({"ok": False, "error": "ordered_ids does not match existing accounts"}), 400

    cfg["accounts"] = [account_map[account_id] for account_id in wanted_ids]
    cfg = save_config(cfg)
    return jsonify({"ok": True, "accounts": build_public_accounts(cfg["accounts"])})


@app.route("/api/accounts/<int:account_index>", methods=["PUT"])
def update_account(account_index: int):
    old_key = str(account_index)
    cfg = load_config(normalize_and_persist=False)
    accounts = cfg.get("accounts", [])
    idx = get_account_index(accounts, account_index)
    if idx < 0:
        return jsonify({"ok": False, "error": "account not found"}), 404

    old_account = accounts[idx]
    old_name = str(old_account.get("name") or "")
    try:
        payload = request.get_json(force=True)
        updated = parse_account_payload(payload, require_name=True)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    try:
        ensure_unique_account(accounts, updated, ignore_account_index=account_index)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409

    updated["account_index"] = account_index
    accounts[idx] = updated
    cfg["accounts"] = accounts
    cfg = save_config(cfg)
    if old_key != old_name:
        move_runtime_entry(SIGNIN_PATH, old_name, old_key)
        move_runtime_entry(HISTORY_PATH, old_name, old_key)
        move_runtime_entry(STATUS_CACHE_PATH, old_name, old_key)
    return jsonify({
        "ok": True,
        "account": to_public_account(
            updated,
            signin_status=get_signin_status_today(old_key),
            last_status=get_status_cache(old_key),
        ),
        "accounts": build_public_accounts(cfg["accounts"]),
    })


@app.route("/api/accounts/<int:account_index>", methods=["DELETE"])
def delete_account(account_index: int):
    cfg = load_config(normalize_and_persist=False)
    accounts = cfg.get("accounts", [])
    idx = get_account_index(accounts, account_index)
    if idx < 0:
        return jsonify({"ok": False, "error": "account not found"}), 404

    removed = accounts.pop(idx)
    runtime_key = str(account_index)
    old_name = str(removed.get("name") or "")
    delete_runtime_entry(SIGNIN_PATH, runtime_key)
    delete_runtime_entry(HISTORY_PATH, runtime_key)
    delete_runtime_entry(STATUS_CACHE_PATH, runtime_key)
    if old_name != runtime_key:
        delete_runtime_entry(SIGNIN_PATH, old_name)
        delete_runtime_entry(HISTORY_PATH, old_name)
        delete_runtime_entry(STATUS_CACHE_PATH, old_name)
    cfg["accounts"] = accounts
    cfg = save_config(cfg)
    return jsonify({"ok": True, "deleted": removed.get("name"), "accounts": build_public_accounts(cfg["accounts"])})


@app.route("/api/accounts/<int:account_index>/checkin", methods=["POST"])
def checkin_one(account_index: int):
    load_signin_store(normalize_and_persist=True)
    cfg = load_config()
    accounts = cfg.get("accounts", [])
    idx = get_account_index(accounts, account_index)
    if idx < 0:
        return jsonify({"ok": False, "error": "account not found"}), 404
    result = classify_checkin(accounts[idx])
    result["account_index"] = account_index
    runtime_key = str(account_index)
    if result.get("state") in ("SIGNED_NOW", "ALREADY_SIGNED"):
        set_signin_status_today(runtime_key, "已签到")
    elif result.get("state") == "UNSUPPORTED":
        set_base_url_signin_status_today(accounts, str(accounts[idx].get("base_url") or get_base_url()), "不可签到")
    elif result.get("state") == "FAILED":
        set_signin_status_today(runtime_key, "未签到")
    return jsonify({"ok": True, "result": result})


@app.route("/api/accounts/checkin-all", methods=["POST"])
def checkin_all():
    load_signin_store(normalize_and_persist=True)
    cfg = load_config()
    all_accounts = cfg.get("accounts", [])
    accounts = [a for a in all_accounts if a.get("enabled", True)]
    unsupported_base_urls: set[str] = set()
    for account in accounts:
        account_index = int(account.get("account_index", 0) or 0)
        runtime_key = str(account_index) if account_index > 0 else str(account.get("name") or "")
        if get_signin_status_today(runtime_key) == "不可签到" or cached_checkin_disabled(account_index):
            unsupported_base_urls.add(normalize_base_url(str(account.get("base_url") or get_base_url())))
    for base_url in unsupported_base_urls:
        set_base_url_signin_status_today(all_accounts, base_url, "不可签到")

    checkin_accounts: list[dict[str, Any]] = []
    skipped_signed = 0
    skipped_unsupported = 0
    for account in accounts:
        account_index = int(account.get("account_index", 0) or 0)
        runtime_key = str(account_index) if account_index > 0 else str(account.get("name") or "")
        account_base_url = normalize_base_url(str(account.get("base_url") or get_base_url()))
        signin_status = get_signin_status_today(runtime_key)
        if account_base_url in unsupported_base_urls or signin_status == "不可签到":
            skipped_unsupported += 1
            continue
        if signin_status != "未签到":
            skipped_signed += 1
            continue
        checkin_accounts.append(account)

    def checkin_account(acc: dict[str, Any]) -> dict[str, Any]:
        account_name = str(acc.get("name") or "")
        account_index = int(acc.get("account_index", 0) or 0)
        runtime_key = str(account_index) if account_index > 0 else account_name
        result = classify_checkin(acc)
        result["account_index"] = account_index
        if result.get("state") in ("SIGNED_NOW", "ALREADY_SIGNED"):
            set_signin_status_today(runtime_key, "已签到")
        elif result.get("state") == "UNSUPPORTED":
            set_signin_status_today(runtime_key, "不可签到")
        elif result.get("state") == "FAILED":
            set_signin_status_today(runtime_key, "未签到")
        return result

    results = run_batch_parallel(checkin_accounts, checkin_account)
    unsupported_urls = unsupported_base_urls | {
        normalize_base_url(str(account.get("base_url") or get_base_url()))
        for account, result in zip(checkin_accounts, results)
        if result.get("state") == "UNSUPPORTED"
    }
    for base_url in unsupported_urls:
        set_base_url_signin_status_today(all_accounts, base_url, "不可签到")
    return jsonify(
        {
            "ok": True,
            "results": results,
            "eligible_count": len(checkin_accounts),
            "skipped_signed": skipped_signed,
            "skipped_unsupported": skipped_unsupported,
        }
    )


@app.route("/api/accounts/<int:account_index>/status", methods=["POST"])
def status_one(account_index: int):
    cfg = load_config()
    accounts = cfg.get("accounts", [])
    idx = get_account_index(accounts, account_index)
    if idx < 0:
        return jsonify({"ok": False, "error": "account not found"}), 404
    account_base_url = normalize_base_url(str(accounts[idx].get("base_url") or get_base_url()))
    system_status = fetch_public_status(base_url=account_base_url)
    result = check_status(accounts[idx], system_status=system_status)
    result["account_index"] = account_index
    if system_status.get("checkin_enabled") is False:
        set_base_url_signin_status_today(accounts, account_base_url, "不可签到")
    result["signin_status"] = get_signin_status_today(str(account_index))
    set_status_cache(str(account_index), result)
    return jsonify({"ok": True, "result": result, "system_status": system_status})


@app.route("/api/accounts/status-all", methods=["POST"])
def status_all():
    cfg = load_config()
    all_accounts = cfg.get("accounts", [])
    accounts = [a for a in all_accounts if a.get("enabled", True)]
    base_urls = []
    for acc in accounts:
        base_url = normalize_base_url(str(acc.get("base_url") or get_base_url()))
        if base_url not in base_urls:
            base_urls.append(base_url)

    fetched_statuses = run_batch_parallel(base_urls, lambda base_url: (base_url, fetch_public_status(base_url=base_url)))
    system_status_cache: dict[str, dict[str, Any]] = dict(fetched_statuses)

    def check_account_status(acc: dict[str, Any]) -> dict[str, Any]:
        account_base_url = normalize_base_url(str(acc.get("base_url") or get_base_url()))
        system_status = system_status_cache.get(account_base_url, {})
        result = check_status(acc, system_status=system_status)
        account_index = int(acc.get("account_index", 0) or 0)
        runtime_key = str(account_index) if account_index > 0 else str(acc.get("name") or "")
        result["account_index"] = account_index
        result["signin_status"] = get_signin_status_today(runtime_key)
        set_status_cache(runtime_key, result)
        return result

    results = run_batch_parallel(accounts, check_account_status)
    for base_url, system_status in system_status_cache.items():
        if system_status.get("checkin_enabled") is False:
            set_base_url_signin_status_today(all_accounts, base_url, "不可签到")
    for result in results:
        runtime_key = str(result.get("account_index") or "")
        if runtime_key:
            result["signin_status"] = get_signin_status_today(runtime_key)
    default_base_url = normalize_base_url(str(get_base_url()))
    return jsonify({"ok": True, "results": results, "system_status": system_status_cache.get(default_base_url) or fetch_public_status(base_url=default_base_url)})


@app.route("/api/accounts/<int:account_index>/token-groups", methods=["GET"])
def token_groups(account_index: int):
    account = get_account_by_index(account_index)
    if account is None:
        return jsonify({"ok": False, "error": "account not found"}), 404
    force = is_truthy_query_arg("force")
    cached_groups = cached_token_groups(account)
    if cached_groups and not force:
        return jsonify({"ok": True, "groups": cached_groups, "source": "cache"})
    try:
        groups, payload = fetch_remote_token_groups(account)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": f"network error: {exc}"}), 502
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True, "groups": groups, "source": "remote", "payload": payload})


@app.route("/api/accounts/<int:account_index>/tokens", methods=["GET"])
def list_tokens(account_index: int):
    account = get_account_by_index(account_index)
    if account is None:
        return jsonify({"ok": False, "error": "account not found"}), 404
    force = is_truthy_query_arg("force")
    cached = cached_tokens(account)
    if has_cached_tokens(account) and not force:
        return jsonify({"ok": True, "tokens": cached, "source": "cache"})
    try:
        tokens, payload = fetch_remote_tokens(account)
    except ValueError as exc:
        return jsonify({"ok": False, "error": "missing session"}), 400
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": f"network error: {exc}"}), 502
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True, "tokens": tokens, "source": "remote", "payload": payload})


@app.route("/api/accounts/<int:account_index>/tokens", methods=["POST"])
def create_token(account_index: int):
    account = get_account_by_index(account_index)
    if account is None:
        return jsonify({"ok": False, "error": "account not found"}), 404
    payload = request.get_json(force=True)
    token_name = str(payload.get("name") or "").strip() if isinstance(payload, dict) else ""
    token_group = str(payload.get("group") or "").strip() if isinstance(payload, dict) else ""
    if not token_name:
        return jsonify({"ok": False, "error": "token name is required"}), 400
    if not token_group:
        return jsonify({"ok": False, "error": "token group is required"}), 400
    base_url, session_value, headers, cookies = build_token_headers(account)
    if not session_value:
        return jsonify({"ok": False, "error": "missing session"}), 400
    if account_provider(account) == "sub2api":
        url = base_url.rstrip("/") + "/" + SUB2API_KEYS_PATH.lstrip("/")
        try:
            group_id: int | str = int(token_group)
        except ValueError:
            group_id = token_group
        create_payload = {"name": token_name, "group_id": group_id}
    else:
        url = base_url.rstrip("/") + "/" + TOKEN_PATH.lstrip("/")
        create_payload = {
            "remain_quota": 0,
            "remain_amount": 0,
            "expired_time": -1,
            "unlimited_quota": True,
            "model_limits_enabled": False,
            "model_limits": "",
            "cross_group_retry": False,
            "name": token_name,
            "group": token_group,
            "allow_ips": "",
        }
    try:
        resp = requests.post(url, cookies=cookies, headers=headers, json=create_payload, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": f"network error: {exc}"}), 502
    api_response = parse_api_payload(resp)
    error = api_payload_error(api_response, resp)
    if error:
        refreshed_groups: list[dict[str, Any]] = []
        groups_refreshed = False
        if token_group_error(error):
            try:
                refreshed_groups, _ = fetch_remote_token_groups(account)
                groups_refreshed = True
            except Exception:
                groups_refreshed = False
        return jsonify({
            "ok": False,
            "error": error,
            "groups_refreshed": groups_refreshed,
            "groups": refreshed_groups,
            "payload": api_response,
        }), 502
    token = normalize_created_token(api_response, token_name, token_group, groups=cached_token_groups(account))
    cache_add_token(account, token)
    return jsonify({"ok": True, "token": token, "payload": api_response})


@app.route("/api/accounts/<int:account_index>/tokens/<int:token_id>", methods=["DELETE"])
def delete_token(account_index: int, token_id: int):
    account = get_account_by_index(account_index)
    if account is None:
        return jsonify({"ok": False, "error": "account not found"}), 404
    base_url, session_value, headers, cookies = build_token_headers(account)
    if not session_value:
        return jsonify({"ok": False, "error": "missing session"}), 400
    if account_provider(account) == "sub2api":
        url = base_url.rstrip("/") + "/" + SUB2API_KEYS_PATH.lstrip("/") + f"/{token_id}"
    else:
        url = base_url.rstrip("/") + "/" + TOKEN_PATH.lstrip("/") + str(token_id)
    try:
        resp = requests.delete(url, cookies=cookies, headers=headers, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": f"network error: {exc}"}), 502
    payload = parse_api_payload(resp)
    error = api_payload_error(payload, resp)
    if error:
        return jsonify({"ok": False, "error": error, "payload": payload}), 502
    cache_delete_token(account, token_id)
    return jsonify({"ok": True, "payload": payload})


@app.route("/api/accounts/<int:account_index>/tokens/<int:token_id>/key", methods=["POST"])
def reveal_token_key(account_index: int, token_id: int):
    account = get_account_by_index(account_index)
    if account is None:
        return jsonify({"ok": False, "error": "account not found"}), 404
    base_url, session_value, headers, cookies = build_token_headers(account)
    if not session_value:
        return jsonify({"ok": False, "error": "missing session"}), 400
    if account_provider(account) == "sub2api":
        try:
            tokens, payload = fetch_remote_tokens(account)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502
        for token in tokens:
            if str(token.get("id")) == str(token_id):
                return jsonify({"ok": True, "key": format_token_key(token.get("key")), "payload": payload})
        return jsonify({"ok": False, "error": "token not found", "payload": payload}), 404
    url = base_url.rstrip("/") + "/" + TOKEN_PATH.lstrip("/") + f"{token_id}/key"
    try:
        resp = requests.post(url, cookies=cookies, headers=headers, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": f"network error: {exc}"}), 502
    payload = parse_api_payload(resp)
    error = api_payload_error(payload, resp)
    if error:
        return jsonify({"ok": False, "error": error, "payload": payload}), 502
    return jsonify({"ok": True, "key": key_from_token_payload(payload), "payload": payload})


@app.route("/api/sites/info", methods=["GET", "PUT"])
def site_info():
    if request.method == "GET":
        base_url = str(request.args.get("base_url") or "").strip()
        if not base_url:
            return jsonify({"ok": False, "error": "base_url is required"}), 400
        return jsonify({"ok": True, "site": get_site_info(base_url)})

    payload = request.get_json(force=True)
    base_url = str(payload.get("base_url") or "").strip() if isinstance(payload, dict) else ""
    remark = str(payload.get("remark") or "").strip() if isinstance(payload, dict) else ""
    if not base_url:
        return jsonify({"ok": False, "error": "base_url is required"}), 400
    if len(remark) > 500:
        return jsonify({"ok": False, "error": "remark must not exceed 500 characters"}), 400
    return jsonify({"ok": True, "site": update_site_info(base_url, remark=remark)})


@app.route("/api/sites/models", methods=["POST"])
def site_models():
    payload = request.get_json(force=True)
    base_url = str(payload.get("base_url") or "").strip() if isinstance(payload, dict) else ""
    if not base_url:
        return jsonify({"ok": False, "error": "base_url is required"}), 400
    try:
        models, info, api_response = fetch_site_models(base_url)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": f"network error: {exc}"}), 502
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True, "models": models, "site": info, "payload": api_response})


@app.route("/api/auth/import-json", methods=["POST"])
def auth_import_json():
    try:
        payload = request.get_json(force=True)
        raw = payload.get("json") if isinstance(payload, dict) else payload
        if isinstance(raw, str):
            import_json = json.loads(raw)
        elif isinstance(raw, dict):
            import_json = raw
        else:
            raise ValueError("请粘贴 JSON 文本")
        account, notes = build_auth_account_from_import_json(import_json)
        ensure_unique_account(load_config().get("accounts", []), account)
        return jsonify({"ok": True, "account": account, "notes": notes})
    except ValueError as exc:
        message = str(exc)
        status = 409 if "账号已存在" in message else 400
        return jsonify({"ok": False, "error": message}), status
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/system/status", methods=["GET"])
def system_status():
    result = fetch_public_status()
    return jsonify({"ok": True, "result": result})


def ensure_config_normalized() -> None:
    ensure_data_layout()
    load_config(normalize_and_persist=True)
    load_signin_store(normalize_and_persist=True)
    load_status_cache(normalize_and_persist=True)


if __name__ == "__main__":
    ensure_config_normalized()
    app.jinja_env.auto_reload = True
    app.run(host="127.0.0.1", port=5050, debug=False)
