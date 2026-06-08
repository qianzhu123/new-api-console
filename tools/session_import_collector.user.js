// ==UserScript==
// @name         qiandao 账号导入 JSON 采集器
// @namespace    local.qiandao.import.collector
// @version      2.0.0
// @description  采集当前网站 origin/page/localStorage/sessionStorage，并可合并 Cookie Editor 导出的 Cookie JSON，复制后可直接粘贴到 qiandao 添加账号 JSON 导入。
// @author       local
// @match        *://*/*
// @run-at       document-idle
// @grant        GM_registerMenuCommand
// @grant        GM_setClipboard
// ==/UserScript==

(function () {
  'use strict';

  let panel = null;
  let floatingButton = null;
  let lastOutput = null;

  function safeJsonParse(text) {
    try { return { ok: true, value: JSON.parse(text) }; }
    catch (err) { return { ok: false, error: String(err) }; }
  }

  function collectStorage(storage, storageName) {
    const items = [];
    try {
      for (let i = 0; i < storage.length; i++) {
        const key = storage.key(i);
        const rawValue = storage.getItem(key);
        const parsed = safeJsonParse(rawValue);
        items.push({
          key,
          value: parsed.ok ? parsed.value : rawValue
        });
      }
      return { storageName, matchedCount: items.length, items };
    } catch (err) {
      return { storageName, error: String(err), matchedCount: items.length, items };
    }
  }

  function collectVisibleCookies() {
    const rows = document.cookie
      ? document.cookie.split(';').map(x => x.trim()).filter(Boolean)
      : [];
    return rows.map(item => {
      const index = item.indexOf('=');
      const name = index >= 0 ? item.slice(0, index) : item;
      const value = index >= 0 ? item.slice(index + 1) : '';
      return { name, value };
    });
  }

  function normalizeCookieEditorInput(input) {
    if (!input) return [];
    const parsed = typeof input === 'string' ? safeJsonParse(input.trim()) : { ok: true, value: input };
    if (!parsed.ok) throw new Error('Cookie Editor 内容不是有效 JSON：' + parsed.error);
    const value = parsed.value;
    if (Array.isArray(value)) return value;
    if (value && typeof value === 'object') {
      if (Array.isArray(value.cookies)) return value.cookies;
      if (Array.isArray(value.cookieEditorCookies)) return value.cookieEditorCookies;
      if (Array.isArray(value.httpOnlyCookies)) return value.httpOnlyCookies;
    }
    throw new Error('未识别 Cookie Editor 导出格式。请复制 Cookie Editor 导出的数组 JSON，或 {"cookies":[...]}。');
  }

  function buildOutput(extraCookies) {
    const cookieEditorCookies = Array.isArray(extraCookies) ? extraCookies : [];
    return {
      format: 'qiandao-account-import',
      version: 2,
      origin: location.origin,
      page: location.href,
      time: new Date().toISOString(),
      storageScan: {
        localStorage: collectStorage(localStorage, 'localStorage'),
        sessionStorage: collectStorage(sessionStorage, 'sessionStorage')
      },
      visibleCookies: {
        note: 'document.cookie 可见 Cookie。HttpOnly Cookie 请通过 Cookie Editor 导出后合并到 cookieEditorCookies。',
        count: collectVisibleCookies().length,
        cookies: collectVisibleCookies()
      },
      cookieEditorCookies,
      importHints: {
        newApi: 'new-api 需要 Cookie Editor 导出的 session Cookie + localStorage.user.id。',
        sub2api: 'sub2api 通常需要 localStorage.auth_token + auth_user。',
        target: '复制本 JSON 后，粘贴到 qiandao -> 添加账号 -> JSON 导入添加。'
      }
    };
  }

  function copyText(text) {
    if (typeof GM_setClipboard === 'function') {
      GM_setClipboard(text);
      return Promise.resolve();
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0;';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const ok = document.execCommand('copy');
    textarea.remove();
    if (!ok) throw new Error('复制失败');
    return Promise.resolve();
  }

  function buttonStyle(bg) {
    return `background:${bg};color:white;border:0;border-radius:7px;padding:6px 10px;cursor:pointer;font-size:12px;`;
  }

  function createPanel() {
    if (panel) panel.remove();
    panel = document.createElement('div');
    panel.style.cssText = `
      position:fixed;right:20px;bottom:78px;z-index:2147483647;width:720px;max-width:calc(100vw - 40px);
      max-height:78vh;overflow:auto;background:#111827;color:#e5e7eb;border:1px solid #374151;border-radius:12px;
      box-shadow:0 10px 40px rgba(0,0,0,.38);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
      font-size:12px;line-height:1.5;padding:12px;box-sizing:border-box;white-space:pre-wrap;`;
    document.body.appendChild(panel);
    return panel;
  }

  function renderPanel(output, message) {
    lastOutput = output;
    const p = createPanel();
    p.textContent = '';
    const bar = document.createElement('div');
    bar.style.cssText = 'position:sticky;top:0;display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;background:#111827;padding-bottom:8px;margin-bottom:8px;border-bottom:1px solid #374151;z-index:1;';

    const copyBtn = document.createElement('button');
    copyBtn.textContent = '复制导入 JSON';
    copyBtn.style.cssText = buttonStyle('#16a34a');
    copyBtn.onclick = async () => {
      await copyText(JSON.stringify(lastOutput, null, 2));
      copyBtn.textContent = '已复制';
      setTimeout(() => copyBtn.textContent = '复制导入 JSON', 1200);
    };

    const mergeBtn = document.createElement('button');
    mergeBtn.textContent = '粘贴 Cookie Editor JSON 合并';
    mergeBtn.style.cssText = buttonStyle('#9333ea');
    mergeBtn.onclick = showCookieEditorMergeBox;

    const refreshBtn = document.createElement('button');
    refreshBtn.textContent = '重新采集';
    refreshBtn.style.cssText = buttonStyle('#2563eb');
    refreshBtn.onclick = () => renderPanel(buildOutput(lastOutput?.cookieEditorCookies || []), '已重新采集。');

    const closeBtn = document.createElement('button');
    closeBtn.textContent = '关闭';
    closeBtn.style.cssText = buttonStyle('#dc2626');
    closeBtn.onclick = () => { if (panel) { panel.remove(); panel = null; } };

    bar.append(copyBtn, mergeBtn, refreshBtn, closeBtn);
    p.appendChild(bar);

    const tip = document.createElement('div');
    tip.style.cssText = 'margin-bottom:8px;color:#fde68a;white-space:pre-wrap;';
    tip.textContent = message || '已生成 qiandao 导入 JSON。';
    p.appendChild(tip);

    const pre = document.createElement('pre');
    pre.style.cssText = 'white-space:pre-wrap;word-break:break-word;margin:0;';
    pre.textContent = JSON.stringify(output, null, 2);
    p.appendChild(pre);
  }

  function showCookieEditorMergeBox() {
    const p = createPanel();
    p.textContent = '';

    const title = document.createElement('div');
    title.style.cssText = 'font-weight:700;margin-bottom:8px;color:#fde68a;';
    title.textContent = '粘贴 Cookie Editor 导出的 Cookie JSON';

    const desc = document.createElement('div');
    desc.style.cssText = 'margin-bottom:8px;color:#d1d5db;white-space:pre-wrap;';
    desc.textContent = '用 Cookie Editor 在当前网站导出 Cookies，粘贴到下面。必须包含 new-api 的 session Cookie。合并后复制生成的 JSON 到 qiandao 导入。';

    const textarea = document.createElement('textarea');
    textarea.style.cssText = 'width:100%;height:180px;background:#0b1220;color:#e5e7eb;border:1px solid #374151;border-radius:8px;padding:8px;box-sizing:border-box;font-family:inherit;';
    textarea.placeholder = '[{"domain":"www.example.com","name":"session","value":"..."}]';

    const bar = document.createElement('div');
    bar.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;margin-top:8px;';

    const mergeBtn = document.createElement('button');
    mergeBtn.textContent = '合并并复制';
    mergeBtn.style.cssText = buttonStyle('#16a34a');
    mergeBtn.onclick = async () => {
      try {
        const cookies = normalizeCookieEditorInput(textarea.value);
        const output = buildOutput(cookies);
        await copyText(JSON.stringify(output, null, 2));
        renderPanel(output, `已合并 Cookie Editor Cookie ${cookies.length} 条并复制。现在可粘贴到 qiandao JSON 导入。`);
      } catch (err) {
        desc.textContent = String(err.message || err);
        desc.style.color = '#fca5a5';
      }
    };

    const cancelBtn = document.createElement('button');
    cancelBtn.textContent = '返回';
    cancelBtn.style.cssText = buttonStyle('#6b7280');
    cancelBtn.onclick = () => renderPanel(lastOutput || buildOutput([]), '已返回。');

    bar.append(mergeBtn, cancelBtn);
    p.append(title, desc, textarea, bar);
  }

  async function copyImportJsonWithoutCookies() {
    const output = buildOutput([]);
    await copyText(JSON.stringify(output, null, 2));
    renderPanel(output, '已复制当前页面可读取的导入 JSON。注意：new-api 的 HttpOnly session 仍需要用 Cookie Editor 合并。');
  }

  function openPanel() {
    renderPanel(buildOutput([]), '当前 JSON 已包含网址和 Storage。若是 new-api，请点击“粘贴 Cookie Editor JSON 合并”，把 Cookie Editor 导出的 session Cookie 合并进去。');
  }

  function createFloatingButton() {
    if (floatingButton) return;
    floatingButton = document.createElement('button');
    floatingButton.textContent = 'qiandao 导入';
    floatingButton.style.cssText = `
      position:fixed;right:20px;bottom:20px;z-index:2147483647;background:#2563eb;color:white;border:0;border-radius:999px;
      padding:10px 14px;font-size:13px;font-weight:700;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.25);`;
    floatingButton.onclick = openPanel;
    document.body.appendChild(floatingButton);
  }

  function init() {
    if (typeof GM_registerMenuCommand === 'function') {
      GM_registerMenuCommand('qiandao：打开导入 JSON 面板', openPanel);
      GM_registerMenuCommand('qiandao：复制当前可读导入 JSON', copyImportJsonWithoutCookies);
    }
    createFloatingButton();
  }

  init();
})();
