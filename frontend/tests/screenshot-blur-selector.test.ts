import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../src/lib/appSettings', async () => {
    const actual = await vi.importActual<typeof import('../src/lib/appSettings')>('../src/lib/appSettings')
    return { ...actual, useAppSettings: () => ({ settings: { date_format_short: 'DD.MM.YYYY' } }) }
})

const { ZevGeneralSettingsFields } = await import('../src/components/ZevGeneralSettingsFields')
const { DateLocaleProvider } = await import('../src/components/DateLocaleProvider')
const { getDefaultZevForm } = await import('../src/lib/zevForm')
await import('../src/i18n')

/**
 * Guards the screenshot suite's PII blur for the ZEV settings page.
 *
 * screenshots/capture.spec.ts blurs these inputs before committing a public
 * screenshot. It used to match them by English label text, which silently
 * stopped matching once the page was translated — leaking bank details. Keep
 * this selector and the component's name attributes in sync.
 */
const BLUR_SELECTOR = 'input[name="name"], input[name="bank_name"], input[name="bank_iban"]'

describe('screenshot PII blur selector', () => {
    it('matches every ZEV settings input holding sensitive data', () => {
        const form = {
            ...getDefaultZevForm(),
            name: 'ACME ZEV',
            bank_name: 'Test Bank',
            bank_iban: 'CH00 1234 5678',
        }

        // Mirrors the app root: the date picker inside the fields inherits the
        // app-level LocalizationProvider from DateLocaleProvider (main.tsx).
        document.body.innerHTML = renderToStaticMarkup(
            createElement(
                DateLocaleProvider,
                null,
                createElement(ZevGeneralSettingsFields, { form, onChange: () => {} }),
            ),
        )

        const matched = Array.from(document.querySelectorAll<HTMLInputElement>(BLUR_SELECTOR))
        expect(matched.map((el) => el.getAttribute('name')).sort()).toEqual(['bank_iban', 'bank_name', 'name'])

        // blurInputs only blurs inputs that carry a value, so a matched-but-empty
        // field would still render its contents unblurred.
        for (const el of matched) {
            expect((el.getAttribute('value') ?? '').trim()).not.toBe('')
        }
    })
})
