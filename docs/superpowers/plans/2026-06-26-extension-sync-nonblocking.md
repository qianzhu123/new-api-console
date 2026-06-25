# 插件账号同步非阻塞 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 本地账号保存成功后立即结束插件同步请求，把新账号签到和账号状态检测移到后台执行，避免插件永久停留在同步中。

**Architecture:** `POST /api/auth/sync-account` 继续负责解析、匹配和持久化账号，但不再直接调用远程签到或检测。保存后的账号副本交给守护线程运行 `run_synced_account_background_tasks()`；插件根据即时响应显示“已保存到本地、后台检测中”，不读取尚未产生的检测结果。

**Tech Stack:** Python 3、Flask、threading、pytest、Chrome Extension Manifest V3、原生 JavaScript。

---

### Task 1: 让同步接口保存后立即返回

**Files:**
- Modify: `tests/test_accounts.py`
- Modify: `app.py:3437-3507`

- [ ] **Step 1: 修改已有同步测试并加入调度断言**

已有账号测试替换 `schedule_synced_account_background_tasks`，记录账号和 `created` 参数；同时把 `fetch_public_status`、`check_status` 替换为抛错函数，证明请求线程不会调用它们。断言响应包含：

```python
assert payload["detection_pending"] is True
assert payload["result"] is None
assert scheduled == [(7, False)]
```

新账号测试同样替换调度器并断言：

```python
assert payload["detection_pending"] is True
assert payload["checkin_result"] is None
assert scheduled == [(1, True)]
```

- [ ] **Step 2: 运行两个测试并确认失败**

```powershell
python -m pytest -q tests/test_accounts.py::test_sync_import_updates_existing_account_by_base_url_and_user_id tests/test_accounts.py::test_sync_import_adds_new_account_then_checks_in_and_detects
```

Expected: FAIL，因为当前请求仍同步调用远程函数，且没有后台调度接口。

- [ ] **Step 3: 提取后台工作函数和守护线程调度器**

在 `app.py` 增加：

```python
def run_synced_account_background_tasks(account: dict[str, Any], created: bool) -> None:
    account = dict(account)
    account_index = int(account.get("account_index", 0) or 0)
    account_base_url = normalize_base_url(str(account.get("base_url") or get_base_url()))
    if created:
        checkin_result = classify_checkin(account)
        checkin_result["account_index"] = account_index
        persist_account_checkin_result(account, checkin_result)
    system_status = fetch_public_status(base_url=account_base_url)
    result = check_status(account, system_status=system_status)
    result["account_index"] = account_index
    signin_status = get_signin_status_today(str(account_index))
    if is_site_with_dedicated_checkin(account_base_url) and signin_status == "不可签到":
        signin_status = "未签到"
    result["signin_status"] = signin_status
    set_status_cache(str(account_index), result)


def schedule_synced_account_background_tasks(account: dict[str, Any], created: bool) -> None:
    worker = threading.Thread(
        target=run_synced_account_background_tasks,
        args=(dict(account), created),
        daemon=True,
        name=f"qiandao-sync-{account.get('account_index') or 'account'}",
    )
    worker.start()
```

后台函数捕获异常并写入包含 `status_state="BACKGROUND_ERROR"` 的状态缓存，避免线程异常直接输出未处理堆栈。

- [ ] **Step 4: 修改路由为调度后立即返回**

删除请求线程中的签到和检测调用，改为：

```python
schedule_synced_account_background_tasks(account, created)
action_note = "已创建新账号，本地保存完成，签到和检测正在后台执行" if created else "已更新现有账号，本地保存完成，重新检测正在后台执行"
```

响应返回 `detection_pending=True`、`checkin_result=None`、`result=None`、`system_status=None`。

- [ ] **Step 5: 运行同步接口测试**

```powershell
python -m pytest -q tests/test_accounts.py::test_sync_import_updates_existing_account_by_base_url_and_user_id tests/test_accounts.py::test_sync_import_adds_new_account_then_checks_in_and_detects
```

Expected: 2 passed。

### Task 2: 验证后台任务仍执行签到和检测

**Files:**
- Modify: `tests/test_accounts.py`
- Modify: `app.py`

- [ ] **Step 1: 写后台任务失败测试**

构造新账号，替换 `classify_checkin`、`fetch_public_status`、`check_status`，直接调用 `run_synced_account_background_tasks(account, True)`，断言：

```python
assert app.get_signin_status_today("1") == "已签到"
assert app.get_status_cache("1")["status_state"] == "VALID"
```

再增加异常测试，令 `fetch_public_status` 抛错，断言状态缓存为 `BACKGROUND_ERROR`，且函数不向调用方抛异常。

- [ ] **Step 2: 运行测试并确认失败**

```powershell
python -m pytest -q tests/test_accounts.py::test_synced_account_background_tasks_check_in_and_detect tests/test_accounts.py::test_synced_account_background_tasks_cache_unexpected_error
```

Expected: 在后台函数实现完成前失败。

- [ ] **Step 3: 完成异常状态缓存实现**

异常结果至少包含：

```python
{
    "account": account.get("name") or "unknown",
    "account_index": account_index,
    "status_state": "BACKGROUND_ERROR",
    "session_valid": False,
    "api_error": str(exc),
    "timestamp": now_ts(),
}
```

- [ ] **Step 4: 运行后台任务和账号测试**

```powershell
python -m pytest -q tests/test_accounts.py
```

Expected: 全部通过。

### Task 3: 修改插件即时成功状态

**Files:**
- Modify: `tests/test_accounts.py`
- Modify: `tools/qiandao_account_import_extension/popup.js:503-529`
- Modify: `tools/qiandao_account_import_extension/README.md`
- Modify: `README.md`
- Modify: `AI_PROJECT_INDEX.md`

- [ ] **Step 1: 写插件静态回归断言**

在 `test_extension_contains_refresh_to_local_action` 增加：

```python
assert "后台执行" in popup_js
assert "data.result || {}" not in popup_js
assert "result.session_valid" not in popup_js
assert "finally" in popup_js
```

- [ ] **Step 2: 运行测试并确认失败**

```powershell
python -m pytest -q tests/test_accounts.py::test_extension_contains_refresh_to_local_action
```

Expected: FAIL，因为当前插件仍读取即时 `result`。

- [ ] **Step 3: 修改插件成功提示**

成功响应后保留 `notifyQiandaoTabs()`，改为：

```javascript
const action = data.created
  ? `已添加账号 #${accountIndex} 到本地，签到和检测正在后台执行。`
  : `已更新账号 #${accountIndex} 到本地，重新检测正在后台执行。`;
setStatus(action, 'ok');
```

- [ ] **Step 4: 更新文档**

明确本地保存成功即结束插件等待；签到和检测在后台继续，不再阻塞扩展弹窗。

- [ ] **Step 5: 运行专项和完整验证**

```powershell
node --check tools/qiandao_account_import_extension/popup.js
python -m py_compile app.py
python -m pytest -q tests/test_accounts.py
python -m pytest -q
```

Expected: 账号测试全部通过；完整测试若仍仅有既有 token 操作列宽断言失败，则记录该基线问题。
