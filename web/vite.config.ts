import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// localhost:8000 via IPv4. Node resolves "localhost" to ::1 on Windows, but uvicorn binds 127.0.0.1.
const API_TARGET = 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  optimizeDeps: {
    // maplibre-gl v6 finds its web worker at runtime via
    // new URL('./maplibre-gl-worker.mjs', import.meta.url). Pre-bundling moves the main
    // module into node_modules/.vite/deps/, where that sibling file doesn't exist, so the
    // worker 404s and the map stays blank. Excluding it keeps it served from its own dist/.
    // Its deps are already bundled into its ESM files, so nothing needs optimizeDeps.include.
    exclude: ['maplibre-gl'],
  },
  server: {
    // Dev only: the browser calls same-origin /api and /health; Vite forwards to FastAPI.
    proxy: {
      '/api': API_TARGET,
      '/health': API_TARGET,
    },
  },
})
