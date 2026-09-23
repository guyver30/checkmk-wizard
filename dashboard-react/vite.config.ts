/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// /checkmk-api same-origin proxy (13-05, D-04/CHECKMK_REST_ORIGIN in src/lib/config.ts):
// Checkmk answers no CORS preflight (13-01 VERDICT V-CORS, live-verified 2026-09-23), so the
// browser cannot call Checkmk's REST API on its own origin/port directly. This is not a new
// backend -- it is a path-forwarding rule on the server that already serves the SPA, with no
// auth and no logic added; the browser still authenticates to Checkmk with its own Bearer
// credential (checkmkWrite.ts). Post-cutover (D-42) the same job becomes one nginx `location`
// block in the dashboard container instead of this dev/preview server.
const checkmkApiProxy = {
  '/checkmk-api': {
    target: process.env.CHECKMK_PROXY_TARGET ?? 'http://localhost:8080',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/checkmk-api/, ''),
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    // Defensive against duplicate React instances even though the packed-tarball
    // install of kone-design-system already avoids the symlink that would cause it.
    dedupe: ['react', 'react-dom'],
  },
  server: {
    proxy: checkmkApiProxy,
  },
  preview: {
    proxy: checkmkApiProxy,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
  },
})
