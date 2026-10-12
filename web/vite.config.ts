import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

// localhost:8000 via IPv4. Node resolves "localhost" to ::1 on Windows, but uvicorn binds 127.0.0.1.
const API_TARGET = 'http://127.0.0.1:8000'

/**
 * Low-priority modulepreload hints for the map's chunks in index.html. They are only reached
 * through dynamic imports, so without a hint the browser starts on them only once the entry has
 * run; with one they download from the start, behind the entry and the CSS.
 */
function preloadMapChunks(): Plugin {
  let base = '/'
  return {
    name: 'tempest:preload-map-chunks',
    apply: 'build',
    configResolved(config) {
      base = config.base
    },
    transformIndexHtml: {
      order: 'post',
      handler(_html, ctx) {
        return Object.values(ctx.bundle ?? {})
          .filter((c) => c.type === 'chunk' && /^(maplibre|deck|deckLayers|MapView)$/.test(c.name))
          .map((c) => ({
            tag: 'link',
            attrs: { rel: 'modulepreload', href: base + c.fileName, crossorigin: '', fetchpriority: 'low' },
            injectTo: 'head' as const,
          }))
      },
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), preloadMapChunks()],
  optimizeDeps: {
    // maplibre-gl v6 finds its web worker at runtime via
    // new URL('./maplibre-gl-worker.mjs', import.meta.url). Pre-bundling moves the main
    // module into node_modules/.vite/deps/, where that sibling file doesn't exist, so the
    // worker 404s and the map stays blank. Excluding it keeps it served from its own dist/.
    // Its deps are already bundled into its ESM files, so nothing needs optimizeDeps.include.
    exclude: ['maplibre-gl'],
  },
  build: {
    rolldownOptions: {
      output: {
        // Named vendor chunks (Rolldown's replacement for manualChunks). MapLibre and deck.gl /
        // luma.gl are only reached through dynamic imports (components/LazyMapView, lib/deck),
        // so they stay off the entry's critical path; React is cached apart from app code.
        // Groups take their dependencies along (earcut, gl-matrix...: no chunk cycles). Vite's
        // preload helper gets its own tiny chunk first: luma.gl uses dynamic imports, and inside
        // the deck chunk the helper would make the entry import deck statically.
        codeSplitting: {
          groups: [
            { name: 'preload-helper', test: /vite\/preload-helper/, priority: 4 },
            { name: 'maplibre', test: /[\\/]node_modules[\\/]maplibre-gl[\\/]/, priority: 3 },
            { name: 'deck', test: /[\\/]node_modules[\\/]@(deck|luma|loaders|math|probe)\.gl[\\/]/, priority: 2 },
            { name: 'react', test: /[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/, priority: 1 },
          ],
        },
      },
    },
  },
  server: {
    // Dev only: the browser calls same-origin /api and /health; Vite forwards to FastAPI.
    proxy: {
      '/api': API_TARGET,
      '/health': API_TARGET,
    },
  },
})
