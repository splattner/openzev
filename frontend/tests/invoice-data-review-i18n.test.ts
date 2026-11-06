import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import i18n from 'i18next'
import { I18nextProvider, initReactI18next } from 'react-i18next'
import { MemoryRouter } from 'react-router-dom'
import { en } from '../src/i18n/locales/en'
import { de } from '../src/i18n/locales/de'
import { fr } from '../src/i18n/locales/fr'
import { it as italian } from '../src/i18n/locales/it'
import type { Invoice } from '../src/types/api'

// No react-i18next mock here: this file renders through a real instance so
// plural resolution (_one/_other) is genuinely exercised.
import { InvoiceDataReviewNotice } from '../src/features/invoices/InvoiceDataReviewNotice'

vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { role: 'manager', memberships: [] } }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return {
        ...actual,
        useAppSettings: () => ({ settings: { date_format_short: 'dd.MM.yyyy' } }),
    }
})

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const instance = i18n.createInstance()

async function readyI18n() {
    if (instance.isInitialized) return
    await instance.use(initReactI18next).init({
        lng: 'en',
        fallbackLng: 'en',
        resources: { en: { translation: en } },
        interpolation: { escapeValue: false },
    })
}

describe('InvoiceDataReviewNotice evidence plural resolution', () => {
    let container: HTMLDivElement
    let root: ReturnType<typeof createRoot>

    beforeEach(async () => {
        await readyI18n()
        container = document.createElement('div')
        document.body.appendChild(container)
        root = createRoot(container)
    })

    afterEach(() => {
        act(() => root.unmount())
        container.remove()
    })

    function invoice(overrides: Partial<Invoice> = {}): Invoice {
        return {
            id: 'inv-1',
            invoice_number: 'INV-1',
            zev: 'zev-1',
            zev_name: 'ZEV 1',
            participant: 'p-1',
            participant_name: 'Anna',
            period_start: '2026-02-01',
            period_end: '2026-02-28',
            total_chf: '10.00',
            status: 'sent',
            ...overrides,
        }
    }

    it('renders resolved evidence sentences, not raw keys', () => {
        const inv = invoice({
            needs_data_review: true,
            open_data_impact_count: 4,
            data_impacts: [
                {
                    id: 'imp-1',
                    import_log: 'log-1',
                    evidence: { source: 'sdat-import', delivery_id: 'DEL-1', change_count: 4, day_from: '2026-02-03', day_to: '2026-02-04' },
                    created_at: '2026-03-01T23:30:00Z',
                    resolution: '',
                    resolved_at: null,
                },
                {
                    id: 'imp-csv', import_log: 'log-csv',
                    evidence: { source: 'csv-import', filename: 'correction.csv', change_count: 2,
                        day_from: '2026-02-03', day_to: '2026-02-04' },
                    created_at: '2026-03-01T23:30:00Z', resolution: '', resolved_at: null,
                },
                {
                    id: 'imp-reanchor', import_log: null,
                    evidence: { source: 'csv-reanchor', changed_readings: 2,
                        day_from: '2026-02-03', day_to: '2026-02-04' },
                    created_at: '2026-03-01T23:30:00Z', resolution: '', resolved_at: null,
                },
                {
                    id: 'imp-2',
                    import_log: null,
                    evidence: { source: 'import-deletion', deleted_readings: 1, day_from: '2026-02-05', day_to: '2026-02-05' },
                    created_at: '2026-03-02T10:00:00Z',
                    resolution: '',
                    resolved_at: null,
                },
            ],
        })
        act(() => {
            root.render(createElement(I18nextProvider, { i18n: instance },
                createElement(MemoryRouter, null,
                    createElement(InvoiceDataReviewNotice, { invoice: inv, canAct: true }))))
        })
        const text = container.textContent ?? ''
        // A missing `count` would render the raw key instead of a sentence.
        expect(text).toContain('Source CSV correction.csv recorded 2 reading changes between 03.02.2026 and 04.02.2026.')
        expect(text).toContain('flagged 02.03.2026')
        expect(text).toContain('CSV timestamps corrected for 2 readings between 03.02.2026 and 04.02.2026.')
        expect(text).not.toContain('pages.invoices.dataReview.evidenceImport')
        expect(text).not.toContain('pages.invoices.dataReview.evidenceDeletion')
        expect(text).toContain('Source delivery DEL-1 recorded 4 reading changes between 03.02.2026 and 04.02.2026.')
        expect(text).toContain('An import deletion removed 1 reading between 05.02.2026 and 05.02.2026.')
    })
})


describe('metering deletion confirmation translations', () => {
    it.each([['en', en], ['de', de], ['fr', fr], ['it', italian]] as const)(
        'keeps building and point parameters separate in %s', async (language, translations) => {
            const localized = i18n.createInstance()
            await localized.init({ lng: language, resources: { [language]: { translation: translations } } })
            const building = localized.t('pages.meteringPoints.buildings.deleteMessage', { name: 'BUILDING-TEST' })
            const point = localized.t('pages.meteringPoints.deleteMessage', { meterId: 'METER-TEST', assignmentCount: 3 })
            expect(building).toContain('BUILDING-TEST')
            expect(point).toContain('METER-TEST')
            expect(building + point).not.toContain('{{')
        },
    )
})
