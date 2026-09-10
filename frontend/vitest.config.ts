import { defineConfig } from 'vitest/config'

const nodeMajor = Number.parseInt(process.versions.node, 10)

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.ts'],
    setupFiles: ['tests/setup.ts'],
    // Node 25+ Web Storage globals conflict with jsdom in Vitest.
    execArgv: nodeMajor >= 25 ? ['--no-webstorage'] : [],
  },
})
