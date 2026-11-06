import { describe, expect, it } from 'vitest'
import { de } from '../src/i18n/locales/de'
import { en } from '../src/i18n/locales/en'
import { fr } from '../src/i18n/locales/fr'
import { it as itLocale } from '../src/i18n/locales/it'

const LOCALES = { de, en, fr, it: itLocale }

const COMMUNITY = ['overview', 'energyBalance', 'metering', 'billing', 'reports', 'participants', 'meteringPoints', 'tariffs', 'zevSettings', 'feasibility'] as const
const PLATFORM = ['adminOverview', 'adminAccounts', 'adminTemplates', 'adminSystemSettings'] as const
const PARTICIPANT = ['dashboard', 'myDocuments', 'annualStatement'] as const

describe('sidebar labels', () => {
    for (const [name, locale] of Object.entries(LOCALES)) {
        it(`${name}: labels are distinct within community, platform and participant navigation`, () => {
            const nav = locale.nav
            for (const group of [COMMUNITY, PLATFORM, PARTICIPANT]) {
                const labels = group.map((key) => {
                    expect(nav[key], `nav.${key} is missing`).toBeTypeOf('string')
                    return nav[key]
                })
                expect(new Set(labels).size, `duplicate label in the ${name} sidebar`).toBe(labels.length)
            }
        })

        it(`${name}: the charts tab does not repeat the metering nav label`, () => {
            const nav = locale.nav
            expect(nav.meteringCharts).toBeTypeOf('string')
            expect(nav.meteringCharts).not.toBe(nav.metering)
        })
    }
})
