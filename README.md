# new-api Local Console

A local Flask web console for multi-account new-api management.

## Features

- Multi-account management (add, edit, enable/disable, delete)
- Per-account domain (`base_url`) configuration (required when adding/editing)
- One-click sign-in for one account or all enabled accounts
- Persisted **today sign-in status** (`已签到 / 失败 / 未知`)
- Account check with:
  - current balance
  - delta vs previous check
  - previous check timestamp
- API key display (masked/full toggle) and copy to clipboard

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
│  └─ status_cache.json    # Latest account status cache
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
      "api_keys": [
        "sk-xxxx",
        "sk-yyyy"
      ]
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

## Core Behavior

### 1) Sign-in status persistence

- When you run `签到` / `全部签到`, successful states (`SIGNED_NOW`, `ALREADY_SIGNED`) are saved as `已签到`.
- Failed states are saved as `失败`.
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

## UI Actions

- `全部签到`: sign in all enabled accounts and persist today sign-in state.
- `全部检测`: check all enabled accounts and update balance delta.
- Row action `复制APIKey`: copy all keys of that account (newline separated).
- Row action `检测`: run single-account check.

## Notes

- All runtime data is stored under `data/` and ignored by git.
- On startup, old root-level files (`session.json`, `quota_history.json`, `signin_status.json`) are migrated automatically into `data/`.
- If UI looks stale after update, restart backend and hard refresh browser (`Ctrl+F5`).

## Security

- Keep `data/session.json` local.
- Do not share `session` or API keys publicly.

