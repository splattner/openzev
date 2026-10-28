import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { waitForCondition } from './helpers/waitForCondition'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key, i18n: { resolvedLanguage: 'en' } }),
}))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (value: string) => value,
}))

import { PeriodSelector } from '../src/components/PeriodSelector'

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

function mount(from: string, to: string, interval: 'monthly' | 'quarterly' = 'monthly') {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const onChange = vi.fn()
    act(() => root.render(createElement(MantineProvider, null, createElement(PeriodSelector, {
        interval, from, to, onChange, allowCustomRange: false, compact: true,
    }))))
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    return { container, onChange }
}

const trigger = (container: HTMLElement) => container.querySelector<HTMLButtonElement>('.period-selector-trigger')!

describe('compact period selector', () => {
    it('names the period and keeps its exact dates in the tooltip', () => {
        const { container } = mount('2026-09-01', '2026-09-30')
        expect(container.querySelector('.period-selector--compact')).not.toBeNull()
        expect(trigger(container).querySelector('.period-selector-name > span:not([aria-hidden])')?.textContent).toBe('September 2026')
        const sizers = [...trigger(container).querySelectorAll('.period-selector-name-sizer')]
        expect(sizers.every((sizer) => sizer.getAttribute('aria-hidden') === 'true')).toBe(true)
        expect(trigger(container).title).toBe('2026-09-01 → 2026-09-30')
        expect(container.textContent).not.toContain('pages.invoices.billingInterval')
    })

    it('steps with labelled chevrons', () => {
        const { container, onChange } = mount('2026-09-01', '2026-09-30')
        const previous = container.querySelector<HTMLButtonElement>('button[aria-label="pages.invoices.prevPeriod"]')!
        const next = container.querySelector<HTMLButtonElement>('button[aria-label="pages.invoices.nextPeriod"]')!
        expect(previous.textContent).toBe('')
        expect(previous.title).toBe('pages.invoices.prevPeriod')
        act(() => next.click())
        expect(onChange).toHaveBeenCalledWith({ from: '2026-10-01', to: '2026-10-31' })
        act(() => previous.click())
        expect(onChange).toHaveBeenLastCalledWith({ from: '2026-08-01', to: '2026-08-31' })
    })

    it('lists recent periods by name with their dates', async () => {
        // The menu counts back from today.
        vi.useFakeTimers({ toFake: ['Date'] })
        vi.setSystemTime(new Date('2026-10-02T12:00:00'))
        cleanups.push(() => vi.useRealTimers())
        const { container } = mount('2026-09-01', '2026-09-30')
        act(() => trigger(container).click())
        await waitForCondition(() => document.querySelector('.period-selector-preset') !== null, 'the period menu')
        const presets = [...document.querySelectorAll('.period-selector-preset')].map((preset) => preset.textContent)
        expect(presets.slice(0, 2)).toEqual([
            'October 20262026-10-01 → 2026-10-31 · common.periodSelector.currentPeriod',
            'September 20262026-09-01 → 2026-09-30',
        ])
        expect(document.querySelector('.period-selector-preset.active')?.textContent).toBe(presets[1])
    })

    it('steps from a range another community\'s interval left in the URL', () => {
        // A monthly community's September, after switching to a quarterly one.
        const { container, onChange } = mount('2026-09-01', '2026-09-30', 'quarterly')
        const previous = container.querySelector<HTMLButtonElement>('button[aria-label="pages.invoices.prevPeriod"]')!
        const next = container.querySelector<HTMLButtonElement>('button[aria-label="pages.invoices.nextPeriod"]')!
        expect(previous.disabled).toBe(false)
        expect(next.disabled).toBe(false)
        act(() => previous.click())
        expect(onChange).toHaveBeenLastCalledWith({ from: '2026-07-01', to: '2026-09-30' })
        act(() => next.click())
        expect(onChange).toHaveBeenLastCalledWith({ from: '2026-10-01', to: '2026-12-31' })
    })

    it('keeps the dates for a range that is not one billing period', () => {
        const { container } = mount('2026-09-03', '2026-09-30')
        expect(trigger(container).textContent).toContain('2026-09-03 → 2026-09-30')
        // Whole periods are all a compact selector offers: anything else is flagged.
        expect(trigger(container).querySelector('.issue-text--warning')?.textContent).toContain('common.periodSelector.notBillingPeriod')
        expect(trigger(container).textContent).not.toContain('common.periodSelector.custom')
        expect(trigger(container).title).toBe('')
    })
})
