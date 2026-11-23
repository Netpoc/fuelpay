import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import tailwindcss from '@tailwindcss/vite'

// Tailwind v4 needs no tailwind.config.js and no postcss.config.js — the Vite
// plugin is the whole integration, and the design tokens live in
// src/assets/main.css under @theme.
export default defineConfig({
  plugins: [vue(), vueDevTools(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // Belt and braces alongside the API's CORS middleware: proxying makes dev
    // same-origin so CORS never engages at all. CORS remains the real fix,
    // since a deployed frontend has no proxy in front of it.
    //
    // Do not put compression in this path — it buffers, and buffering breaks
    // the SSE stream.
    proxy: {
      '/v1': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/health': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
