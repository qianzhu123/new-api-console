# Xiavier Local Console

A local Flask web console for multi-account Xiavier management.

## Features

- Multi-account management (add, edit, enable/disable, delete)
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
├─ templates/
│  └─ index.html           # Web UI
├─ .gitignore
├─ README.md
├─ session.json            # Local account config (ignored by git)
├─ quota_history.json      # Local balance history (ignored by git)
└─ signin_status.json      # Local sign-in status store (ignored by git)
```

## Quick Start

1. Install dependencies:

```powershell
pip install flask requests
```

2. Prepare `session.json` in project root:

```json
{
  "accounts": [
    {
      "name": "account_1",
      "enabled": true,
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
- Store file: `signin_status.json`.

### 2) Daily cleanup

- On each sign-in run, sign-in store is normalized to **today**.
- Non-today sign-in records are removed automatically.

### 3) Balance check

- Current balance comes from `/api/user/self`.
- Delta is computed against the **previous stored snapshot**.
- If current response has no quota, app falls back to last snapshot and marks it as cached source in UI.

## UI Actions

- `全部签到`: sign in all enabled accounts and persist today sign-in state.
- `全部检测`: check all enabled accounts and update balance delta.
- Row action `复制APIKey`: copy all keys of that account (newline separated).
- Row action `检测`: run single-account check.

## Notes

- `session.json`, `quota_history.json`, and `signin_status.json` are intentionally ignored by git.
- If UI looks stale after update, restart backend and hard refresh browser (`Ctrl+F5`).

## Security

- Keep `session.json` local.
- Do not share `session` or API keys publicly.
