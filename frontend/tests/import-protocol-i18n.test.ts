import { readFileSync } from 'node:fs'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18next from 'i18next'
import { I18nextProvider, initReactI18next } from 'react-i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ImportProtocolModal } from '../src/features/imports/ImportProtocolModal'
import { queryKeys } from '../src/lib/api/queryKeys'
import { en } from '../src/i18n/locales/en'
import { de } from '../src/i18n/locales/de'
import { fr } from '../src/i18n/locales/fr'
import { it as italian } from '../src/i18n/locales/it'
import type { ImportLog, SdatIssue } from '../src/types/api'

vi.mock('../src/lib/api/metering', () => ({ fetchImportLog: vi.fn(), fetchHeldMeteringReadings: vi.fn() }))
vi.mock('../src/lib/appSettings', () => ({ useAppSettings: () => ({ settings: {} }), formatDateTime: (value: string) => value }))

const locales = { en, de, fr, it: italian }
const backend = readFileSync('../backend/metering/importers/sdatch_importer.py', 'utf8')
const issueCodes = Array.from(backend.matchAll(/^ISSUE_[A-Z_]+ = "([a-z_]+)"/gm), match => match[1])
const detailCodes = new Set(Array.from(backend.matchAll(/detail_code="([a-z_]+)"/g), match => match[1]))
const raw = 'Skipped 2 observations superseded by newer deliveries; nothing changed.'
let container: HTMLDivElement
let root: ReturnType<typeof createRoot>
let client: QueryClient
beforeEach(() => {
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
})
afterEach(() => {
    act(() => root.unmount())
    client.clear()
    container.remove()
})

async function render(language: keyof typeof locales, issues: SdatIssue[]) {
    const instance = i18next.createInstance()
    await instance.use(initReactI18next).init({
        lng: language, fallbackLng: false,
        resources: { [language]: { translation: locales[language] } },
        interpolation: { escapeValue: false },
    })
    const log: ImportLog = {
        id: 'localized', filename: 'delivery.xml', created_at: '2026-11-05T10:00:00Z', source: 'sdatch',
        rows_imported: 0, rows_overwritten: 0, rows_skipped: 2, result_status: 'unchanged',
        issues, reading_changes: [],
    }
    client.setQueryData(queryKeys.metering.importLog(log.id), log)
    await act(async () => root.render(createElement(I18nextProvider, { i18n: instance },
        createElement(QueryClientProvider, { client }, createElement(ImportProtocolModal, { log, onClose: () => undefined })),
    )))
    return document.querySelector('[role="dialog"]')!.textContent!
}

describe.each(Object.keys(locales) as Array<keyof typeof locales>)('SDAT protocol in %s', language => {
    it('translates every supported backend issue code', () => {
        expect(issueCodes.length).toBeGreaterThan(40)
        const messages = locales[language].pages.imports.issues
        for (const code of issueCodes) expect(messages, code).toHaveProperty(code, expect.any(String))
        expect(detailCodes.size).toBeGreaterThan(0)
        for (const code of detailCodes) expect(locales[language].pages.imports.issueDetails, code).toHaveProperty(code, expect.any(String))
    })

    it('uses translated findings and structured evidence independently of backend wording', async () => {
        const issues: SdatIssue[] = [
            { code: 'stale_superseded', severity: 'info', message: raw, stale: 2, block_id: 'DOC-19' },
            { code: 'future_code', severity: 'error', message: 'Unmapped English diagnostic.' },
        ]
        const text = await render(language, issues)
        expect(text).toContain(locales[language].pages.imports.issues.stale_superseded)
        expect(text).toContain(locales[language].pages.imports.protocol.issueParam.stale)
        expect(text).toContain('2')
        expect(text).toContain('DOC-19')
        expect(text).toContain('future_code')
        expect(text).not.toContain(raw)
        expect(text).not.toContain('Unmapped English diagnostic.')
        expect(await render(language, issues.map(issue => ({ ...issue, message: 'Completely reworded backend prose.' })))).toBe(text)
    })

    it('keeps diagnostic values and locations with translated detail and fallback messages', async () => {
        const text = await render(language, [
            { code: 'invalid_volume', detail_code: 'negative_volume', severity: 'error', message: 'Negative volume -1.2345.', volume: '-1.2345', position: 19 },
            { code: 'schema_invalid', severity: 'error', message: 'Element Status violates schema.', xml_line: 73, xml_path: '/Delivery/Status', xml_error_type: 'SCHEMAV_CVC_ENUMERATION_VALID' },
            { code: 'invalid_interval', detail_code: 'future_variant', severity: 'error', message: 'New English detail.' },
            { code: 'meter_direction_mismatch', severity: 'error', message: 'Wrong meter type.', meter_type: 'consumption' },
        ])
        const messages = locales[language].pages.imports
        expect(text).toContain(messages.issueDetails.negative_volume)
        expect(text).toContain('-1.2345')
        expect(text).toContain(messages.protocol.issueParam.xml_line)
        expect(text).toContain('73')
        expect(text).toContain('/Delivery/Status')
        expect(text).toContain('SCHEMAV_CVC_ENUMERATION_VALID')
        expect(text).toContain(messages.issues.invalid_interval)
        expect(text).toContain(locales[language].pages.meteringPoints.meterTypes.consumption)
        expect(text).not.toContain('future_variant')
        expect(text).not.toContain('Negative volume')
        expect(text).not.toContain('violates schema')
        expect(text).not.toContain('New English detail')
    })
})
