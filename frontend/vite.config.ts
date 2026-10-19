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
    // axe over a whole page in jsdom can take several seconds when every test file runs in parallel
    testTimeout: 15_000,
    // One jsdom worker per CPU (the default) oversubscribed an 8-CPU machine: whole files ran 10-20x slower and
    // axe-heavy tests hit the timeout intermittently. Half the CPUs is stable and faster (P8-D1 D1.9).
    maxWorkers: '50%',
  },
})
