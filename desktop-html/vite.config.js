import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath, URL } from 'node:url';

// 本地开发时把 /api 代理到 Python 本地服务：
//   1) python -m scout.web_desktop.window --serve-only --ready-file tmp/ready.json
//   2) $env:SCOUT_API="http://127.0.0.1:<ready.json 里的 port>"; npm run dev
const apiTarget = process.env.SCOUT_API || 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: Number(process.env.SCOUT_DEV_PORT || 5173),
    strictPort: true,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true, ws: true },
      '/brand.png': { target: apiTarget, changeOrigin: true },
      '/bridge.js': { target: apiTarget, changeOrigin: true },
      '/mermaid.js': { target: apiTarget, changeOrigin: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
});
