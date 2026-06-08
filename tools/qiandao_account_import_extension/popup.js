const els = {
  status: document.getElementById('status'),
  summary: document.getElementById('summary'),
  siteText: document.getElementById('siteText'),
  providerText: document.getElementById('providerText'),
  nameText: document.getElementById('nameText'),
  userIdText: document.getElementById('userIdText'),
  sessionText: document.getElementById('sessionText'),
  collectBtn: document.getElementById('collectBtn'),
  copyBtn: document.getElementById('copyBtn'),
  downloadBtn: document.getElementById('downloadBtn'),
  jsonOutput: document.getElementById('jsonOutput')
};

let lastJsonText = '';

const NEW_API_SELF_PATHS = [
  '/api/user/self',
  '/api/user',
  '/api/me'
];

const SUB2API_SELF_PATHS = [
  '/api/v1/auth/me?timezone=Asia%2FShanghai',
  '/api/v1/auth/me',
  '/api/auth/me'
];

function setStatus(text, kind = '') {
  els.status.textContent = text;
  els.status.className = `status ${kind}`.trim();
}

function normalizeOrigin(url) {
  try {
    return new URL(url).origin;
  } catch (_) {
    return '';
  }
}

function normalizeCookieDomain(domain) {
  return String(domain || '').replace(/^\./, '');
}

function cookieMatchesHost(cookie, host) {
  const domain = normalizeCookieDomain(cookie.domain);
  return domain && (host === domain || host.endsWith(`.${domain}`));
}

function pickCookie(cookies, names) {
  const lowered = names.map(x => x.toLowerCase());
  return cookies.find(c => lowered.includes(String(c.name || '').toLowerCase())) || null;
}

function cookieHeader(cookies) {
  return cookies
    .filter(c => c && c.name && c.value !== undefined && c.value !== null)
    .map(c => `${c.name}=${c.value}`)
    .join('; ');
}

function getStorageItem(items, key) {
  return items.find(item => item.key === key)?.value;
}

function setStorageItem(items, key, value) {
  const item = items.find(x => x.key === key);
  if (item) item.value = value;
  else items.push({ key, value });
}

function pickAccountName(user) {
  if (!user || typeof user !== 'object') return '';
  return String(user.email || user.username || user.display_name || user.name || user.id || '').trim();
}

function normalizeIdentityFromPayload(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const data = payload.data && typeof payload.data === 'object' ? payload.data : payload;
  if (!data || typeof data !== 'object') return null;
  const hasIdentity = ['id', 'email', 'username', 'display_name', 'name'].some(k => data[k] !== undefined && data[k] !== null && String(data[k]).trim() !== '');
  return hasIdentity ? data : null;
}

async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs && tabs[0] ? tabs[0] : null;
}

async function collectPageStorage(tabId) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      function readStorage(storage) {
        const items = [];
        for (let i = 0; i < storage.length; i += 1) {
          const key = storage.key(i);
          const raw = storage.getItem(key);
          let value = raw;
          try {
            value = JSON.parse(raw);
          } catch (_) {}
          items.push({ key, value });
        }
        return {
          storageName: storage === localStorage ? 'localStorage' : 'sessionStorage',
          matchedCount: items.length,
          items
        };
      }

      return {
        title: document.title || '',
        origin: location.origin,
        page: location.href,
        localStorage: readStorage(localStorage),
        sessionStorage: readStorage(sessionStorage),
        documentCookie: document.cookie || ''
      };
    }
  });
  return result?.result;
}

async function collectCookiesForUrl(url) {
  const cookies = await chrome.cookies.getAll({ url });
  return cookies.map(c => ({
    domain: c.domain,
    expirationDate: c.expirationDate,
    hostOnly: c.hostOnly,
    httpOnly: c.httpOnly,
    name: c.name,
    path: c.path,
    sameSite: c.sameSite,
    secure: c.secure,
    session: c.session,
    storeId: c.storeId,
    value: c.value
  }));
}

function visibleCookieList(documentCookie) {
  if (!documentCookie) return [];
  return documentCookie.split(';').map(x => x.trim()).filter(Boolean).map(item => {
    const idx = item.indexOf('=');
    return {
      name: idx >= 0 ? item.slice(0, idx) : item,
      valuePreview: idx >= 0 ? item.slice(idx + 1) : ''
    };
  });
}

async function requestJsonInPage(tabId, path, options = {}) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    args: [path, options],
    func: async (requestPath, requestOptions) => {
      const startedAt = Date.now();
      try {
        const url = new URL(requestPath, location.origin).href;
        const response = await fetch(url, {
          method: 'GET',
          credentials: 'include',
          cache: 'no-store',
          headers: {
            Accept: 'application/json, text/plain, */*',
            ...(requestOptions && requestOptions.headers ? requestOptions.headers : {})
          }
        });
        const text = await response.text();
        let json = null;
        let isJson = false;
        try {
          json = JSON.parse(text);
          isJson = true;
        } catch (_) {}
        return {
          path: requestPath,
          url,
          status: response.status,
          ok: response.ok,
          contentType: response.headers.get('content-type') || '',
          elapsedMs: Date.now() - startedAt,
          isJson,
          json,
          textPreview: isJson ? '' : text.slice(0, 300)
        };
      } catch (err) {
        return {
          path: requestPath,
          ok: false,
          networkError: true,
          error: String(err),
          elapsedMs: Date.now() - startedAt
        };
      }
    }
  });
  return result?.result;
}

async function discoverNewApiIdentity(tabId, userId) {
  const headers = {};
  if (userId) headers['new-api-user'] = String(userId);
  const results = [];
  for (const path of NEW_API_SELF_PATHS) {
    const result = await requestJsonInPage(tabId, path, { headers });
    results.push(result);
    const identity = normalizeIdentityFromPayload(result?.json);
    if (result?.ok && identity) {
      return { identity, result, results };
    }
  }
  return { identity: null, result: null, results };
}

async function discoverSub2apiIdentity(tabId, token) {
  const headers = token ? { Authorization: `Bearer ${String(token).replace(/^Bearer\s+/i, '')}` } : {};
  const results = [];
  for (const path of SUB2API_SELF_PATHS) {
    const result = await requestJsonInPage(tabId, path, { headers });
    results.push(result);
    const identity = normalizeIdentityFromPayload(result?.json);
    if (result?.ok && identity) {
      return { identity, result, results };
    }
  }
  return { identity: null, result: null, results };
}

async function inferAndEnrich(tabId, output) {
  const localItems = output.storageScan?.localStorage?.items || [];
  const cookies = output.cookieEditorCookies || [];
  const authToken = getStorageItem(localItems, 'auth_token');
  let authUser = getStorageItem(localItems, 'auth_user');
  let newApiUser = getStorageItem(localItems, 'user');
  const sessionCookie = pickCookie(cookies, ['session']);

  const apiScan = { matchedCount: 0, matched: [], allResultsSummary: [] };

  if (typeof authToken === 'string' && authToken.trim()) {
    if (!authUser || typeof authUser !== 'object') {
      const discovered = await discoverSub2apiIdentity(tabId, authToken);
      apiScan.allResultsSummary.push(...discovered.results);
      if (discovered.identity) {
        authUser = discovered.identity;
        setStorageItem(localItems, 'auth_user', authUser);
        apiScan.matched.push(discovered.result);
      }
    }
    apiScan.matchedCount = apiScan.matched.length;
    return {
      provider: 'sub2api',
      name: pickAccountName(authUser),
      userId: authUser && typeof authUser === 'object' ? String(authUser.id || '') : '',
      sessionField: 'localStorage.auth_token',
      hasSession: true,
      account: {
        provider: 'sub2api',
        base_url: output.origin,
        name: pickAccountName(authUser) || 'sub2api-account',
        new_api_user: '',
        session: String(authToken).replace(/^Bearer\s+/i, ''),
        cookie: cookieHeader(cookies)
      },
      apiScan
    };
  }

  if (sessionCookie) {
    let userId = newApiUser && typeof newApiUser === 'object' ? String(newApiUser.id || '') : '';
    if (!newApiUser || typeof newApiUser !== 'object') {
      const discovered = await discoverNewApiIdentity(tabId, userId);
      apiScan.allResultsSummary.push(...discovered.results);
      if (discovered.identity) {
        newApiUser = discovered.identity;
        userId = String(discovered.identity.id || userId || '');
        setStorageItem(localItems, 'user', newApiUser);
        apiScan.matched.push(discovered.result);
      }
    }
    apiScan.matchedCount = apiScan.matched.length;
    return {
      provider: 'new-api',
      name: pickAccountName(newApiUser),
      userId: newApiUser && typeof newApiUser === 'object' ? String(newApiUser.id || userId || '') : userId,
      sessionField: 'cookie.session',
      hasSession: true,
      account: {
        provider: 'new-api',
        base_url: output.origin,
        name: pickAccountName(newApiUser) || (userId ? `new-api-${userId}` : 'new-api-account'),
        new_api_user: newApiUser && typeof newApiUser === 'object' ? String(newApiUser.id || userId || '') : userId,
        session: sessionCookie.value,
        cookie: ''
      },
      apiScan
    };
  }

  if (newApiUser && typeof newApiUser === 'object') {
    return {
      provider: 'new-api',
      name: pickAccountName(newApiUser),
      userId: String(newApiUser.id || ''),
      sessionField: '未找到 cookie.session',
      hasSession: false,
      account: {
        provider: 'new-api',
        base_url: output.origin,
        name: pickAccountName(newApiUser),
        new_api_user: String(newApiUser.id || ''),
        session: '',
        cookie: ''
      },
      apiScan
    };
  }

  return {
    provider: '未识别',
    name: '',
    userId: '',
    sessionField: '未找到',
    hasSession: false,
    account: null,
    apiScan
  };
}

async function collect() {
  setStatus('正在采集当前标签页...', '');
  els.collectBtn.disabled = true;
  els.copyBtn.disabled = true;
  els.downloadBtn.disabled = true;

  try {
    const tab = await getActiveTab();
    if (!tab || !tab.id || !tab.url) {
      throw new Error('没有找到当前标签页');
    }
    if (!/^https?:\/\//i.test(tab.url)) {
      throw new Error('请在 http/https 网站页面使用本扩展');
    }

    const page = await collectPageStorage(tab.id);
    if (!page) throw new Error('无法读取当前页面 storage，请刷新页面后重试');

    const cookies = await collectCookiesForUrl(tab.url);
    const origin = page.origin || normalizeOrigin(tab.url);
    const host = new URL(tab.url).hostname;
    const currentSiteCookies = cookies.filter(c => cookieMatchesHost(c, host));

    const output = {
      format: 'qiandao-account-import',
      version: 4,
      collector: 'chrome-extension',
      compatibility: ['new-api', 'sub2api'],
      origin,
      base_url: origin,
      page: page.page || tab.url,
      title: page.title || tab.title || '',
      time: new Date().toISOString(),
      storageScan: {
        localStorage: page.localStorage,
        sessionStorage: page.sessionStorage
      },
      cookieEditorCookies: currentSiteCookies,
      cookies: currentSiteCookies,
      visibleCookies: {
        note: 'document.cookie 可见 Cookie；完整 Cookie 见 cookieEditorCookies，其中可包含 HttpOnly cookie。',
        count: visibleCookieList(page.documentCookie).length,
        cookies: visibleCookieList(page.documentCookie)
      }
    };

    setStatus('正在识别 new-api/sub2api 并补全用户信息...', '');
    const summary = await inferAndEnrich(tab.id, output);
    output.detected = summary;
    output.apiScan = summary.apiScan;
    output.qiandaoAccount = summary.account;

    lastJsonText = JSON.stringify(output, null, 2);
    els.jsonOutput.value = lastJsonText;

    els.summary.hidden = false;
    els.siteText.textContent = origin;
    els.providerText.textContent = summary.provider;
    els.nameText.textContent = summary.name || '-';
    els.userIdText.textContent = summary.userId || '-';
    els.sessionText.textContent = summary.sessionField;

    if (summary.provider === '未识别') {
      setStatus('未识别为 new-api 或 sub2api。请确认当前页面已经登录，且网站属于这两种类型。', 'warn');
    } else if (!summary.hasSession) {
      setStatus(`已识别 ${summary.provider}，但没有找到可导入的 session/token。new-api 请确认存在 session Cookie；sub2api 请确认 localStorage.auth_token 存在。`, 'warn');
    } else if (summary.provider === 'new-api' && !summary.userId) {
      setStatus('已读取 new-api session，但没有识别到 new_api_user。可以复制 JSON 后在导入表单中手动补用户 ID。', 'warn');
    } else {
      setStatus(`采集成功：已识别 ${summary.provider}，导入 JSON 已包含所需字段。`, 'ok');
    }

    els.copyBtn.disabled = false;
    els.downloadBtn.disabled = false;
  } catch (err) {
    console.error(err);
    setStatus(`采集失败：${err.message || err}`, 'err');
  } finally {
    els.collectBtn.disabled = false;
  }
}

async function copyJson() {
  if (!lastJsonText) return;
  try {
    await navigator.clipboard.writeText(lastJsonText);
    setStatus('已复制导入 JSON。回到 qiandao -> 添加账号 -> JSON 导入添加 粘贴即可。', 'ok');
  } catch (err) {
    setStatus(`复制失败：${err.message || err}。可以手动选中文本框内容复制。`, 'err');
  }
}

function downloadJson() {
  if (!lastJsonText) return;
  const blob = new Blob([lastJsonText], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `qiandao-account-import-${Date.now()}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

els.collectBtn.addEventListener('click', collect);
els.copyBtn.addEventListener('click', copyJson);
els.downloadBtn.addEventListener('click', downloadJson);

document.addEventListener('DOMContentLoaded', () => {
  setStatus('打开已登录的 new-api/sub2api 页面后，点击“采集当前页”。');
});
