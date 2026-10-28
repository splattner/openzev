import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    rules: {
      'react-hooks/set-state-in-effect': 'off',
      'react-refresh/only-export-components': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
      'no-restricted-imports': ['error', {
        paths: [
          {
            // SPEC-2026-10-ui-patterns §7.4: one class mapping for every tab strip.
            name: '@mantine/core',
            importNames: ['Tabs'],
            message: 'Use AppTabs from components/AppTabs, which applies the app-tabs class mapping.',
          },
          {
            // SPEC-2026-10-ui-patterns §5 rule C: no overlay drawers.
            name: '@mantine/core',
            importNames: ['Drawer'],
            message: 'A detail beside a list uses DetailPane; one with no list is a FormModal or an inline section.',
          },
        ],
      }],
    },
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
  {
    // The wrapper itself is the one place that builds on Mantine's Tabs.
    files: ['src/components/AppTabs.tsx'],
    rules: { 'no-restricted-imports': 'off' },
  },
])
