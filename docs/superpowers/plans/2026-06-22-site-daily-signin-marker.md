# Site Daily Sign-In Marker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate address sign-in capability from the address's daily manual completion marker so forced or manually disabled addresses retain `不可签到` while their compact manual marker updates reliably.

**Architecture:** Keep the existing per-account daily store, but expose an unnormalized address-level `daily_signin_marked` value that reads the raw records before capability rules are applied. Preserve user-selected `manual` and `disabled` modes during capability detection, and make the frontend consume the address marker directly instead of inferring it from public account status.

**Tech Stack:** Python 3, Flask, pytest, vanilla JavaScript, HTML/CSS, Codex in-app Browser

---

## File Map

- Modify `app.py`: add the raw address marker helper, decouple mode changes from daily status, preserve non-enabled modes during detection, and return the marker through existing site APIs.
- Modify `templates/index.html`: consume `daily_signin_marked`, separate manual mode from unsupported capability, and render a compact marker control for `manual` and `disabled` modes.
- Modify `tests/test_signin_status.py`: add backend route regressions and focused frontend contract assertions.
- Modify `README.md`: document the three modes, marker semantics, and detection preservation rule.
- Modify `AI_PROJECT_INDEX.md`: point future maintenance at the marker helper and the relevant routes/UI functions.

### Task 1: Expose an address-level daily marker without changing capability status

**Files:**
- Modify: `app.py:920-945`
- Modify: `app.py:2920-2960`
- Modify: `app.py:3290-3340`
- Test: `tests/test_signin_status.py`

- [ ] **Step 1: Write failing tests for forced-unsupported and disabled addresses**

Append these tests to `tests/test_signin_status.py`:

```python
def test_site_manual_signin_exposes_raw_marker_without_changing_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {
                    "account_index": 7,
                    "name": "forced-site-user",
                    "enabled": True,
                    "base_url": "https://api.e2ez.com",
                    "new_api_user": "7",
                    "session": "session-value-that-is-long-enough",
                }
            ]
        },
    )
    write_json(
        app.SITE_INFO_PATH,
        {"sites": {"https://api.e2ez.com": {"checkin_mode": "manual"}}},
    )

    with app.app.test_client() as client:
        response = client.post(
            "/api/sites/manual-signin",
            json={"base_url": "https://api.e2ez.com", "signed": True},
        )
        accounts_response = client.get("/api/accounts")

    assert response.status_code == 200
    assert response.get_json()["site"]["checkin_mode"] == "manual"
    assert response.get_json()["site"]["daily_signin_marked"] is True
    assert accounts_response.get_json()["accounts"][0]["signin_status"] == UNSUPPORTED


def test_disabled_site_manual_marker_does_not_change_public_signin_status(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {
                    "account_index": 8,
                    "name": "disabled-site-user",
                    "enabled": True,
                    "base_url": "https://disabled.example",
                    "new_api_user": "8",
                    "session": "session-value-that-is-long-enough",
                }
            ]
        },
    )
    write_json(
        app.SITE_INFO_PATH,
        {"sites": {"https://disabled.example": {"checkin_mode": "disabled"}}},
    )

    with app.app.test_client() as client:
        response = client.post(
            "/api/sites/manual-signin",
            json={"base_url": "https://disabled.example", "signed": True},
        )
        site_response = client.get(
            "/api/sites/info?base_url=https%3A%2F%2Fdisabled.example"
        )

    assert response.status_code == 200
    assert response.get_json()["site"]["checkin_mode"] == "disabled"
    assert site_response.get_json()["site"]["daily_signin_marked"] is True
    assert response.get_json()["accounts"][0]["signin_status"] == UNSUPPORTED
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_signin_status.py::test_site_manual_signin_exposes_raw_marker_without_changing_mode tests/test_signin_status.py::test_disabled_site_manual_marker_does_not_change_public_signin_status
```

Expected: both tests fail because `daily_signin_marked` is absent and `/api/sites/manual-signin` changes the mode to `manual`.

- [ ] **Step 3: Add the raw address marker helper**

Add immediately after `clear_site_signin_status_today` in `app.py`:

```python
def site_daily_signin_marked(base_url: str) -> bool:
    accounts = site_accounts_for_base_url(base_url)
    if not accounts:
        return False
    for account in accounts:
        account_index = int(account.get("account_index", 0) or 0)
        runtime_key = str(account_index) if account_index > 0 else str(account.get("name") or "")
        if not runtime_key or get_signin_status_today(runtime_key) != "已签到":
            return False
    return True
```

Add the field to the dictionary returned by `get_site_info`:

```python
        "daily_signin_marked": site_daily_signin_marked(normalized_url),
```

- [ ] **Step 4: Make the manual marker endpoint preserve the current mode**

Replace `site_manual_signin` in `app.py` with:

```python
@app.route("/api/sites/manual-signin", methods=["POST"])
def site_manual_signin():
    payload = request.get_json(force=True)
    base_url = str(payload.get("base_url") or "").strip() if isinstance(payload, dict) else ""
    signed = bool(payload.get("signed", False)) if isinstance(payload, dict) else False
    if not base_url:
        return jsonify({"ok": False, "error": "base_url is required"}), 400
    if not site_accounts_for_base_url(base_url):
        return jsonify({"ok": False, "error": "site has no accounts"}), 404
    if signed:
        set_site_signin_status_today(base_url, "已签到")
    else:
        clear_site_signin_status_today(base_url, only_status="已签到")
    return jsonify({
        "ok": True,
        "site": get_site_info(base_url),
        "accounts": build_public_accounts(load_config().get("accounts", [])),
    })
```

- [ ] **Step 5: Stop disabled mode writes from overwriting the independent marker**

In the `PUT /api/sites/info` branch, replace the mode/status coupling with:

```python
    if has_checkin_mode and site.get("checkin_mode") in ("enabled", "manual"):
        clear_site_signin_status_today(base_url, only_status="不可签到")
```

This intentionally performs no per-account daily-status write when the new mode is `disabled`; `build_public_accounts` already projects `不可签到` from the address mode.

- [ ] **Step 6: Run the focused tests and verify GREEN**

Run the Step 2 command again.

Expected: `2 passed`.

- [ ] **Step 7: Commit the marker separation**

```powershell
git add app.py tests/test_signin_status.py
git commit -m "Fix address daily sign-in marker state"
```

### Task 2: Preserve manual and disabled modes during capability detection

**Files:**
- Modify: `app.py:3335-3360`
- Test: `tests/test_signin_status.py`

- [ ] **Step 1: Write parameterized failing tests for mode preservation**

Add `import pytest` beside the existing imports at the top of `tests/test_signin_status.py`, then append:

```python
@pytest.mark.parametrize("mode", ["manual", "disabled"])
def test_site_checkin_detection_preserves_non_enabled_mode(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(
        app.CONFIG_PATH,
        {
            "accounts": [
                {
                    "account_index": 9,
                    "name": "preserved-mode-user",
                    "enabled": True,
                    "base_url": "https://preserve.example",
                    "new_api_user": "9",
                    "session": "session-value-that-is-long-enough",
                }
            ]
        },
    )
    write_json(
        app.SITE_INFO_PATH,
        {"sites": {"https://preserve.example": {"checkin_mode": mode}}},
    )
    app.set_site_signin_status_today("https://preserve.example", SIGNED)
    monkeypatch.setattr(
        app,
        "fetch_public_status",
        lambda base_url=None: {"ok": True, "checkin_enabled": mode == "disabled"},
    )

    with app.app.test_client() as client:
        response = client.post(
            "/api/sites/checkin-status",
            json={"base_url": "https://preserve.example"},
        )

    assert response.status_code == 200
    assert response.get_json()["site"]["checkin_mode"] == mode
    assert response.get_json()["site"]["daily_signin_marked"] is True
```

- [ ] **Step 2: Write a failing test proving enabled mode still updates**

Append:

```python
def test_site_checkin_detection_updates_enabled_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    write_json(app.CONFIG_PATH, {"accounts": []})
    write_json(
        app.SITE_INFO_PATH,
        {"sites": {"https://enabled.example": {"checkin_mode": "enabled"}}},
    )
    monkeypatch.setattr(
        app,
        "fetch_public_status",
        lambda base_url=None: {"ok": True, "checkin_enabled": False},
    )

    with app.app.test_client() as client:
        response = client.post(
            "/api/sites/checkin-status",
            json={"base_url": "https://enabled.example"},
        )

    assert response.status_code == 200
    assert response.get_json()["site"]["checkin_mode"] == "disabled"
```

- [ ] **Step 3: Run detection tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_signin_status.py::test_site_checkin_detection_preserves_non_enabled_mode tests/test_signin_status.py::test_site_checkin_detection_updates_enabled_mode
```

Expected: the parameterized preservation cases fail because the route rewrites both modes; the enabled-mode case passes.

- [ ] **Step 4: Preserve non-enabled modes in the detection route**

Replace `site_checkin_status` in `app.py` with:

```python
@app.route("/api/sites/checkin-status", methods=["POST"])
def site_checkin_status():
    payload = request.get_json(force=True)
    base_url = str(payload.get("base_url") or "").strip() if isinstance(payload, dict) else ""
    if not base_url:
        return jsonify({"ok": False, "error": "base_url is required"}), 400
    normalized = normalize_base_url(base_url)
    current_mode = normalize_site_checkin_mode(get_site_info(normalized).get("checkin_mode"))
    system_status = fetch_public_status(base_url=normalized)
    disabled = is_forced_unsupported_checkin_site(normalized) or system_status.get("checkin_enabled") is False
    if current_mode == "enabled":
        site = update_site_info(normalized, checkin_mode="disabled" if disabled else "enabled")
        if not disabled:
            clear_site_signin_status_today(normalized, only_status="不可签到")
    else:
        site = get_site_info(normalized)
    return jsonify({
        "ok": True,
        "site": site,
        "system_status": system_status,
        "accounts": build_public_accounts(load_config().get("accounts", [])),
    })
```

- [ ] **Step 5: Run focused detection tests and the full status test module**

Run:

```powershell
python -m pytest -q tests/test_signin_status.py::test_site_checkin_detection_preserves_non_enabled_mode tests/test_signin_status.py::test_site_checkin_detection_updates_enabled_mode
python -m pytest -q tests/test_signin_status.py
```

Expected: focused tests pass; the full module passes with no failures.

- [ ] **Step 6: Commit detection preservation**

```powershell
git add app.py tests/test_signin_status.py
git commit -m "Preserve explicit site sign-in modes"
```

### Task 3: Render compact marker controls and correct group semantics

**Files:**
- Modify: `templates/index.html:429-434`
- Modify: `templates/index.html:1940-2010`
- Modify: `templates/index.html:2055-2140`
- Modify: `templates/index.html:2745-2790`
- Modify: `templates/index.html:2860-2890`
- Test: `tests/test_signin_status.py`

- [ ] **Step 1: Write failing frontend contract assertions**

Add this test to `tests/test_signin_status.py`:

```python
def test_frontend_uses_address_marker_and_separates_manual_from_unsupported():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "siteInfoForBaseUrl(baseUrl).daily_signin_marked" in template
    assert "checkinMode !== 'enabled'" in template
    assert "data-toggle-manual-signin" in template
    assert "siteCheckinManual(baseUrl)) return true" not in template
    assert "manualCheckin" in template
    assert "手动签到" in template
```

- [ ] **Step 2: Run the frontend contract test and verify RED**

Run:

```powershell
python -m pytest -q tests/test_signin_status.py::test_frontend_uses_address_marker_and_separates_manual_from_unsupported
```

Expected: failure because the marker is still inferred from account statuses and manual mode is still treated as unsupported.

- [ ] **Step 3: Read the independent address marker in JavaScript**

Replace `siteManualSigninSigned` with:

```javascript
function siteManualSigninSigned(baseUrl) {
  return siteInfoForBaseUrl(baseUrl).daily_signin_marked === true;
}
```

Replace `toggleManualSignin` with:

```javascript
async function toggleManualSignin(baseUrl) {
  const normalized = normalizeBaseUrlInput(baseUrl);
  const signed = !siteManualSigninSigned(normalized);
  const data = await api('/api/sites/manual-signin', {
    method: 'POST',
    body: JSON.stringify({ base_url: normalized, signed }),
  });
  state.siteInfo[normalized] = data.site || state.siteInfo[normalized] || {};
  notify('ok', signed ? '已标记今日已签到' : '已取消今日签到标记', normalized);
  renderTable();
  renderDetail();
}
```

- [ ] **Step 4: Separate manual mode from unsupported capability**

Replace the first condition in `accountCheckinUnsupported` with:

```javascript
  if (isForcedUnsupportedCheckinSite(baseUrl) || siteCheckinDisabled(baseUrl)) return true;
```

In `renderGroupRow`, define action state before assigning `tr.innerHTML`:

```javascript
  const manualCheckin = siteCheckinManual(group.baseUrl);
  const checkinActionDisabled = stats.checkinUnsupported || manualCheckin;
  const checkinActionLabel = stats.checkinUnsupported ? '不可签到' : (manualCheckin ? '手动签到' : '全部签到');
  const checkinActionTitle = stats.checkinUnsupported ? '该网站不支持签到' : (manualCheckin ? '该地址使用手动签到' : '');
```

Replace the group check-in button with:

```html
<button type="button" data-group-action="checkin" data-group-key="${key}" ${checkinActionDisabled ? 'disabled title="' + checkinActionTitle + '"' : ''}>${checkinActionLabel}</button>
```

In `renderTable`, replace the account-row check-in state block with:

```javascript
      const manualCheckin = siteCheckinManual(acc.base_url || state.defaultBaseUrl);
      const accountUnsupported = accountCheckinUnsupported(acc);
      const checkinDisabled = groupCheckinUnsupported || accountUnsupported || manualCheckin;
      if (groupCheckinUnsupported || accountUnsupported) rowSum.checkinText = '不可签到';
      const checkinLabel = groupCheckinUnsupported || accountUnsupported
        ? '不可签到'
        : (manualCheckin ? '手动签到' : (activeAction === 'checkin' ? '签到中' : '签到'));
```

- [ ] **Step 5: Show the compact marker control for both non-enabled modes**

Replace the manual card conditional in `renderSiteDetail` with:

```javascript
      ${checkinMode !== 'enabled' ? `<div class="manual-signin-card compact">
        <div class="manual-title">今日手动标记</div>
        <button type="button" class="manual-toggle-button compact ${siteManualSigninSigned(baseUrl) ? 'signed' : ''}" data-toggle-manual-signin>
          <span class="manual-toggle-dot"></span>${siteManualSigninSigned(baseUrl) ? '今日已签到' : '标记今日已签到'}
        </button>
      </div>` : ''}
```

Add these declarations beside the existing `.manual-signin-card` styles:

```css
.manual-signin-card.compact { padding:6px 8px; min-height:0; border-radius:10px; }
.manual-signin-card.compact .manual-title { font-size:12px; }
.manual-toggle-button.compact { padding:5px 8px; min-height:28px; font-size:12px; border-radius:8px; }
```

- [ ] **Step 6: Keep the detection result message truthful when mode is preserved**

In `detectSiteCheckinStatus`, replace the notification calculation with:

```javascript
    const mode = siteCheckinMode(normalized);
    const detectedDisabled = isForcedUnsupportedCheckinSite(normalized) || data.system_status?.checkin_enabled === false;
    const detectionText = mode === 'enabled'
      ? (detectedDisabled ? '不可签到' : '可以签到')
      : `${mode === 'manual' ? '手动签到' : '不可签到'}（设置保持不变）`;
    notify(detectedDisabled ? 'warn2' : 'ok', '签到状态检测完成', `${normalized}：${detectionText}。`);
```

- [ ] **Step 7: Run frontend and full status tests**

Run:

```powershell
python -m pytest -q tests/test_signin_status.py::test_frontend_uses_address_marker_and_separates_manual_from_unsupported
python -m pytest -q tests/test_signin_status.py
```

Expected: both commands pass.

- [ ] **Step 8: Commit the frontend behavior**

```powershell
git add templates/index.html tests/test_signin_status.py
git commit -m "Refine address sign-in controls"
```

### Task 4: Synchronize documentation and run complete verification

**Files:**
- Modify: `README.md:103-110`
- Modify: `AI_PROJECT_INDEX.md:145-155`
- Verify: `app.py`, `templates/index.html`, `tests/test_signin_status.py`

- [ ] **Step 1: Update README behavior documentation**

Replace the current sign-in mode bullets with text covering these exact rules:

```markdown
- Address sign-in mode and today's manual completion marker are independent. `可以签到` participates in automatic and batch sign-in; `手动签到` and `不可签到` expose a compact daily marker control but never participate in automatic sign-in.
- A manual marker updates the address's manual chip. An address set to `不可签到` continues to display `不可签到` in account and group sign-in status even after the daily marker is set.
- Sign-in capability detection may update an address only while its current mode is `可以签到`. Explicit `手动签到` and `不可签到` choices are preserved.
```

- [ ] **Step 2: Update the project index maintenance pointers**

Document these symbols and routes in `AI_PROJECT_INDEX.md`:

```markdown
- 地址今日手动标记：`site_daily_signin_marked`、`set_site_signin_status_today`、`POST /api/sites/manual-signin`；原始标记与公开的 `不可签到` 状态分离。
- 地址签到能力检测：`POST /api/sites/checkin-status` 仅在当前 `checkin_mode=enabled` 时修改设置，保留 `manual` 与 `disabled`。
- 前端地址控件：`siteManualSigninSigned`、`toggleManualSignin`、`accountCheckinUnsupported`、`renderSiteDetail`。
```

- [ ] **Step 3: Run syntax and focused regression checks**

Run:

```powershell
python -m py_compile app.py
python -m pytest -q tests/test_signin_status.py
```

Expected: compilation succeeds and the status module passes.

- [ ] **Step 4: Run the full repository test suite**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass with no failures.

- [ ] **Step 5: Restart the local Flask process from this checkout**

Stop only the Python process whose command line is `python app.py` and whose listening port is `5050`, then launch from `D:\code\myweb\qiandao`:

```powershell
Start-Process -FilePath python -ArgumentList 'app.py' -WorkingDirectory 'D:\code\myweb\qiandao' -WindowStyle Hidden
```

Verify `http://127.0.0.1:5050/api/accounts` returns HTTP 200 before browser testing.

- [ ] **Step 6: Verify the rendered flow with the in-app Browser**

The flow under test is: `http://127.0.0.1:5050` -> open `https://api.e2ez.com` address details -> toggle the compact daily marker -> observe the left address chip update while unsupported status remains correct.

Perform and record:

1. Page URL and title identify the local console.
2. DOM snapshot contains the populated address list and no framework error overlay.
3. Console has no relevant warnings or errors.
4. `api.e2ez.com` in `manual` mode changes between `今日未签到` and `今日已签到` immediately and after reload.
5. In `disabled` mode, the compact button changes state while group/account status remains `不可签到`.
6. Detecting status in `manual` and `disabled` modes leaves the selected mode unchanged.
7. Detecting status in `enabled` mode retains the existing capability-update behavior.
8. Capture a desktop screenshot showing the compact control and corresponding left-column state.

- [ ] **Step 7: Commit documentation changes**

```powershell
git add README.md AI_PROJECT_INDEX.md
git commit -m "Document address daily sign-in markers"
```

- [ ] **Step 8: Confirm the final worktree state**

Run:

```powershell
git status --short
git log -5 --oneline
```

Expected: the worktree is clean and the marker, detection, frontend, and documentation commits are present.
