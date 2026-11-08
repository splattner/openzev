import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ZevGeneralSettingsFields } from '../src/components/ZevGeneralSettingsFields'
import type { ZevInput } from '../src/types/api'

/** ZEV settings payment section — client-side IBAN feedback. */
vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (k: string) => k,
        i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
}))

// The start date input formats its label with the app's date format.
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return { ...actual, useAppSettings: () => ({ settings: { date_format_short: 'dd.MM.yyyy' }, isLoading: false }) }
})

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

function renderFields(form: Partial<ZevInput>, zevId?: string, extra: { group?: 'general' | 'billing'; readOnly?: boolean } = {}) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    act(() => {
        root.render(
            createElement(
                MantineProvider,
                null,
                createElement(QueryClientProvider, { client: new QueryClient() }, createElement(MemoryRouter, null, createElement(ZevGeneralSettingsFields, {
                    form: { name: 'Z', start_date: '2026-01-01', ...form } as ZevInput,
                    onChange: () => {},
                    group: extra.group ?? 'billing',
                    readOnly: extra.readOnly,
                    zevId,
                }))),
            ),
        )
    })
    return container
}

describe('ZevGeneralSettingsFields IBAN feedback', () => {
    it('shows an inline error for a non-blank invalid IBAN', () => {
        const container = renderFields({ bank_iban: 'CH00' })
        const alert = container.querySelector('[role="alert"]')
        expect(alert?.textContent).toBe('pages.zevSettings.validation.invalidIban')
    })

    it('shows no error when the IBAN is blank', () => {
        const container = renderFields({ bank_iban: '' })
        expect(container.querySelector('[role="alert"]')).toBeNull()
    })

    it('shows no error for a valid IBAN', () => {
        const container = renderFields({ bank_iban: 'CH93 0076 2011 6238 5295 7' })
        expect(container.querySelector('[role="alert"]')).toBeNull()
    })
})

describe('ZevGeneralSettingsFields billing layout', () => {
    it('has three captioned sections and no box inside the sheet', () => {
        const container = renderFields({})
        const captions = Array.from(container.querySelectorAll('.form-section-header')).map(node => node.textContent)
        expect(captions).toEqual([
            'pages.zevSettings.sections.invoicing',
            'pages.zevSettings.sections.paymentRecipient',
            'pages.zevSettings.sections.vatAndRounding',
        ])
        expect(container.querySelector('.payment-recipient-section')).toBeNull()
    })

    it('links the creditor address to the issuer on the People tab, for an existing community only', () => {
        expect(renderFields({}).querySelector('a')).toBeNull()
        const link = renderFields({}, 'zev-1').querySelector('a')
        expect(link?.getAttribute('href')).toBe('/zev-settings/people')
        expect(link?.textContent).toBe('pages.zevSettings.fields.issuerLink')
    })

    it('explains the VAT mode that needs it, and asks for the number only when registered', () => {
        const hint = 'pages.zevSettings.fields.vatModeHint'
        expect(renderFields({ vat_mode: 'not_registered' }).textContent).not.toContain(hint)
        expect(renderFields({ vat_mode: 'inclusive' }).textContent).toContain(hint)
        expect(renderFields({ vat_mode: 'inclusive' }).querySelector('[data-zev-field="vat_number"]')).toBeNull()
        expect(renderFields({ vat_mode: 'registered' }).querySelector('[data-zev-field="vat_number"]')).not.toBeNull()
    })
})

describe('ZevGeneralSettingsFields general group', () => {
    it('has no clear button on the start date, which every community needs', () => {
        const container = renderFields({}, 'zev-1', { group: 'general' })
        const date = container.querySelector('[data-zev-field="start_date"]')
        expect(date?.querySelector('.mantine-DatePickerInput-input')?.textContent).toBe('01.01.2026')
        expect(date?.querySelector('.mantine-Input-section button')).toBeNull()
    })

    it('links the tariff address to the tariff import for someone who can edit, and not for a reader', () => {
        const editor = renderFields({}, 'zev-1', { group: 'general' })
        expect(editor.querySelector('[data-zev-field="tariff_source_url"] a')?.getAttribute('href')).toBe('/tariffs')

        const reader = renderFields({}, 'zev-1', { group: 'general', readOnly: true })
        expect(reader.querySelector('[data-zev-field="tariff_source_url"] a')).toBeNull()
    })
})
