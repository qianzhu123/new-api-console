# 不可签到地址清除手动标记 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 地址保存为“不可签到”时清除当天手动签到标记，并确保只有“手动签到”模式展示地址标记和操作按钮。

**Architecture:** 后端在 `PUT /api/sites/info` 保存 `checkin_mode=disabled` 后，清除该地址账号当天的 `已签到` 原始记录，并重新读取地址信息后返回，保证响应中的 `daily_signin_marked` 已变为 `false`。前端把地址 chip 和详情按钮的渲染条件统一收紧为 `manual`，不改变账户公开签到状态、签到能力检测或可用数统计。

**Tech Stack:** Python 3、Flask、pytest、原生 JavaScript/HTML。

---

## 文件结构

- `tests/test_signin_status.py`：增加后端清除标记和前端显示边界的回归测试。
- `app.py`：在地址模式保存接口中处理 `disabled` 的当天标记清除，并返回清除后的地址信息。
- `templates/index.html`：仅为 `manual` 模式渲染地址标记和详情按钮。
- `README.md`、`AI_PROJECT_INDEX.md`：同步最终行为说明。

### Task 1: 后端在切换为不可签到时清除当天标记

**Files:**
- Modify: `tests/test_signin_status.py`
- Modify: `app.py:3313-3341`

- [ ] **Step 1: 写入失败测试**

在 `tests/test_signin_status.py` 增加：

```python
def test_site_info_disabled_mode_clears_daily_manual_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_PATH", tmp_path / "session.json")
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    monkeypatch.setattr(app, "SITE_INFO_PATH", tmp_path / "site_info.json")
    base_url = "https://disable-marker.example.test"
    write_json(
        app.CONFIG_PATH,
        {"accounts": [{"account_index": 41, "name": "manual", "enabled": True, "base_url": base_url}]},
    )
    write_json(app.SITE_INFO_PATH, {"sites": {base_url: {"checkin_mode": "manual"}}})
    app.set_signin_status_today("41", SIGNED)

    with app.app.test_client() as client:
        response = client.put(
            "/api/sites/info",
            json={"base_url": base_url, "checkin_mode": "disabled"},
        )

    assert response.status_code == 200
    assert response.get_json()["site"]["checkin_mode"] == "disabled"
    assert response.get_json()["site"]["daily_signin_marked"] is False
    assert app.get_signin_status_today("41") == UNSIGNED
```

- [ ] **Step 2: 运行测试并确认正确失败**

Run:

```powershell
python -m pytest -q tests/test_signin_status.py::test_site_info_disabled_mode_clears_daily_manual_marker
```

Expected: FAIL，因为当前接口不会在 `disabled` 模式下清除 `已签到`，且响应仍包含旧的 `daily_signin_marked=true`。

- [ ] **Step 3: 实现最小后端修改**

将地址保存后的分支改为：

```python
site = update_site_info(
    base_url,
    remark=remark,
    special_info=special_info,
    display_color=display_color,
    pinned=pinned,
    checkin_mode=checkin_mode,
)
if has_checkin_mode and site.get("checkin_mode") in ("enabled", "manual"):
    clear_site_signin_status_today(base_url, only_status="不可签到")
elif has_checkin_mode and site.get("checkin_mode") == "disabled":
    clear_site_signin_status_today(base_url, only_status="已签到")
site = get_site_info(base_url)
```

重新读取 `site` 是必要的，因为首次 `update_site_info()` 在清除动作前计算了 `daily_signin_marked`。

- [ ] **Step 4: 运行后端相关测试**

Run:

```powershell
python -m pytest -q tests/test_signin_status.py::test_site_info_disabled_mode_clears_daily_manual_marker tests/test_signin_status.py::test_manual_marker_for_manual_site_preserves_public_unsupported_status tests/test_signin_status.py::test_site_checkin_status_preserves_explicit_manual_mode_and_daily_marker
```

Expected: 3 passed。

- [ ] **Step 5: 提交后端修改**

```powershell
git add app.py tests/test_signin_status.py
git commit -m "Clear manual marker for disabled sites"
```

### Task 2: 仅手动签到模式展示标记

**Files:**
- Modify: `tests/test_signin_status.py:725-732`
- Modify: `templates/index.html:1950-1954`
- Modify: `templates/index.html:2881-2886`

- [ ] **Step 1: 将现有前端回归测试改为目标行为**

```python
def test_frontend_only_manual_sites_show_daily_marker():
    template = (app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "siteInfoForBaseUrl(baseUrl).daily_signin_marked === true" in template
    assert "siteCheckinManual(baseUrl)) return true" in template
    assert "if (!siteCheckinManual(baseUrl)) return '';" in template
    assert "siteCheckinDisabled(baseUrl) ? '手动标记' : '手动签到'" not in template
    assert "checkinMode === 'manual'" in template
    assert "checkinMode !== 'enabled'" not in template
```

- [ ] **Step 2: 运行测试并确认正确失败**

Run:

```powershell
python -m pytest -q tests/test_signin_status.py::test_frontend_only_manual_sites_show_daily_marker
```

Expected: FAIL，因为模板当前明确允许 `disabled` 渲染 chip，并使用 `checkinMode !== 'enabled'` 渲染详情按钮。

- [ ] **Step 3: 收紧前端渲染条件**

将 `siteManualChip()` 改为：

```javascript
function siteManualChip(baseUrl) {
  if (!siteCheckinManual(baseUrl)) return '';
  const signed = siteManualSigninSigned(baseUrl);
  return `<span class="site-manual-chip ${signed ? 'signed' : ''}" title="手动签到：${signed ? '今日已标记签到' : '今日未标记签到'}"><span class="today-dot"></span>手动签到 · ${signed ? '今日已签到' : '今日未签到'}</span>`;
}
```

将详情控件条件改为：

```javascript
${checkinMode === 'manual' ? `<div class="manual-signin-card">
```

- [ ] **Step 4: 运行前端模板测试**

Run:

```powershell
python -m pytest -q tests/test_signin_status.py::test_frontend_only_manual_sites_show_daily_marker
```

Expected: 1 passed。

- [ ] **Step 5: 提交前端修改**

```powershell
git add templates/index.html tests/test_signin_status.py
git commit -m "Hide manual marker for disabled sites"
```

### Task 3: 同步文档并完成回归验证

**Files:**
- Modify: `README.md:112-115`
- Modify: `AI_PROJECT_INDEX.md:149-151`

- [ ] **Step 1: 更新行为说明**

README 明确说明：

```markdown
- `手动签到` skips automatic sign-in and exposes the compact daily manual marker.
- `不可签到` skips automatic sign-in, hides the manual marker, and clears that address's current-day manual marker when saved.
```

项目索引明确记录 `PUT /api/sites/info` 在保存 `disabled` 时清除当天 `已签到` 标记，前端仅 `manual` 模式读取并展示 `daily_signin_marked`。

- [ ] **Step 2: 运行专项测试**

Run:

```powershell
python -m pytest -q tests/test_signin_status.py
```

Expected: 全部通过。

- [ ] **Step 3: 运行完整测试**

Run:

```powershell
python -m pytest -q
```

Expected: 新增和既有签到测试通过；若仍只有既有 token 列宽断言失败，记录为与本修改无关的基线问题。

- [ ] **Step 4: 浏览器验证**

启动本地应用后验证：

1. 把一个“手动签到”地址标记为“今日已签到”。
2. 将签到设置保存为“不可签到”。
3. 确认左侧地址 chip 和右侧手动标记按钮立即消失。
4. 切回“手动签到”，确认显示“今日未签到”。
5. 确认地址和账号仍显示“不可签到”，账户可用数逻辑未回退。

- [ ] **Step 5: 提交文档和最终修改**

```powershell
git add README.md AI_PROJECT_INDEX.md
git commit -m "Document disabled sign-in marker behavior"
```
