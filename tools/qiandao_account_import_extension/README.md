# qiandao Account Import Helper

本目录是一个 Chrome / Edge Manifest V3 浏览器插件，用于在当前已登录网站中采集 qiandao 可直接导入的账号 JSON。

## 可行性结论

可行。浏览器插件拥有 `cookies` 权限后，可以通过 Chrome/Edge 扩展 API 读取当前站点 Cookie，包括页面 JavaScript 和油猴脚本无法读取的 HttpOnly Cookie。因此它可以直接生成包含 new-api `session` 或 sub2api Bearer Token 的完整导入 JSON。

## 兼容范围

只面向：

- new-api：读取 `session` Cookie，优先读取 `localStorage.user`，缺失时尝试请求 `/api/user/self` 补全用户 ID。
- sub2api：读取 `localStorage.auth_token` 和 `localStorage.auth_user`，缺失用户信息时尝试请求 `/api/v1/auth/me` 补全。

## 安装方式

1. 打开 Chrome / Edge 扩展管理页：
   - Chrome: `chrome://extensions/`
   - Edge: `edge://extensions/`
2. 开启“开发者模式”。
3. 点击“加载已解压的扩展程序”。
4. 选择本目录：

```text
D:\code\myweb\qiandao\tools\qiandao_account_import_extension
```

## 使用方式

1. 打开并登录目标 new-api/sub2api 网站。
2. 点击浏览器工具栏里的 `qiandao 导入` 扩展图标。
3. 点击“采集当前页”。
4. 插件会展示：
   - 站点
   - 识别类型
   - 账号
   - 用户 ID
   - 会话字段
5. 点击“复制导入 JSON”。
6. 回到本地 qiandao：

```text
添加账号 -> JSON 导入添加 -> 粘贴 -> 从 JSON 解析并回填 -> 创建账号
```

## 导出内容

导出的 JSON 会包含：

- `origin` / `base_url` / `page`
- `storageScan.localStorage`
- `cookieEditorCookies` / `cookies`
- `detected`
- `qiandaoAccount`

`qiandaoAccount` 是给人看的预览字段；后端仍会从 Cookie 和 Storage 中重新解析，保证和现有导入逻辑兼容。

## 安全注意

导出的 JSON 可能包含登录 session 或 Bearer Token，等同登录凭证。请勿分享给他人，不要上传到公网。
