/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// /checkmk-api same-origin proxy (13-05, CHECKMK_REST_ORIGIN in src/lib/config.ts):
// Checkmk answers no CORS preflight (13-01 VERDICT V-CORS, live-verified 2026-09-23), so the
// browser cannot call Checkmk's REST API on its own origin/port directly. This is not a new
// backend -- it is a path-forwarding rule on the server that already serves the SPA.
//
// Amended 2026-09-30 (quick 260930-hpy): the browser no longer sends a credential at all
// (checkmkWrite.ts's request() sets no Authorization header) -- this dev/preview proxy now
// injects it itself from the dev shell's own TOPOLOGY_EDITOR_SECRET env var, mirroring what
// deploy/dashboard-nginx.conf's production `proxy_set_header Authorization` does post-cutover
// (D-42). An empty/unset env var still produces a well-formed (if rejected) header, same as
// nginx's envsubst default.
const checkmkApiProxy = {
  '/checkmk-api': {
    target: process.env.CHECKMK_PROXY_TARGET ?? 'http://localhost:8080',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/checkmk-api/, ''),
    headers: {
      Authorization: `Bearer topology_editor ${process.env.TOPOLOGY_EDITOR_SECRET ?? ''}`,
    },
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
