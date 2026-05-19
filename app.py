import json
import os
import pathlib
import tempfile
import threading
import time
from datetime import datetime, timedelta
from typing import Any

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
DEFAULT_BASE_URL = "https://www.new-api.com"
BASE_URL_ENV_KEY = "NEW_API_BASE_URL"
CHECKIN_PATH = "/api/user/checkin"
SELF_PATH = "/api/user/self"
STATUS_PATH = "/api/status"
TIMEOUT_SECONDS = 20
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


app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
config_lock = threading.RLock()


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


def validate_account_fields(
    name: str,
    base_url: str,
    new_api_user: str,
    session_value: str,
    api_keys: list[str],
    require_name: bool = True,
) -> None:
    if require_name:
        if not name:
            raise ValueError("name is required")
        if not 2 <= len(name) <= 40:
            raise ValueError("name length must be between 2 and 40 characters")
        for ch in name:
            if ch.isalnum() or ch in " _-.":
                continue
            if "\u4e00" <= ch <= "\u9fff":
                continue
            raise ValueError("name contains unsupported characters")

    if not base_url:
        raise ValueError("base_url is required")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")

    if not new_api_user:
        raise ValueError("new_api_user is required")
    if not new_api_user.isdigit():
        raise ValueError("new_api_user must be numeric")

    if not session_value:
        raise ValueError("session is required")
    if any(ch.isspace() for ch in session_value):
        raise ValueError("session must not contain whitespace")
    if len(session_value) < 20:
        raise ValueError("session looks too short")

    for key in api_keys:
        if any(ch.isspace() for ch in key):
            raise ValueError("api_keys must not contain whitespace")
        if len(key) < 10:
            raise ValueError("api_keys entry looks too short")


def normalize_account(account: dict[str, Any], fallback_base_url: str | None = None) -> dict[str, Any]:
    normalized = dict(account)
    account_base = str(normalized.get("base_url") or "").strip()
    if account_base:
        normalized["base_url"] = normalize_base_url(account_base)
    elif fallback_base_url:
        normalized["base_url"] = normalize_base_url(fallback_base_url)
    else:
        normalized["base_url"] = DEFAULT_BASE_URL
    normalized["name"] = str(normalized.get("name") or "").strip()
    normalized["enabled"] = bool(normalized.get("enabled", True))
    normalized["new_api_user"] = str(normalized.get("new_api_user") or "").strip()
    normalized["session"] = str(normalized.get("session") or "").strip()
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

    new_accounts: list[dict[str, Any]] = []
    for item in raw_accounts:
        if not isinstance(item, dict):
            changed = True
            continue
        n = normalize_account(item, fallback_base_url=top_level_base_url)
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
                if status != "已签到":
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
            return "已签到" if status == "已签到" else "未签到"
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
            # Small backoff for TLS EOF / transient network conditions.
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


def classify_checkin(account: dict[str, Any]) -> dict[str, Any]:
    name = account.get("name") or "unknown"
    session_value = (account.get("session") or "").strip()
    user_id = (account.get("new_api_user") or "").strip()
    base_url = normalize_base_url(str(account.get("base_url") or get_base_url()))

    if not session_value:
        return {
            "account": name,
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

    if "\u4eca\u65e5\u5df2\u7b7e\u5230" in message or "already" in message.lower():
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
        "state": state,
        "message": message,
        "http_status": resp.status_code,
        "payload": data,
        "timestamp": now_ts(),
    }


def check_status(account: dict[str, Any], system_status: dict[str, Any] | None = None) -> dict[str, Any]:
    name = account.get("name") or "unknown"
    session_value = (account.get("session") or "").strip()
    user_id = (account.get("new_api_user") or "").strip()
    base_url = normalize_base_url(str(account.get("base_url") or get_base_url()))

    if not session_value:
        return {
            "account": name,
            "status_state": "INVALID_SESSION",
            "session_valid": False,
            "needs_verification": False,
            "api_error": "missing session",
            "system_status": system_status,
            "timestamp": now_ts(),
        }
    if not user_id:
        return {
            "account": name,
            "status_state": "INVALID_SESSION",
            "session_valid": False,
            "needs_verification": False,
            "api_error": "missing new_api_user",
            "system_status": system_status,
            "timestamp": now_ts(),
        }
    resp, payload, network_error = request_self_with_retry(session_value, user_id, base_url=base_url)
    if network_error:
        return {
            "account": name,
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

    if isinstance(payload, dict) and payload.get("success") is True and isinstance(payload.get("data"), dict):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        quota = data.get("quota")
        quota_delta = None
        quota_source = "live"
        if isinstance(quota, (int, float)):
            quota_delta = record_quota_snapshot_and_get_previous_change(name, quota)
            yesterday_delta = build_yesterday_delta(name, quota)
        else:
            last = get_last_quota_snapshot(name)
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
                yesterday_delta = build_yesterday_delta(name, quota if isinstance(quota, (int, float)) else None)
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
            "status_state": "VALID",
            "session_valid": True,
            "needs_verification": False,
            "api_error": None,
            "system_status": system_status,
            "timestamp": now_ts(),
            "identity": {
                "id": data.get("id"),
                "username": data.get("username"),
                "display_name": data.get("display_name"),
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


def get_account_index(accounts: list[dict[str, Any]], name: str) -> int:
    for idx, acc in enumerate(accounts):
        if (acc.get("name") or "") == name:
            return idx
    return -1


def to_public_account(account: dict[str, Any], signin_status: str = "未签到", last_status: dict[str, Any] | None = None) -> dict[str, Any]:
    api_keys = parse_api_keys(account.get("api_keys"))
    return {
        "name": account.get("name", ""),
        "enabled": bool(account.get("enabled", True)),
        "base_url": normalize_base_url(str(account.get("base_url") or get_base_url())),
        "new_api_user": str(account.get("new_api_user", "")),
        "session": str(account.get("session", "")),
        "api_keys": api_keys,
        "api_keys_masked": [mask_api_key(k) for k in api_keys],
        "signin_status": "已签到" if signin_status == "已签到" else "未签到",
        "last_status": last_status if isinstance(last_status, dict) else None,
    }


def parse_account_payload(data: dict[str, Any], require_name: bool = True) -> dict[str, Any]:
    name = str(data.get("name") or "").strip()
    raw_base_url = str(data.get("base_url") or "").strip()
    base_url = normalize_base_url(raw_base_url)
    new_api_user = str(data.get("new_api_user") or "").strip()
    session_value = str(data.get("session") or "").strip()
    enabled = bool(data.get("enabled", True))
    api_keys = parse_api_keys(data.get("api_keys"))

    validate_account_fields(
        name=name,
        base_url=raw_base_url,
        new_api_user=new_api_user,
        session_value=session_value,
        api_keys=api_keys,
        require_name=require_name,
    )

    return {
        "name": name,
        "enabled": enabled,
        "base_url": base_url,
        "new_api_user": new_api_user,
        "session": session_value,
        "api_keys": api_keys,
    }


def build_public_accounts(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signin_store = load_signin_store(normalize_and_persist=True)
    signin_map = signin_store.get("accounts", {}) if isinstance(signin_store.get("accounts"), dict) else {}
    status_store = load_status_cache(normalize_and_persist=True)
    status_map = status_store.get("accounts", {}) if isinstance(status_store.get("accounts"), dict) else {}
    out: list[dict[str, Any]] = []
    for acc in accounts:
        name = str(acc.get("name") or "")
        item = signin_map.get(name)
        status = item.get("status") if isinstance(item, dict) else "未签到"
        last_status = status_map.get(name) if isinstance(status_map.get(name), dict) else None
        out.append(to_public_account(acc, signin_status=status or "未签到", last_status=last_status))
    return out


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/api/accounts", methods=["GET"])
def list_accounts():
    cfg = load_config()
    accounts = build_public_accounts(cfg.get("accounts", []))
    return jsonify({"ok": True, "accounts": accounts, "default_base_url": normalize_base_url(str(cfg.get("base_url") or get_base_url()))})


@app.route("/api/accounts", methods=["POST"])
def add_account():
    try:
        payload = request.get_json(force=True)
        new_account = parse_account_payload(payload, require_name=True)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    cfg = load_config(normalize_and_persist=False)
    accounts = cfg.get("accounts", [])

    if get_account_index(accounts, new_account["name"]) >= 0:
        return jsonify({"ok": False, "error": "account name already exists"}), 409

    accounts.append(new_account)
    cfg["accounts"] = accounts
    cfg = save_config(cfg)
    return jsonify({"ok": True, "account": to_public_account(new_account, signin_status="未签到", last_status=None), "accounts": build_public_accounts(cfg["accounts"])})


@app.route("/api/accounts/<path:name>", methods=["PUT"])
def update_account(name: str):
    old_name = name
    cfg = load_config(normalize_and_persist=False)
    accounts = cfg.get("accounts", [])
    idx = get_account_index(accounts, old_name)
    if idx < 0:
        return jsonify({"ok": False, "error": "account not found"}), 404

    try:
        payload = request.get_json(force=True)
        updated = parse_account_payload(payload, require_name=True)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    new_name = updated["name"]
    if new_name != old_name and get_account_index(accounts, new_name) >= 0:
        return jsonify({"ok": False, "error": "target name already exists"}), 409

    accounts[idx] = updated
    cfg["accounts"] = accounts
    cfg = save_config(cfg)
    if new_name != old_name:
        move_runtime_entry(SIGNIN_PATH, old_name, new_name)
        move_runtime_entry(HISTORY_PATH, old_name, new_name)
        move_runtime_entry(STATUS_CACHE_PATH, old_name, new_name)
    return jsonify({
        "ok": True,
        "account": to_public_account(
            updated,
            signin_status=get_signin_status_today(updated.get("name", "")),
            last_status=get_status_cache(updated.get("name", "")),
        ),
        "accounts": build_public_accounts(cfg["accounts"]),
    })


@app.route("/api/accounts/<path:name>", methods=["DELETE"])
def delete_account(name: str):
    cfg = load_config(normalize_and_persist=False)
    accounts = cfg.get("accounts", [])
    idx = get_account_index(accounts, name)
    if idx < 0:
        return jsonify({"ok": False, "error": "account not found"}), 404

    removed = accounts.pop(idx)
    delete_runtime_entry(SIGNIN_PATH, name)
    delete_runtime_entry(HISTORY_PATH, name)
    delete_runtime_entry(STATUS_CACHE_PATH, name)
    cfg["accounts"] = accounts
    cfg = save_config(cfg)
    return jsonify({"ok": True, "deleted": removed.get("name"), "accounts": build_public_accounts(cfg["accounts"])})


@app.route("/api/accounts/<path:name>/checkin", methods=["POST"])
def checkin_one(name: str):
    # Daily cleanup: keep only today's sign-in records.
    load_signin_store(normalize_and_persist=True)
    cfg = load_config()
    accounts = cfg.get("accounts", [])
    idx = get_account_index(accounts, name)
    if idx < 0:
        return jsonify({"ok": False, "error": "account not found"}), 404
    result = classify_checkin(accounts[idx])
    if result.get("state") in ("SIGNED_NOW", "ALREADY_SIGNED"):
        set_signin_status_today(name, "已签到")
    elif result.get("state") == "FAILED":
        set_signin_status_today(name, "未签到")
    return jsonify({"ok": True, "result": result})


@app.route("/api/accounts/checkin-all", methods=["POST"])
def checkin_all():
    # Daily cleanup: keep only today's sign-in records.
    load_signin_store(normalize_and_persist=True)
    cfg = load_config()
    accounts = [a for a in cfg.get("accounts", []) if a.get("enabled", True)]
    results = []
    for acc in accounts:
        result = classify_checkin(acc)
        account_name = str(acc.get("name") or "")
        if result.get("state") in ("SIGNED_NOW", "ALREADY_SIGNED"):
            set_signin_status_today(account_name, "已签到")
        elif result.get("state") == "FAILED":
            set_signin_status_today(account_name, "未签到")
        results.append(result)
    return jsonify({"ok": True, "results": results})


@app.route("/api/accounts/<path:name>/status", methods=["POST"])
def status_one(name: str):
    cfg = load_config()
    accounts = cfg.get("accounts", [])
    idx = get_account_index(accounts, name)
    if idx < 0:
        return jsonify({"ok": False, "error": "account not found"}), 404
    account_base_url = normalize_base_url(str(accounts[idx].get("base_url") or get_base_url()))
    system_status = fetch_public_status(base_url=account_base_url)
    result = check_status(accounts[idx], system_status=system_status)
    set_status_cache(name, result)
    return jsonify({"ok": True, "result": result, "system_status": system_status})


@app.route("/api/accounts/status-all", methods=["POST"])
def status_all():
    cfg = load_config()
    accounts = [a for a in cfg.get("accounts", []) if a.get("enabled", True)]
    system_status_cache: dict[str, dict[str, Any]] = {}
    results = []
    for acc in accounts:
        account_base_url = normalize_base_url(str(acc.get("base_url") or get_base_url()))
        if account_base_url not in system_status_cache:
            system_status_cache[account_base_url] = fetch_public_status(base_url=account_base_url)
        system_status = system_status_cache[account_base_url]
        result = check_status(acc, system_status=system_status)
        results.append(result)
        set_status_cache(str(acc.get("name") or ""), result)
    default_base_url = normalize_base_url(str(get_base_url()))
    return jsonify({"ok": True, "results": results, "system_status": system_status_cache.get(default_base_url) or fetch_public_status(base_url=default_base_url)})


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
