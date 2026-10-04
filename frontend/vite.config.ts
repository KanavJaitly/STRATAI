/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The web app talks to the STRATAI API on the same origin. In development, Vite proxies /api to the API
// (`python -m api`, default http://127.0.0.1:8000) and strips the prefix. Same-origin is deliberate: the
// API's CORS allow-list admits only GET/POST with Content-Type, and is not widened for the write token.
const apiTarget = process.env.STRATAI_API_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
