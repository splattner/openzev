import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import '@fontsource-variable/inter/index.css'
import '@mantine/core/styles.css'
import '@mantine/dates/styles.css'
import './styles/tokens.css'
import { generatedTheme } from './styles/generatedTheme'
import './index.css'
import App from './App.tsx'
import './i18n'
import { DateLocaleProvider } from './components/DateLocaleProvider'
import { AuthProvider } from './lib/auth'
import { AppSettingsProvider } from './lib/appSettings'
import { ToastProvider } from './lib/toast'

const queryClient = new QueryClient()

// Colors live in styles/generatedTheme.ts (generated from design/tokens.json),
// never here. `fontFamily` must stay in the generated theme: Mantine's stylesheet
// sets `body { font-family }` and would otherwise override index.css.
const mantineTheme = { ...generatedTheme, defaultRadius: 'md' } as const

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AppSettingsProvider>
          <ToastProvider>
            <MantineProvider theme={mantineTheme}>
              <DateLocaleProvider>
                <App />
              </DateLocaleProvider>
            </MantineProvider>
          </ToastProvider>
        </AppSettingsProvider>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
