import { readdirSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import i18next from 'i18next'
import { describe, expect, it } from 'vitest'
import { de } from '../src/i18n/locales/de'
import { en } from '../src/i18n/locales/en'
import { fr } from '../src/i18n/locales/fr'
import { it as italian } from '../src/i18n/locales/it'
import { auditActionLabel, auditActorLabel, auditTargetLabel } from '../src/features/audit/auditEventText'
import type { AppSettings } from '../src/types/api'

const locales = { de, en, fr, it: italian }
const BACKEND = resolve(__dirname, '..', '..', 'backend')

async function translator(lng: keyof typeof locales) {
    const instance = i18next.createInstance()
    await instance.init({ lng, resources: { [lng]: { translation: locales[lng] } }, interpolation: { escapeValue: false } })
    return instance.t.bind(instance)
}

/** Every action type the backend writes with a literal, so a new one cannot ship without words. */
function backendActionTypes(): Set<string> {
    const found = new Set<string>()
    const walk = (dir: string) => {
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
            const path = join(dir, entry.name)
            if (entry.isDirectory()) {
                if (!['migrations', 'tests', '__pycache__', 'management'].includes(entry.name)) walk(path)
                continue
            }
            if (!entry.name.endsWith('.py') || /^test|tests\.py$|fixtures\.py$/.test(entry.name)) continue
            const source = readFileSync(path, 'utf8')
            for (const match of source.matchAll(/\baction_type=["']([a-z_.]+)["']/g)) found.add(match[1])
            for (const match of source.matchAll(/\b(?:audit_action_type|ACTION_[A-Z_]+) = ["']([a-z_.]+)["']/g)) {
                found.add(match[1])
                // AuditedCreateDestroyMixin derives the create and delete types from the update type.
                if (match[1].endsWith('.update') && source.includes('AuditedCreateDestroyMixin')) {
                    const prefix = match[1].slice(0, -'.update'.length)
                    found.add(`${prefix}.create`)
                    found.add(`${prefix}.delete`)
                }
            }
        }
    }
    walk(BACKEND)
    return found
}

/** Internal markers that only tests and demo seeding write; no user ever reads them. `revoke` is
 * only a parameter of the analytics-token audit helper, which prefixes it. */
const INTERNAL = new Set(['demo.seed.test', 'regression.marker', 'test.event', 'test.number_allocation', 'zev.test_event', 'revoke'])

describe('audit event names', () => {
    it('has a name in every language for every action type the backend writes', () => {
        const missing: string[] = []
        for (const type of [...backendActionTypes()].filter(type => !INTERNAL.has(type) && !type.startsWith('system.'))) {
            for (const [lng, locale] of Object.entries(locales)) {
                const label = type.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], (locale.pages as { auditLogs: { events: unknown } }).auditLogs.events)
                if (typeof label !== 'string' || !label) missing.push(`${lng}: ${type}`)
            }
        }
        expect(missing).toEqual([])
    })

    it('names an event in the reader\'s language, not in the stored English sentence', async () => {
        const event = { action_type: 'invoice.approve', summary: 'Participant tried to approve an invoice.' }
        expect(auditActionLabel(await translator('de'), event)).toBe('Rechnung genehmigen')
        expect(auditActionLabel(await translator('fr'), event)).toBe('Approuver une facture')
    })

    it('falls back to the stored sentence for a type it has no name for, never to the code', async () => {
        const event = { action_type: 'future.thing', summary: 'Did a future thing.' }
        expect(auditActionLabel(await translator('de'), event)).toBe('Did a future thing.')
    })

    it('says who acted when no person did', async () => {
        const t = await translator('de')
        expect(auditActorLabel(t, { actor_display: 'owner@example.com', source: 'api' })).toBe('owner@example.com')
        expect(auditActorLabel(t, { actor_display: '', source: 'celery' })).toBe('System')
        expect(auditActorLabel(t, { actor_display: '', source: 'invoice_link' })).toBe('Rechnungslink')
        expect(auditActorLabel(t, { actor_display: '', source: 'api' })).toBe('Nicht angemeldet')
    })

    it('names a batch run by its period instead of an internal type', () => {
        const settings = { date_format_short: 'dd.MM.yyyy' } as AppSettings
        expect(auditTargetLabel({ target_display: 'INV-00006', metadata_json: {} }, settings)).toBe('INV-00006')
        expect(auditTargetLabel({ target_display: '', metadata_json: { period_start: '2026-07-01', period_end: '2026-09-30' } }, settings))
            .toBe('01.07.2026 – 30.09.2026')
        expect(auditTargetLabel({ target_display: '', metadata_json: {} }, settings)).toBe('')
    })
})
