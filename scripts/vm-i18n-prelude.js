function t(key, params = {}) {
  let value = zh[key];
  if (value && typeof value === 'object') {
    const count = params.count;
    value = count === 1 && value.one ? value.one : value.other ?? value.one ?? key;
  }
  if (!value) value = key;
  return String(value).replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ''));
}

function tp(key, count, params = {}) {
  return t(key, { ...params, count });
}
