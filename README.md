# new-api Local Console

A local Flask web console for multi-account new-api management.

## Features

- Multi-account management (add, edit, enable/disable, delete)
- Optional per-account remarks, editable from the account form and shown in account details
- Per-account domain (`base_url`) configuration (required when adding/editing)
- `new_api_user` is optional when adding or editing an account; when provided, it must be numeric.
- Address-level detail view with aggregate balances, editable remarks, special labels, display color, sign-in mode, and cached supported-model information
- Fixed header/detail layout: the address-account list scrolls independently while top controls and the right detail panel stay visible
- Address-level delete action that removes the address group and all accounts under it
- One-click sign-in for one account or all enabled accounts
- Persisted **today sign-in status** (`已签到 / 未签到 / 不可签到`)
- Automatic detection of websites that do not support check-in
- Account check with:
  - current balance
  - delta vs previous check
  - previous check timestamp
- Token management:
  - create tokens from locally cached groups
  - refresh token groups and token records on demand
  - copy full token keys after the remote key endpoint reveals them

## Tech Stack

- Python 3.10+
- Flask
- requests
- Frontend: vanilla HTML/CSS/JS (single page)

## Project Structure

```text
qiandao/
├─ app.py                  # Flask backend
├─ AI_PROJECT_INDEX.md     # Detailed maintenance and AI navigation index
├─ run_web.bat             # Start local web server
├─ data/                   # Local runtime data (ignored by git)
│  ├─ session.json         # Local account config
│  ├─ quota_history.json   # Local balance history
│  ├─ signin_status.json   # Today sign-in status store
│  ├─ status_cache.json    # Latest account status cache
│  ├─ token_cache.json     # Local token group/token metadata cache
│  └─ site_info.json       # Address remarks and filtered model cache
├─ templates/
│  └─ index.html           # Web UI
├─ tests/                  # Account, sign-in, address/model, and token tests
├─ tools/                  # JSON collectors and browser extension
├─ build_artifacts/        # Launcher source/spec and generated build work
├─ .gitignore
├─ README.md
```

## Quick Start

1. Install dependencies:

```powershell
pip install flask requests
```

No browser automation dependency is required for JSON import. The previous browser authorization entry has been removed from the UI; add-account import now works by pasting a captured JSON document.

2. Prepare `data/session.json`:

```json
{
  "base_url": "https://your-service-domain.com",
  "accounts": [
    {
      "name": "account_1",
      "enabled": true,
      "base_url": "https://your-service-domain.com",
      "new_api_user": "1571",
      "session": "YOUR_SESSION",
      "remark": "Optional note for this account"
    }
  ]
}
```

- `base_url` is optional. If omitted, app uses `https://www.new-api.com`.
- You can override at runtime with env var `NEW_API_BASE_URL`.
- `accounts[].base_url` is required for each account; if missing, legacy data is auto-filled from top-level `base_url` during startup.

3. Start the web app:

```powershell
run_web.bat
```

4. Open browser:

- `http://127.0.0.1:5050`
- On Windows, `run_web.bat` first terminates all previous service processes listening on port `5050`, then starts one new service instance.

## Core Behavior

### 1) Sign-in status persistence

- When you run `签到` / `全部签到`, successful states (`SIGNED_NOW`, `ALREADY_SIGNED`) are saved as `已签到`.
- Failed states remain `未签到`.
- If an account's check-in request reports that check-in is disabled or unsupported, or the check-in endpoint returns HTTP 404/405, only that account's daily sign-in status is saved as `不可签到`.
- Address detail has a sign-in mode selector: `自动检测` keeps account-level detection isolated, `可以签到` keeps the address eligible, and `不签到` manually skips the address and all accounts under it.
- A website group is treated as `不可签到` only when the address is manually set to `不签到` or every account under that address is already marked `不可签到`.
- `全部签到` only sends requests for enabled accounts whose current daily status is `未签到`; accounts marked `已签到` or `不可签到` are skipped.
- Store file: `data/signin_status.json`.

### 2) Daily cleanup

- On each sign-in run, sign-in store is normalized to **today**.
- Non-today sign-in records are removed automatically.

### 3) Balance check

- Current balance comes from `/api/user/self`.
- Status and sign-in requests are sent to each account's own `base_url`.
- Delta is computed against the **previous stored snapshot**.
- The last successful detection result is cached locally in `data/status_cache.json`; failed detections do not overwrite it, so the right detail panel can keep showing the last successful balance.
- If current response has no quota, app falls back to last snapshot and marks it as cached source in UI.

### 4) Token group and token metadata cache

- Store file: `data/token_cache.json`.
- The file is created during startup if it does not already exist.
- Opening the add-token dialog uses locally cached groups first.
- If no local groups exist, the app requests `/api/user/self/groups` from the account's `base_url` and saves the result.
- The `刷新令牌` button forces a remote refresh of both token groups and token metadata.
- Successful token creation inserts the new token metadata into the local cache.
- Successful token deletion removes the token metadata from the local cache.
- If token creation fails because the selected group no longer exists, the app refreshes groups from the remote site and asks you to select again.
- Full revealed `sk-...` token keys are not persisted to `data/token_cache.json`; only token metadata is cached locally.

### 5) Address details and model cache

- Single-click an address group to show its account count, available count, sign-in summary, aggregate balance metrics, address remark, special label, display color, sign-in mode, and supported models.
- Double-click an address group to expand or collapse it.
- Address remarks, special labels, display colors, sign-in mode, and model results are stored in `data/site_info.json`.
- Account remarks belong to individual accounts and are stored in `data/session.json`; importing JSON over an existing account preserves its current remark.
- Model detection calls `/api/user/models` using the first account under that address.
- Only model names containing `gpt-image-2`, `gpt`, `claude`, or `gemini` are displayed.

## UI Actions

- `全部签到`: sign in all enabled accounts and persist today sign-in state.
- `全部检测`: check all enabled accounts and update balance delta.
- Address action `删除`: delete the address group and all accounts under it after confirmation.
- Address detail `提交修改`: save address remarks, special info, display color, and sign-in mode together.
- Row action `检测`: run single-account check.
- When a single-account check is abnormal, the account detail panel shows `打开网站更新登录`; it opens the account site with a `qiandao-account` marker so the browser extension can update that exact local account and immediately re-check it.
- `添加令牌`: create a token after token groups are loaded.
- `刷新令牌`: force-refresh token groups and token metadata from the remote site.
- `添加账号` -> `JSON 导入添加`: paste a captured JSON or Cookie Editor exported Cookie JSON, then click `从 JSON 解析并回填`. The site URL is read from JSON `origin`/`page`/`url`, or from cookie `domain`; no extra URL field is required.
- Recommended collector: install the Chrome/Edge extension under `tools/qiandao_account_import_extension`. It reads current-page `localStorage`, current-site cookies through the browser extension cookies API, and tries new-api/sub2api self endpoints to complete missing identity fields. It can export HttpOnly `session` cookies that normal page JavaScript/Tampermonkey cannot read.
- For `sub2api`, the JSON must contain a complete non-redacted `localStorage.auth_token`; `auth_user` is used to fill the account name.
- For `new-api`, the JSON should contain user identity plus a complete `session` cookie. The extension can produce this directly on the logged-in site.

## Performance Tuning

- Batch sign-in and status checks run in parallel.
- `QIANDAO_MAX_BATCH_WORKERS` controls max concurrent account/site requests; default is `24`.
- `QIANDAO_TIMEOUT_SECONDS` controls each HTTP request timeout; default is `10`.
- `QIANDAO_HTTP_RETRY_ATTEMPTS` controls retry attempts for self-info requests; default is `2`.

### Browser extension collector

A local unpacked Chrome/Edge extension is provided at:

```text
tools/qiandao_account_import_extension
```

Install it from `chrome://extensions/` or `edge://extensions/` by enabling developer mode and choosing `加载已解压的扩展程序`.

Usage:

```text
Open logged-in new-api/sub2api site -> click qiandao extension -> 采集当前页 -> 复制导入 JSON -> paste into qiandao JSON import
```

Abnormal-account recovery:

```text
qiandao account detail -> 打开网站更新登录 -> login on the target site -> qiandao extension -> 采集当前页 -> 更新到本地并重新检测
```

`更新到本地并重新检测` matches existing accounts by normalized site address plus `new_api_user`. Existing accounts are updated and checked; new accounts are added, signed in once, and checked once.
qiandao does not store site passwords and will not auto-fill passwords; use the browser's own saved-password/autofill behavior if available.

The extension only targets `new-api` and `sub2api` import fields. It displays the detected site, provider, account name, user ID, and session source, then generates JSON that can be pasted directly into the add-account JSON import box. Exported JSON contains login credentials (`session` or Bearer token), so keep it private.

## Notes

- All runtime data is stored under `data/` and ignored by git.
- On startup, old root-level files (`session.json`, `quota_history.json`, `signin_status.json`) are migrated automatically into `data/`.
- If UI looks stale after update, restart backend and hard refresh browser (`Ctrl+F5`).

## Security

- Keep `data/session.json` local.
- Keep `data/token_cache.json` local.
- Do not share `session` or token keys publicly.
