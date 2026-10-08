import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FilterTabs, type FilterTab } from '../src/components/FilterTabs'

const cleanups: (() => void)[] = []
afterEach(() => {
    cleanups.splice(0).forEach((cleanup) => cleanup())
})

async function render(tabs: FilterTab<string>[], value = 'all', onChange = vi.fn()) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    await act(async () => root.render(createElement(FilterTabs<string>, { label: 'Views', tabs, value, onChange })))
    return container
}

const shownTabs = (container: HTMLElement) =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('.filter-tab')).map((tab) => tab.textContent)

describe('FilterTabs', () => {
    it('leaves out a tab with nothing to show or with the default’s count', async () => {
        const container = await render([
            { value: 'all', label: 'All', count: 5 },
            { value: 'empty', label: 'Empty', count: 0 },
            { value: 'same', label: 'Same', count: 5 },
            { value: 'some', label: 'Some', count: 2 },
        ])
        expect(shownTabs(container)).toEqual(['All 5', 'Some 2'])
    })

    it('keeps the active tab, so it can be cleared', async () => {
        const container = await render([
            { value: 'all', label: 'All', count: 5 },
            { value: 'empty', label: 'Empty', count: 0 },
        ], 'empty')
        expect(shownTabs(container)).toEqual(['All 5', 'Empty 0'])
    })

    it('keeps an attention tab while it has a count, even the default’s', async () => {
        const container = await render([
            { value: 'all', label: 'All', count: 3 },
            { value: 'warn', label: 'Warn', count: 3, attention: true },
            { value: 'quiet', label: 'Quiet', count: 0, attention: true },
        ])
        expect(shownTabs(container)).toEqual(['All 3', 'Warn 3'])
        expect(container.querySelector('.filter-tab--attention')?.textContent).toBe('Warn 3')
    })

    it('leaves the group out when only the default is left', async () => {
        const container = await render([
            { value: 'all', label: 'All', count: 4 },
            { value: 'empty', label: 'Empty', count: 0 },
            { value: 'same', label: 'Same', count: 4 },
        ])
        expect(container.querySelector('[role="group"]')).toBeNull()
    })

    it('selects a tab, and returns to the default when the active tab is pressed', async () => {
        const onChange = vi.fn()
        const tabs = [{ value: 'all', label: 'All', count: 5 }, { value: 'some', label: 'Some', count: 2 }]
        let container = await render(tabs, 'all', onChange)
        const some = () => Array.from(container.querySelectorAll<HTMLButtonElement>('.filter-tab'))[1]
        expect(some().getAttribute('aria-pressed')).toBe('false')
        await act(async () => some().click())
        expect(onChange).toHaveBeenLastCalledWith('some')

        container = await render(tabs, 'some', onChange)
        expect(some().getAttribute('aria-pressed')).toBe('true')
        await act(async () => some().click())
        expect(onChange).toHaveBeenLastCalledWith('all')
    })
})
