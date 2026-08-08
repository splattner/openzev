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
        // the supported equivalent: a module matching several groups (e.g.
        // `@emotion/react` matching both the emotion and the react group) goes
        // to the group with the highest priority, and a module whose own group
        // has a lower priority than its importer's group is pulled into the
        // importer's chunk. The MUI/emotion group therefore outranks the
        // data-grid group (so `@mui/material` deps and Emotion stay out of the
        // data-grid chunk) while excluding `x-data-grid` modules themselves
        // (so they still split into their own chunk). Emotion must also outrank
        // the catch-all vendor-misc group, otherwise it follows
        // `@mui/styled-engine` into vendor-misc.
        codeSplitting: {
          groups: [
            { name: 'vendor-react-query', test: /@tanstack\/react-query/, priority: 50 },
            { name: 'vendor-mui', test: /@mui\/(?!x-data-grid|x-date-pickers)|@emotion\//, priority: 45 },
            { name: 'vendor-mui-data-grid', test: /@mui\/x-data-grid/, priority: 40 },
            { name: 'vendor-mui-date-pickers', test: /@mui\/x-date-pickers/, priority: 40 },
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
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
})
