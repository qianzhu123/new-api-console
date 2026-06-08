# new-api Local Console

A local Flask web console for multi-account new-api management.

## Features

- Multi-account management (add, edit, enable/disable, delete)
- Per-account domain (`base_url`) configuration (required when adding/editing)
- `new_api_user` is optional when adding or editing an account; when provided, it must be numeric.
- Address-level detail view with aggregate balances, editable remarks, and cached supported-model information
- One-click sign-in for one account or all enabled accounts
- Persisted **today sign-in status** (`已签到 / 失败 / 未知`)
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
├─ .gitignore
├─ README.md
```

## Quick Start

1. Install dependencies:

```powershell
pip install flask requests
```

Optional dependency for the browser authorization helper:

```powershell
pip install playwright
python -m playwright install chromium
```

Without Playwright, the normal account management, sign-in, status check, and token functions still work. Only the "授权添加" browser-assisted account capture feature is unavailable.

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
      "session": "YOUR_SESSION"
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
- If the website reports that check-in is disabled or unsupported, or the check-in endpoint returns HTTP 404/405, the status is saved as `不可签到`.
- Once one account confirms that its website cannot check in, that website group's check-in buttons are disabled and the group summary displays `不可签到`.
- `全部签到` only sends requests for enabled accounts whose current daily status is `未签到`; accounts marked `已签到` or `不可签到` are skipped.
- Store file: `data/signin_status.json`.

### 2) Daily cleanup

- On each sign-in run, sign-in store is normalized to **today**.
- Non-today sign-in records are removed automatically.

### 3) Balance check

- Current balance comes from `/api/user/self`.
- Status and sign-in requests are sent to each account's own `base_url`.
- Delta is computed against the **previous stored snapshot**.
- Latest detection result is also cached locally in `data/status_cache.json`.
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

- Single-click an address group to show its account count, available count, sign-in summary, aggregate balance metrics, address remark, and supported models.
- Double-click an address group to expand or collapse it.
- Address remarks and model results are stored in `data/site_info.json`; account records no longer contain remarks.
- Model detection calls `/api/user/models` using the first account under that address.
- Only model names containing `gpt-image-2`, `gpt`, `claude`, or `gemini` are displayed.

## UI Actions

- `全部签到`: sign in all enabled accounts and persist today sign-in state.
- `全部检测`: check all enabled accounts and update balance delta.
- Row action `检测`: run single-account check.
- `添加令牌`: create a token after token groups are loaded.
- `刷新令牌`: force-refresh token groups and token metadata from the remote site.
- `添加账号` -> `授权添加`: enter a target website URL, open an isolated Playwright browser, log in manually, then capture supported login information and auto-fill the add-account form.

## Notes

- All runtime data is stored under `data/` and ignored by git.
- Browser authorization uses an isolated local profile under `data/auth_browser/`, which is also ignored by git.
- On startup, old root-level files (`session.json`, `quota_history.json`, `signin_status.json`) are migrated automatically into `data/`.
- If UI looks stale after update, restart backend and hard refresh browser (`Ctrl+F5`).

## Security

- Keep `data/session.json` local.
- Keep `data/token_cache.json` local.
- Do not share `session` or token keys publicly.

