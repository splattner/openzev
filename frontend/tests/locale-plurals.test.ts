import i18next from 'i18next'
import { describe, expect, it } from 'vitest'
import { de } from '../src/i18n/locales/de'
import { en } from '../src/i18n/locales/en'
import { fr } from '../src/i18n/locales/fr'
import { it as itLocale } from '../src/i18n/locales/it'

const locales = { en, de, fr, it: itLocale }

function leaves(obj: Record<string, unknown>, prefix = ''): Array<[string, unknown]> {
    return Object.entries(obj).flatMap(([key, value]) => value !== null && typeof value === 'object'
        ? leaves(value as Record<string, unknown>, `${prefix}${key}.`) : [[`${prefix}${key}`, value] as [string, unknown]])
}

describe('plural keys', () => {
    it.each(Object.entries(locales))('%s: every _one has its _other', (_lang, locale) => {
        const all = new Map(leaves(locale))
        for (const path of all.keys()) {
            if (path.endsWith('_one')) expect(all.has(path.replace(/_one$/, '_other')), `${path} has no _other`).toBe(true)
        }
    })

    // Exact output, so a missing placeholder fails too. French uses the singular for 0 as well.
    it.each([
        ['en', 'pages.dynamicSources.reuseTariffs', 1, '1 tariff'],
        ['en', 'pages.dynamicSources.reuseTariffs', 2, '2 tariffs'],
        ['en', 'pages.dynamicSources.reuseZevs', 1, '1 ZEV'],
        ['de', 'pages.dynamicSources.reuseTariffs', 1, '1 Tarif'],
        ['fr', 'pages.dynamicSources.history.coverage', 1, '1 point stocké · couverture A – B'],
        ['fr', 'pages.dynamicSources.history.coverage', 0, '0 point stocké · couverture A – B'],
        ['it', 'pages.dynamicSources.history.coverage', 1, '1 punto memorizzato · copertura A – B'],
        ['en', 'account.mfa.recoveryCodesRemaining', 1, '1 unused recovery code left.'],
        ['en', 'account.mfa.recoveryCodesRemaining', 8, '8 unused recovery codes left.'],
        ['en', 'pages.backups.restore.done', 1, 'Restored 1 record.'],
    ] as const)('%s %s with %i is "%s"', async (lang, key, count, expected) => {
        const i18n = i18next.createInstance()
        await i18n.init({ lng: lang, resources: { [lang]: { translation: locales[lang] } }, interpolation: { escapeValue: false } })
        expect(i18n.t(key, { count, from: 'A', to: 'B' })).toBe(expected)
    })

    it('puts the reuse counts into one sentence', async () => {
        const i18n = i18next.createInstance()
        await i18n.init({ lng: 'en', resources: { en: { translation: en } }, interpolation: { escapeValue: false } })
        const [tariffs, zevs] = [i18n.t('pages.dynamicSources.reuseTariffs', { count: 1 }), i18n.t('pages.dynamicSources.reuseZevs', { count: 3 })]
        expect(i18n.t('pages.dynamicSources.globalReuseSummary', { tariffs, zevs })).toBe('Across the platform: 1 tariff · 3 ZEVs')
        expect(i18n.t('pages.dynamicSources.reuseSummary', { tariffs, zevs })).toBe('1 tariff · 3 ZEVs')
    })
})
