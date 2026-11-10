/* global window, document, localStorage, location, navigator, fetch, Intl */
(function initI18n(global) {
  'use strict';

  const STORAGE_KEY = 'ui-locale';

  const FALLBACK_UI = {
    loadFailed: 'Unable to load the interface language. Please retry. / 无法加载界面语言，请重试。',
    retry: 'Retry / 重试',
  };

  const ALLOWED_ATTRS = new Set([
    'title',
    'alt',
    'placeholder',
    'aria-label',
    'aria-description',
    'aria-valuetext',
    'aria-roledescription',
  ]);

  const KEY_PATTERN = /^[a-z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9_-]+)+$/;

  let manifest = null;
  let messages = {};
  let fallbackMessages = {};
  let localeId = 'zh-CN';
  let intlLocale = 'zh-CN';
  let pluralRules = null;
  let fallbackPluralRules = null;
  let loaded = false;
  const warnedKeys = new Set();
  let manifestPromise = null;
  let loadFailed = false;

  function readStorageLocale() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (_err) {
      return null;
    }
  }

  function writeStorageLocale(value) {
    try {
      if (value == null || value === '') {
        localStorage.removeItem(STORAGE_KEY);
      } else {
        localStorage.setItem(STORAGE_KEY, value);
      }
    } catch (_err) {
      /* ignore */
    }
  }

  function normalizeAlias(tag) {
    return typeof tag === 'string' ? tag.trim().replace(/_/g, '-').toLowerCase() : '';
  }

  function matchLocale(raw, manifestDoc) {
    let tag = normalizeAlias(raw);
    const locales = Object.entries(manifestDoc.locales || {}).filter(([id, cfg]) =>
      /^[a-z0-9]+(?:-[a-z0-9]+)*$/i.test(id) && cfg && cfg.enabled !== false);
    // Exact aliases win before regional variants fall back to a parent language.
    while (tag) {
      for (const [id, cfg] of locales) {
        const aliases = [id, ...(cfg.aliases || [])].map(normalizeAlias);
        if (aliases.includes(tag)) return id;
      }
      const end = tag.lastIndexOf('-');
      tag = end < 0 ? '' : tag.slice(0, end);
    }
    return null;
  }

  function defaultLocale(manifestDoc) {
    const fallback = matchLocale(manifestDoc.default, manifestDoc);
    return fallback || Object.keys(manifestDoc.locales || {}).find(id =>
      manifestDoc.locales[id]?.enabled !== false);
  }

  function resolveFromNavigator(manifestDoc) {
    const nav = Array.isArray(navigator.languages) && navigator.languages.length
      ? navigator.languages : [navigator.language || ''];
    for (const raw of nav) {
      const found = matchLocale(raw, manifestDoc);
      if (found) return found;
    }
    return defaultLocale(manifestDoc);
  }

  function resolveLocale(manifestDoc) {
    const stored = readStorageLocale();
    return matchLocale(stored, manifestDoc) || resolveFromNavigator(manifestDoc);
  }

  function localesBase() {
    const script = document.currentScript;
    if (script && script.src) {
      const url = new URL(script.src, global.location.href);
      return new URL('locales/', url).pathname;
    }
    return '/locales/';
  }

  async function fetchJson(path) {
    const res = await fetch(path, { credentials: 'same-origin' });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} for ${path}`);
    }
    return res.json();
  }

  function pickBranch(entry, count, rules) {
    if (typeof entry === 'string') return entry.trim() ? entry : null;
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return null;
    const category = rules ? rules.select(Number(count)) : 'other';
    const branch = Object.prototype.hasOwnProperty.call(entry, category) ? entry[category] : entry.other;
    return typeof branch === 'string' && branch.trim() ? branch : null;
  }

  function warnMissing(key) {
    if (!loaded || warnedKeys.has(key)) return;
    warnedKeys.add(key);
    global.console?.warn(`Missing interface translation: ${localeId}:${key}`);
  }

  function interpolate(template, params) {
    if (template == null) {
      return '';
    }
    let text = String(template);
    const bag = params && typeof params === 'object' ? params : {};
    text = text.replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, (match, name) => {
      if (!Object.prototype.hasOwnProperty.call(bag, name)) {
        return match;
      }
      const value = bag[name];
      return value == null ? '' : String(value);
    });
    return text;
  }

  function lookup(key, source) {
    if (!source || !Object.prototype.hasOwnProperty.call(source, key)) {
      return undefined;
    }
    return source[key];
  }

  function translate(key, params, count) {
    if (typeof key !== 'string' || !KEY_PATTERN.test(key)) return `[missing:${key}]`;
    let branch = pickBranch(lookup(key, messages), count, pluralRules);
    if (branch == null) {
      warnMissing(key);
      branch = pickBranch(lookup(key, fallbackMessages), count, fallbackPluralRules);
    }
    return branch == null ? `[missing:${key}]` : interpolate(branch, params);
  }

  function t(key, params) {
    return translate(key, params, params?.count ?? 0);
  }

  function tp(key, count, params) {
    return translate(key, Object.assign({}, params || {}, { count }), count);
  }

  function isMessage(value) {
    return value && typeof value === 'object' && !Array.isArray(value) &&
      (typeof value.key === 'string' || Array.isArray(value.join));
  }

  function renderMessage(value, depth = 0) {
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    if (!isMessage(value) || depth > 32) return '';
    if (Array.isArray(value.join)) {
      const separator = value.separator_key ? t(value.separator_key) : (value.separator ?? '');
      return value.join.map(part => renderMessage(part, depth + 1)).filter(Boolean).join(separator);
    }
    const params = {};
    for (const [name, param] of Object.entries(value.params || {})) {
      // Only explicit descriptors are translated. Paths, output and other data stay verbatim.
      params[name] = isMessage(param) ? renderMessage(param, depth + 1) : param;
    }
    const text = t(value.key, params);
    return text + (Array.isArray(value.suffixes)
      ? value.suffixes.map(part => renderMessage(part, depth + 1)).join('') : '');
  }

  function formatNumber(value, options) {
    try {
      return new Intl.NumberFormat(intlLocale, options).format(value);
    } catch (_err) {
      return String(value);
    }
  }

  function formatDate(value, options) {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) {
      return t('common.unrecorded');
    }
    try {
      return new Intl.DateTimeFormat(intlLocale, options).format(date);
    } catch (_err) {
      return date.toISOString();
    }
  }

  function formatDuration(milliseconds) {
    const ms = Number(milliseconds);
    if (!Number.isFinite(ms) || ms < 0) {
      return t('common.unrecorded');
    }
    const totalSeconds = Math.round(ms / 1000);
    if (totalSeconds < 60) {
      return tp('common.durationSeconds', totalSeconds, { count: totalSeconds });
    }
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    if (seconds === 0) {
      return tp('common.durationMinutes', minutes, { minutes, count: minutes });
    }
    return tp('common.durationMinutesSeconds', minutes, {
      minutes,
      seconds,
      count: minutes,
    });
  }

  function applyTranslations(root) {
    const scope = root && root.querySelectorAll ? root : document;
    const nodes = scope.querySelectorAll('[data-i18n]');
    nodes.forEach((el) => {
      const keySpec = el.getAttribute('data-i18n');
      if (!keySpec) {
        return;
      }
      const keys = keySpec.split(',').map((piece) => piece.trim()).filter(Boolean);
      if (!keys.length) {
        return;
      }
      const attrSpec = el.getAttribute('data-i18n-attr');
      if (!attrSpec) {
        el.textContent = t(keys[0]);
        return;
      }
      const attrs = attrSpec.split(',').map((piece) => piece.trim()).filter(Boolean);
      attrs.forEach((attr, index) => {
        if (!attr || !ALLOWED_ATTRS.has(attr)) {
          return;
        }
        const key = keys.length === attrs.length ? keys[index] : keys[0];
        el.setAttribute(attr, t(key));
      });
      // Attribute-only nodes (inputs, icon buttons) keep existing children/value.
      if (keys.length === 1 && !['INPUT', 'TEXTAREA', 'IMG', 'SELECT', 'BUTTON'].includes(el.tagName) && !el.querySelector('*')) {
        el.textContent = t(keys[0]);
      }
    });
  }

  function applyDocumentLocale() {
    const cfg = manifest && manifest.locales && manifest.locales[localeId];
    const lang = cfg && cfg.intl ? cfg.intl : localeId;
    const dir = cfg && cfg.dir ? cfg.dir : 'ltr';
    document.documentElement.lang = lang;
    document.documentElement.dir = dir;
  }

  function setLocale(id) {
    writeStorageLocale(id == null ? '' : id);
    global.location.reload();
  }

  function getLocale() {
    return localeId;
  }

  function getManifest() {
    return manifest;
  }

  function showLoadFailure(err) {
    loadFailed = true;
    const main = document.querySelector('main') || document.body;
    if (!main) {
      return;
    }
    main.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.setAttribute('role', 'alert');
    wrap.style.padding = '2rem';
    wrap.style.maxWidth = '32rem';
    wrap.style.margin = '4rem auto';
    wrap.style.fontFamily = 'system-ui, sans-serif';
    wrap.style.lineHeight = '1.5';

    const p = document.createElement('p');
    p.textContent = FALLBACK_UI.loadFailed;
    wrap.appendChild(p);

    const detail = document.createElement('p');
    detail.style.opacity = '0.75';
    detail.style.fontSize = '0.875rem';
    detail.textContent = err && err.message ? err.message : String(err || '');
    wrap.appendChild(detail);

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = FALLBACK_UI.retry;
    btn.style.marginTop = '1rem';
    btn.addEventListener('click', () => global.location.reload());
    wrap.appendChild(btn);

    main.appendChild(wrap);
  }

  async function loadMessages() {
    const base = localesBase();
    manifest = await fetchJson(`${base}manifest.json`);
    localeId = resolveLocale(manifest);
    const cfg = manifest.locales[localeId] || {};
    intlLocale = cfg.intl || localeId;
    pluralRules = new Intl.PluralRules(intlLocale);

    const fallbackId = matchLocale(manifest.fallback, manifest) || defaultLocale(manifest);
    const fallbackCfg = manifest.locales[fallbackId] || {};
    fallbackPluralRules = new Intl.PluralRules(fallbackCfg.intl || fallbackId);
    const results = await Promise.allSettled([
      fetchJson(`${base}${localeId}.json`),
      localeId === fallbackId ? Promise.resolve(null) : fetchJson(`${base}${fallbackId}.json`),
    ]);
    if (results[0].status === 'fulfilled') {
      messages = results[0].value || {};
      fallbackMessages = localeId === fallbackId ? messages
        : results[1].status === 'fulfilled' ? results[1].value || {} : {};
    } else if (results[1].status === 'fulfilled' && results[1].value) {
      global.console?.warn(`Unable to load ${localeId}; using ${fallbackId}.`);
      messages = fallbackMessages = results[1].value;
      localeId = fallbackId;
      intlLocale = fallbackCfg.intl || fallbackId;
      pluralRules = fallbackPluralRules;
    } else {
      throw results[0].reason;
    }
    loaded = true;
    applyDocumentLocale();
    loadFailed = false;
  }

  const ready = (function start() {
    if (!manifestPromise) {
      manifestPromise = loadMessages().catch((err) => {
        showLoadFailure(err);
        throw err;
      });
    }
    return manifestPromise;
  })();

  const I18n = {
    STORAGE_KEY,
    ready,
    resolveLocale: () => (manifest ? resolveLocale(manifest) : 'zh-CN'),
    t,
    tp,
    renderMessage,
    formatNumber,
    formatDate,
    formatDuration,
    applyTranslations,
    setLocale,
    getLocale,
    getManifest,
    get loadFailed() {
      return loadFailed;
    },
  };

  global.I18n = I18n;
  global.t = t;
  global.tp = tp;
  global.formatNumber = formatNumber;
  global.formatDate = formatDate;
  global.formatDuration = formatDuration;
})(typeof window !== 'undefined' ? window : globalThis);
