import type { ReactNode } from 'react'
import { DatesProvider } from '@mantine/dates'
import { AdapterDayjs } from '@mui/x-date-pickers/AdapterDayjs'
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider'
import { deDE, frFR, itIT } from '@mui/x-date-pickers/locales'
import { useTranslation } from 'react-i18next'
import 'dayjs/locale/de'
import 'dayjs/locale/fr'
import 'dayjs/locale/it'

// MUI X localizes on two separate paths: the date library via `adapterLocale`
// (dayjs month names, formats) and the picker component text via `localeText`
// ("Choose date", "Clear", month navigation). English is MUI's built-in
// default, so only the non-English bundles are mapped. Mirrors the DataGrid
// pattern in lib/dataGridLocale.ts.
const pickerLocaleTextByLanguage = {
    de: deDE.components.MuiLocalizationProvider.defaultProps.localeText,
    fr: frFR.components.MuiLocalizationProvider.defaultProps.localeText,
    it: itIT.components.MuiLocalizationProvider.defaultProps.localeText,
}

/**
 * Feeds the active UI language to the date pickers, which otherwise render
 * English month names and button text: Mantine's calendars via `DatesProvider`
 * and MUI X's pickers via a single app-level `LocalizationProvider` (so
 * individual fields don't need their own, and all of them inherit
 * `adapterLocale` and `localeText`).
 */
export function DateLocaleProvider({ children }: { children: ReactNode }) {
    const { i18n } = useTranslation()
    // dayjs locales are registered under the bare language code.
    const locale = i18n.language?.split('-')[0] ?? 'en'

    return (
        <LocalizationProvider
            dateAdapter={AdapterDayjs}
            adapterLocale={locale}
            localeText={pickerLocaleTextByLanguage[locale as keyof typeof pickerLocaleTextByLanguage]}
        >
            <DatesProvider settings={{ locale }}>{children}</DatesProvider>
        </LocalizationProvider>
    )
}
