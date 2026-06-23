# qiandao 项目索引（供 AI 与维护者快速定位）

> 新对话优先把本文件和需求一起交给 AI。项目真实目录通常为 `D:\code\myweb\qiandao`。
> 本项目把后端集中在 `app.py`，把前端集中在 `templates/index.html`；修改账号字段时通常需要同时改这两个文件和对应测试。

## 1. 项目概览

- 用途：本地管理多个 new-api、sub2api 和自定义站点账号。
- 后端：Flask + requests，入口为 `app.py`。
- 前端：原生 HTML/CSS/JavaScript 单页应用，全部位于 `templates/index.html`。
- 默认地址：`http://127.0.0.1:5050`。
- 数据：全部保存在根目录 `data/`，该目录被 Git 忽略。
- 测试：`python -m pytest -q`。
- 启动：运行 `run_web.bat`；它会先终止占用 5050 端口的旧服务。

## 2. 根目录文件

| 文件 | 具体功能 | 修改提示 |
| --- | --- | --- |
| `app.py` | 整个 Flask 后端：配置读写、账号增删改查、签到、余额检测、令牌管理、地址备注、模型检测、JSON 导入及全部 API 路由。 | 后端功能的首要修改点，详见第 5 节。 |
| `templates/index.html` | 整个网页：CSS、页面结构、弹窗、前端状态、请求封装、账号/地址详情、令牌、签到及所有交互。 | UI 和浏览器行为的首要修改点，详见第 6 节。 |
| `static/favicon.svg` | 浏览器页签图标，蓝金色齿轮样式。 | 仅修改品牌图标时编辑。 |
| `README.md` | 面向使用者的安装、启动、功能与安全说明。 | 新增用户可见功能或改变数据文件时同步更新。 |
| `AI_PROJECT_INDEX.md` | 当前文件，面向后续 AI 的代码导航和修改地图。 | 目录、路由、数据归属或核心行为变化时同步更新。 |
| `.gitignore` | 忽略 Python 缓存、IDE 配置、`data/` 和日志。 | 不要把账号凭据或运行时缓存移出忽略范围。 |
| `run_web.bat` | Windows 启动脚本：查找 Python、终止 5050 端口旧进程、打开浏览器、运行 `app.py`。 | 启动端口或启动流程变化时修改。 |
| `run_web.exe` | 由启动器源码构建的可执行启动程序。 | 构建产物，不直接编辑。 |
| `run_web.lnk` | 指向启动程序的 Windows 快捷方式。 | 二进制/系统产物，不直接编辑。 |
| `qiandao.exe`、`qiandao.lnk` | 旧名称的启动器和快捷方式；当前工作区可能显示为已删除。 | 不要在未确认用户意图时恢复或提交删除。 |
| `build_log.txt` | 本地启动器构建日志。 | 生成文件，不作为业务源码。 |
| `.__script_to_exe_run_web_*.bat` | 脚本转 EXE 工具产生的临时批处理文件。 | 临时文件，不直接编辑。 |
| `_codex_marker.tmp` | 本地工具产生的临时标记文件。 | 临时文件，不直接编辑。 |

## 3. 目录与逐文件职责

### `tests/`

| 文件 | 覆盖内容 |
| --- | --- |
| `tests/test_accounts.py` | 账号字段校验、可选 `new_api_user`、账号备注保存/返回/导入保留、前端账号备注入口。 |
| `tests/test_signin_status.py` | 每日签到状态迁移、单个/全部检测后的签到状态、不可签到识别、批量签到过滤、分组交互。 |
| `tests/test_sites.py` | 地址备注独立存储、使用该地址第一个 new-api 账号请求模型、模型过滤与缓存。 |
| `tests/test_tokens.py` | 令牌分组/列表缓存、创建/删除/完整 key 获取、`sk-` 前缀、前端令牌布局与币种显示。 |

### `tools/`

| 文件 | 具体功能 |
| --- | --- |
| `tools/session_import_collector.user.js` | Tampermonkey 采集脚本：读取当前页面地址、localStorage、sessionStorage 和页面可见 Cookie，可合并 Cookie Editor JSON。不能直接读取 HttpOnly Cookie。 |
| `tools/qiandao_account_import_extension/manifest.json` | Chrome/Edge Manifest V3 配置，声明 cookies、scripting、activeTab、clipboardWrite、tabs 权限和站点访问权限。 |
| `tools/qiandao_account_import_extension/popup.html` | 浏览器扩展弹窗结构。 |
| `tools/qiandao_account_import_extension/popup.css` | 浏览器扩展弹窗样式。 |
| `tools/qiandao_account_import_extension/popup.js` | 扩展采集逻辑：读取当前标签页存储与 Cookie、识别 new-api/sub2api、调用自信息接口补全身份、复制或下载导入 JSON。 |
| `tools/qiandao_account_import_extension/README.md` | 扩展安装、兼容范围、使用方式和凭据安全说明。 |
| `tools/qiandao_account_import_extension/icons/icon16.svg` | 16px 扩展图标源文件。 |
| `tools/qiandao_account_import_extension/icons/icon48.svg` | 48px 扩展图标源文件。 |
| `tools/qiandao_account_import_extension/icons/icon128.svg` | 128px 扩展图标源文件。 |
| `tools/qiandao_account_import_extension/icons/icon16.png` | Manifest 实际引用的 16px PNG 图标。 |
| `tools/qiandao_account_import_extension/icons/icon48.png` | Manifest 实际引用的 48px PNG 图标。 |
| `tools/qiandao_account_import_extension/icons/icon128.png` | Manifest 实际引用的 128px PNG 图标。 |

### `build_artifacts/`

| 文件 | 具体功能 |
| --- | --- |
| `build_artifacts/launch_qiandao.py` | 启动器源码，功能与 `run_web.bat` 接近：终止旧服务、打开网页、启动 `app.py`。 |
| `build_artifacts/qiandao_launcher.spec` | PyInstaller 构建配置。 |
| `build_artifacts/pyinstaller_work/qiandao_launcher/Analysis-00.toc` | PyInstaller 分析阶段清单。 |
| `build_artifacts/pyinstaller_work/qiandao_launcher/EXE-00.toc` | EXE 构建清单。 |
| `build_artifacts/pyinstaller_work/qiandao_launcher/PKG-00.toc` | 打包内容清单。 |
| `build_artifacts/pyinstaller_work/qiandao_launcher/PYZ-00.pyz` | 打包后的 Python 模块归档。 |
| `build_artifacts/pyinstaller_work/qiandao_launcher/PYZ-00.toc` | PYZ 模块清单。 |
| `build_artifacts/pyinstaller_work/qiandao_launcher/qiandao_launcher.pkg` | PyInstaller 中间包。 |
| `build_artifacts/pyinstaller_work/qiandao_launcher/base_library.zip` | Python 标准库归档。 |
| `build_artifacts/pyinstaller_work/qiandao_launcher/warn-qiandao_launcher.txt` | 构建时缺失/可选模块警告。 |
| `build_artifacts/pyinstaller_work/qiandao_launcher/xref-qiandao_launcher.html` | 模块依赖交叉引用报告。 |
| `build_artifacts/pyinstaller_work/qiandao_launcher/localpycs/*.pyc` | PyInstaller 引导模块字节码。 |

以上 `pyinstaller_work` 内容都是可再生成的构建产物，通常不要手动修改。

### `data/`（本地运行时数据，禁止提交）

| 文件 | 数据归属 |
| --- | --- |
| `data/session.json` | 顶层默认地址和账号配置。账号字段包括 `account_index`、`name`、`enabled`、`provider`、`base_url`、`new_api_user`、`session`、`cookie`、`api_keys`、`remark`。账号备注保存在这里。 |
| `data/quota_history.json` | 每个账号的额度历史，用于计算与上次检测、昨天最后一次检测的差值。 |
| `data/signin_status.json` | 当天签到状态，以稳定账号序号为主要键；旧名称键会被迁移。 |
| `data/status_cache.json` | 最近一次成功账号检测结果和站点能力信息；失败检测不会覆盖这里的成功结果。 |
| `data/token_cache.json` | 令牌分组和令牌元数据缓存；完整 `sk-...` key 不持久化。 |
| `data/site_info.json` | 地址级备注、过滤后的模型列表、模型检测时间和失败状态。地址备注只保存在这里。 |
| `data/_patch_name_duplicate.py.tmp` | 旧修改过程遗留的临时文件，不参与运行。 |
| `data/modify_json_import.tmp.delete` | 旧修改过程遗留的临时文件，不参与运行。 |

### 工具/缓存目录

- `.git/`：Git 仓库元数据。
- `.idea/`：JetBrains IDE 本地配置。
- `.pytest_cache/`：pytest 缓存。
- `__pycache__/`：Python 字节码缓存。

## 4. 账号备注与地址备注的边界

- 账号备注：属于单个账号，字段为 `accounts[].remark`，保存在 `data/session.json`。
- 地址备注：属于同一 `base_url` 下的整个地址分组，保存在 `data/site_info.json` 的 `sites[base_url].remark`。
- 新增/编辑账号备注：修改 `parse_account_payload`、`normalize_account`、`to_public_account` 和前端 `f-remark` / `m-remark`。
- 地址备注：修改 `get_site_info`、`update_site_info`、`/api/sites/info` 和前端 `renderSiteDetail` / `saveSiteRemark`。
- JSON 导入更新已有账号时保留原账号备注，逻辑在 `merge_imported_account`。

## 5. `app.py` 后端定位地图

### 配置与本地数据

- 路径常量：文件顶部的 `DATA_DIR`、`CONFIG_PATH`、`HISTORY_PATH`、`SIGNIN_PATH`、`STATUS_CACHE_PATH`、`TOKEN_CACHE_PATH`、`SITE_INFO_PATH`。
- 初始化/迁移：`ensure_data_layout`、`ensure_config_normalized`。
- 原子 JSON 写入：`atomic_save_json`。
- 账号配置：`normalize_account`、`normalize_config`、`load_config`、`save_config`。
- 额度历史：`load_history`、`save_history`、`record_quota_snapshot_and_get_previous_change`、`build_yesterday_delta`。

### 账号字段与 API

- 输入校验：`validate_account_fields`、`parse_account_payload`。
- API 输出：`to_public_account`、`build_public_accounts`。
- 重复账号：`find_duplicate_account`、`ensure_unique_account`。
- 导入更新：`find_import_update_account`、`merge_imported_account`。
- 路由：
  - `GET /api/accounts`
  - `POST /api/accounts`
  - `POST /api/accounts/reorder`
  - `PUT /api/accounts/<account_index>`
  - `DELETE /api/accounts/<account_index>`

新增账号字段时，至少同步修改：

1. `normalize_account`
2. `parse_account_payload`
3. `to_public_account`
4. `templates/index.html` 的新增/编辑字段、`el`、`buildPayloadFromInputs`、`fillForm`
5. `tests/test_accounts.py`
6. `README.md` 与本索引

### 签到与状态检测

- 请求头：`build_headers`。
- new-api 自信息重试：`request_self_with_retry`。
- sub2api 自信息重试：`request_sub2api_self_with_retry`。
- 自定义 Cookie 站点：`build_custom_cookie_auth`、`classify_custom_cookie_checkin`、`request_custom_cookie_self_with_retry`。
- 签到判断：`classify_checkin`。
- 余额/账号状态：`check_status`。
- 不可签到：`checkin_response_unsupported`、`is_forced_unsupported_checkin_site`；账号级签到失败只写本账号，地址级 `手动签到` / `不可签到` 通过公开账号投影显示为 `不可签到`，不会覆盖原始今日手动标记。
- 地址级今日手动标记：`daily_signin_marked` 来自原始今日签到记录；前端地址 chip/card 读取该字段，账号行仍按地址能力显示 `不可签到`。
- 地址级签到能力检测：`POST /api/sites/checkin-status` 只在当前 `checkin_mode=enabled` 时写入检测结果；`manual` / `disabled` 不会被检测覆盖。
- 检测失败缓存：`set_status_cache` 只保存成功检测结果；前端会用 `statusErrors` 显示当前异常，同时右侧详情保留 `statusResults` / `last_status` 中的最后成功结果。
- 异常登录恢复：`POST /api/accounts/<account_index>/refresh-auth` 解析扩展采集 JSON，按账号序号更新同地址账号的登录信息，然后立即调用 `check_status` 重新检测。
- 扩展自动同步：`POST /api/auth/sync-account` 优先按地址和 `new_api_user` 匹配；已有账号更新并检测，新账号创建后签到并检测。
- 路由：
  - `POST /api/accounts/<account_index>/checkin`
  - `POST /api/accounts/checkin-all`
  - `POST /api/accounts/<account_index>/status`
  - `POST /api/accounts/status-all`
  - `POST /api/accounts/<account_index>/refresh-auth`

### 令牌管理

- 本地缓存：`load_token_cache`、`update_token_cache`、`cache_add_token`、`cache_delete_token`。
- 远端请求：`build_token_headers`、`fetch_remote_token_groups`、`fetch_remote_tokens`。
- 标准化：`normalize_token_groups`、`normalize_tokens`、`format_token_key`。
- 路由：
  - `GET /api/accounts/<account_index>/token-groups`
  - `GET /api/accounts/<account_index>/tokens`
  - `POST /api/accounts/<account_index>/tokens`
  - `DELETE /api/accounts/<account_index>/tokens/<token_id>`
  - `POST /api/accounts/<account_index>/tokens/<token_id>/key`

### 地址详情、备注与模型

- 地址数据：`load_site_info`、`get_site_info`、`update_site_info`。
- 选择检测账号：`first_account_for_site`、`first_new_api_account_for_site`。
- 模型请求/过滤：`fetch_site_models`、`filter_supported_models`。
- 路由：
  - `GET/PUT /api/sites/info`
  - `POST /api/sites/models`

### JSON 导入

- Cookie/Storage 解析：`json_import_cookies`、`json_import_storage_items`、`find_auth_token_from_storage`。
- 地址推断：`base_url_from_import_json`、`base_url_from_cookie_domains`。
- 账号构建：`build_auth_account`、`account_from_qiandao_import_field`、`build_auth_account_from_import_json`。
- 路由：`POST /api/auth/import-json`。

## 6. `templates/index.html` 前端定位地图

该文件按顺序包含 CSS、HTML、JavaScript。

### 关键状态

- `state.accounts`：公开账号列表。
- `state.selected`：当前单账号详情。
- `state.selectedSite`：当前地址详情。
- `state.signinStatus` / `state.statusResults` / `state.statusErrors`：签到状态、最后成功检测结果、当前检测异常结果。
- `state.tokenGroups` / `state.tokens` / `state.tokenLoading`：令牌状态。
- `state.siteInfo` / `state.siteLoading`：地址备注和模型状态。
- `state.collapsedGroups`：地址分组展开状态。

### 关键入口

- 账号表格：`renderTable`、`renderRow`、`renderGroupRow`。
- 单账号详情：`renderDetail`。
- 检测异常恢复：`buildAccountAuthRefreshUrl`、`openAccountAuthRefreshSite`，以及 `qiandao-auth-refreshed` message listener。
- 地址详情：`renderSiteDetail`。
- 单击地址/双击折叠：`selectSite` 和分组行事件。
- 新增/编辑账号：`openAddModal`、`resetModalForm`、`buildPayloadFromInputs`、`validatePayload`、`fillForm`、`saveForm`、`saveNewAccount`。
- JSON 导入：`importAccountJson`、`fillModalFromAuthAccount`。
- 令牌：`renderTokenPanel`、`loadTokenData`、`openTokenModal`、`createTokenFromModal`、`revealTokenKeys`。
- 地址备注/模型：`saveSiteRemark`、`loadSiteInfo`、`refreshSiteModels`。
- 自定义确认框：`showConfirmDialog`。
- 右上角提示：`notify`。

## 7. 常见需求应该修改哪里

| 需求 | 主要文件/函数 |
| --- | --- |
| 新增或修改账号字段 | `app.py` 的账号标准化/解析/公开输出；`index.html` 的两个表单和详情；`test_accounts.py` |
| 修改签到规则 | `classify_checkin`、签到路由、`test_signin_status.py`、前端按钮禁用逻辑 |
| 修改余额展示或币种 | `check_status`、额度历史函数、前端 `formatMoney`/指标卡、令牌测试中的币种用例 |
| 修改令牌创建/刷新/复制 | 后端 token helpers/routes、前端 token functions、`test_tokens.py` |
| 修改地址备注 | `update_site_info`、`/api/sites/info`、`renderSiteDetail`、`saveSiteRemark`、`test_sites.py` |
| 修改模型筛选 | `filter_supported_models`、`fetch_site_models`、地址模型前端、`test_sites.py` |
| 修改导入识别 | `build_auth_account_from_import_json` 及解析 helpers；扩展 `popup.js`；README/扩展 README |
| 修改整体布局/颜色/间距 | `templates/index.html` 顶部 CSS；完成后必须在浏览器检查宽屏和窄屏 |
| 修改启动方式/端口 | `run_web.bat`、`build_artifacts/launch_qiandao.py`、`app.py` 启动端口、README |

## 8. 修改与验证流程

```powershell
cd D:\code\myweb\qiandao
python -m pytest -q
.\run_web.bat
```

完成前至少检查：

1. `git status --short`，不要覆盖或提交用户已有的无关改动。
2. 运行完整 pytest。
3. 重启 5050 服务，浏览器访问 `http://127.0.0.1:5050`。
4. 涉及 UI 时实际操作新增、编辑、刷新和弹窗关闭流程。
5. 不读取、打印或提交 `data/session.json` 中的凭据。

## 9. 当前维护注意事项

- 工作区可能包含启动器重命名、扩展 manifest、PNG 图标和临时构建文件的用户改动；处理其他需求时不要回退这些变化。
- `app.py` 和 `templates/index.html` 都较大，优先按函数名搜索，不依赖容易漂移的行号。
- 账号稳定标识是 `account_index`；不要重新使用账号名作为唯一运行时键。
- 完整令牌只在远端 `/api/token/<id>/key` 返回后展示，并统一补 `sk-` 前缀；不要写入本地 token 缓存。
- 地址模型使用该地址下第一个 new-api 账号检测，过滤关键词为 `gpt-image-2`、`gpt`、`claude`、`gemini`。
