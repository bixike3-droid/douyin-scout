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
  // Both desktop carriers use the same UI contract. Qt remains available for
  // the original desktop; the release carrier uses the system WebView2 runtime.
  if (new URLSearchParams(location.hash.slice(1)).get('native') === 'webview2' || window.pywebview?.api) {
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
  if (!window.qt?.webChannelTransport) return null;
  await new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = '/bridge.js'; script.onload = resolve; script.onerror = reject;
    document.head.appendChild(script);
  });
  return new Promise(resolve => new window.QWebChannel(window.qt.webChannelTransport, channel => resolve(channel.objects.desktop)));
}
export const size = bytes => bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(2)} GB` : bytes >= 1024 ** 2 ? `${(bytes / 1024 ** 2).toFixed(1)} MB` : `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
export const modelName = value => value === 'deepseek-flash' ? 'DeepSeek Flash' : value === 'deepseek-v4-pro' ? 'DeepSeek V4 Pro' : value || 'DeepSeek';
export const dateLabel = value => value ? new Date(value).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }) : '';
