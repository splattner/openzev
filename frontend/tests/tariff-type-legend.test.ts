import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { TariffTypeLegend } from '../src/features/tariffs/TariffTypeIcon'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

const legend = (types: Array<string | null | undefined>) => renderToStaticMarkup(createElement(TariffTypeLegend, { types }))

describe('TariffTypeLegend', () => {
    it('deduplicates types in legend order', () => {
        const html = legend(['feed_in', 'grid', 'grid', null])
        expect(html.match(/energyTypes\.\w+/g)).toEqual(['energyTypes.grid', 'energyTypes.feed_in'])
        expect(html).not.toContain('energyTypes.local')
    })

    it('is absent when no tariff has an energy type', () => {
        expect(legend([null, undefined])).toBe('')
    })
})
