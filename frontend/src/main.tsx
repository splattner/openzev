import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider, createTheme } from '@mantine/core'
import '@fontsource-variable/inter/index.css'
import '@mantine/core/styles.css'
import '@mantine/dates/styles.css'
import './index.css'
import App from './App.tsx'
import './i18n'
import { DateLocaleProvider } from './components/DateLocaleProvider'
import { AuthProvider } from './lib/auth'
import { AppSettingsProvider } from './lib/appSettings'
import { ToastProvider } from './lib/toast'

const queryClient = new QueryClient()

// Aligns Mantine's surfaces (date pickers) with the hand-rolled CSS in index.css:
// Tailwind's sky ramp, whose shade 6 is the brand blue used by .button's gradient.
//
// `fontFamily` must be set here too: Mantine's stylesheet sets `body { font-family }`,
// which otherwise overrides index.css and reverts the app to the system font. Keep this
// stack in sync with index.css's `:root`.
const mantineTheme = createTheme({
    fontFamily: "'Inter Variable', Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    defaultRadius: 'md',
    primaryColor: 'brand',
    primaryShade: 6,
    colors: {
        brand: [
            '#f0f9ff',
            '#e0f2fe',
            '#bae6fd',
            '#7dd3fc',
            '#38bdf8',
            '#0ea5e9',
            '#0284c7',
            '#0369a1',
            '#075985',
            '#0c4a6e',
        ],
    },
})

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
