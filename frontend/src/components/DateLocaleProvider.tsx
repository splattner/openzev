import type { ReactNode } from 'react'
import { DatesProvider } from '@mantine/dates'
import { useTranslation } from 'react-i18next'
import 'dayjs/locale/de'
import 'dayjs/locale/fr'
import 'dayjs/locale/it'

/**
 * Feeds the active UI language to Mantine's calendars via `DatesProvider`
 * (month names, weekday order, button text). English is Mantine's built-in
 * default, so only the non-English dayjs locales are imported. This is the
 * app's single date-localization path since the MUI X pickers were retired.
 */
export function DateLocaleProvider({ children }: { children: ReactNode }) {
    const { i18n } = useTranslation()
    // dayjs locales are registered under the bare language code.
    const locale = i18n.language?.split('-')[0] ?? 'en'

    return <DatesProvider settings={{ locale }}>{children}</DatesProvider>
}
