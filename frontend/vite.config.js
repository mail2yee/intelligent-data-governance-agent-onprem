import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/setupTests.js',
    globals: true,
  },
  server: {
    port: 5173,
    proxy: {
      // Backend runs separately (uvicorn on :8000, or the backend
      // container in docker-compose). Proxying avoids CORS entirely for
      // local dev; in Docker, nginx does the equivalent (see nginx.conf).
      // /health is intentionally unprefixed on the backend (matches the
      // convention infra health checks/k8s probes expect), so it needs
      // its own proxy entry separate from /api.
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
