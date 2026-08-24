import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: {
        // Vite 8 bundles with Rolldown, where the Rollup-style `manualChunks`
        // function is deprecated and its per-module assignments are overridden
        // by importer relationships. `codeSplitting.groups` with priorities is
        // the supported equivalent: a module matching several groups goes to
        // the group with the highest priority, and a module whose own group
        // has a lower priority than its importer's group is pulled into the
        // importer's chunk — hence the catch-all vendor-misc group sits at
        // the lowest priority.
        codeSplitting: {
          groups: [
            { name: 'vendor-react-query', test: /@tanstack\/react-query/, priority: 50 },
            { name: 'vendor-mantine', test: /@mantine\//, priority: 35 },
            { name: 'vendor-charts', test: /recharts|d3-/, priority: 30 },
            { name: 'vendor-router', test: /react-router/, priority: 25 },
            {
              name: 'vendor-react',
              test: /[\\/](?:react-dom|react|scheduler)[\\/]/,
              priority: 20,
            },
            { name: 'vendor-misc', test: /node_modules/, priority: 5 },
          ],
        },
      },
    },
  },
  server: {
    proxy: {
      // Default matches the compose topology (http://backend:8000). Override
      // with VITE_DEV_PROXY_TARGET=http://localhost:8000 for bare-metal dev.
      ...(Object.fromEntries(['/api', '/media'].map((path) => [
        path,
        {
          // Dev parity with the production nginx (fullstack-nginx.conf):
          // document embeds fetch authenticated API blob instead of /media/.
          target: process.env.VITE_DEV_PROXY_TARGET ?? 'http://backend:8000',
          changeOrigin: true,
        },
      ]))),
    },
  },
})
