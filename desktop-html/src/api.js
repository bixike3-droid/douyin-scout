let token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
export const authToken = () => token;
export async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { Authorization: `Bearer ${token}`, ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try { message = (await response.json()).detail || message; } catch {}
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
  }
  return response.json();
}
export function fileUrl(id, options = {}) {
  const query = new URLSearchParams({ token, ...options });
  return `/api/files/${encodeURIComponent(id)}?${query}`;
}
// 媒体元素（<video>/<img>）不能带请求头，token 只能走查询参数。
export function withToken(path) {
  if (!path) return '';
  return `${path}${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`;
}
export function uploadUrl(id, preview = true) {
  return `/api/uploads/${id}/${preview ? 'preview' : 'file'}?token=${encodeURIComponent(token)}`;
}
export function uploadFile(file, progress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', `/api/uploads?name=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.upload.onprogress = event => progress(event.lengthComputable ? Math.round(event.loaded / event.total * 100) : 0);
    xhr.onload = () => {
      try {
        const result = JSON.parse(xhr.responseText);
        xhr.status < 300 ? resolve(result) : reject(new Error(result.detail || '文件添加失败'));
      } catch { reject(new Error('文件添加失败，请重试')); }
    };
    xhr.onerror = () => reject(new Error('文件传输中断，请重试'));
    xhr.send(file);
  });
}
export async function nativeBridge() {
  // The desktop carrier is the system WebView2 runtime (pywebview); a plain
  // browser tab (dev preview) has no bridge.
  if (new URLSearchParams(location.hash.slice(1)).get('native') !== 'webview2' && !window.pywebview?.api) return null;
  if (!window.pywebview?.api) await new Promise(resolve => window.addEventListener('pywebviewready', resolve, { once: true }));
  const host = window.pywebview.api;
  const signal = name => ({ connect(callback) { window.addEventListener(name, event => callback(event.detail)); } });
  return {
    handlesNativeDrop: true,
    filesDropped: signal('yuanjing-files-dropped'),
    dragState: signal('yuanjing-drag-state'),
    initialFiles: callback => host.initialFiles(token).then(callback),
    pickFiles: callback => host.pickFiles(token).then(callback),
    windowAction: action => host.windowAction(token, action),
    openDataFolder: () => host.openDataFolder(token),
  };
}
export const size = bytes => bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(2)} GB` : bytes >= 1024 ** 2 ? `${(bytes / 1024 ** 2).toFixed(1)} MB` : `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
export const modelName = value => value === 'deepseek-flash' ? 'DeepSeek Flash' : value === 'deepseek-v4-pro' ? 'DeepSeek V4 Pro' : value || 'DeepSeek';
export const dateLabel = value => value ? new Date(value).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }) : '';
