import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import i18n from '../src/i18n'
import { BillingPeriodCard } from '../src/components/BillingPeriodCard'
import type { PeriodCardEntry } from '../src/features/overview/periodCards'

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }), formatShortDate: (value: string) => value,
}))

const entry: PeriodCardEntry = {
    period: { start: '2026-06-01', end: '2026-06-30', interval: 'monthly', source: 'calendar', ended: true },
    alerts: [],
}

const savedLanguage = i18n.language
afterEach(async () => {
    await act(() => i18n.changeLanguage(savedLanguage))
    localStorage.removeItem('openzev.language')
})

describe('date labels on a language switch', () => {
    it('re-label a mounted component without remounting it', async () => {
        await act(() => i18n.changeLanguage('de'))
        const container = document.createElement('div')
        document.body.append(container)
        const root = createRoot(container)
        act(() => root.render(createElement(MemoryRouter, null, createElement(BillingPeriodCard, { entry }))))
        const heading = container.querySelector('h3')
        expect(heading?.textContent).toBe('Juni')

        await act(() => i18n.changeLanguage('fr'))
        expect(container.querySelector('h3')).toBe(heading)
        expect(heading?.textContent).toBe('juin')

        act(() => root.unmount())
        container.remove()
    })
})
