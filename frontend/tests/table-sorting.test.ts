import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SortableHeader, useTableSorting } from '../src/components/tableSorting'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ i18n: { language: 'de-CH' } }) }))

type Row = { id: string; amount: number | null }
const data: Row[] = [{ id: 'z', amount: 10 }, { id: 'a', amount: 2 }, { id: 'missing', amount: null }]
let cleanup: (() => void) | undefined
afterEach(() => cleanup?.())

function mount() {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    cleanup = () => { act(() => root.unmount()); container.remove() }
    function Table({ rows, names }: { rows: Row[]; names: Record<string, string> }) {
        const sorting = useTableSorting(rows, { name: row => names[row.id], amount: row => row.amount })
        return createElement('table', {},
            createElement('thead', {}, createElement('tr', {},
                createElement(SortableHeader, { ...sorting.header('name') }, 'Name'),
                createElement(SortableHeader, { ...sorting.header('amount') }, 'Amount'))),
            createElement('tbody', {}, sorting.rows.map(row => createElement('tr', { key: row.id }, createElement('td', {}, row.id)))))
    }
    const render = async (rows = data, names = { z: 'Zürcher', a: 'Äberli', missing: 'Missing' }) => {
        await act(async () => root.render(createElement(Table, { rows, names })))
    }
    const click = async (column: number) => {
        await act(async () => container.querySelectorAll('th')[column].querySelector('button')!.click())
    }
    const ids = () => Array.from(container.querySelectorAll('td')).map(cell => cell.textContent)
    return { container, render, click, ids }
}

describe('custom-table sorting', () => {
    it('sorts numeric values in both directions, keeps missing values last, and restores source order', async () => {
        const view = mount()
        await view.render()
        await view.click(1)
        expect(view.ids()).toEqual(['z', 'a', 'missing'])
        await view.click(1)
        expect(view.ids()).toEqual(['a', 'z', 'missing'])
        await view.click(1)
        expect(view.ids()).toEqual(data.map(row => row.id))
        expect(view.container.querySelector('th[aria-sort]')).toBeNull()
        expect(data.map(row => row.id)).toEqual(['z', 'a', 'missing'])
    })

    it('uses locale collation and refreshes lookup-backed values without replacing data', async () => {
        const view = mount()
        const rows = data.slice(0, 2)
        await view.render(rows)
        await view.click(0)
        expect(view.ids()).toEqual(['a', 'z'])
        await view.render(rows, { z: 'Aaron', a: 'Zulu', missing: 'Missing' })
        expect(view.ids()).toEqual(['z', 'a'])
    })

    it('orders numbered names naturally and shows direction only while sorted', async () => {
        const view = mount()
        await view.render(data.slice(0, 2), { z: 'Group 10', a: 'Group 2', missing: '' })
        const icon = () => view.container.querySelector('th span[aria-hidden="true"]')?.textContent
        expect(icon()).toBe('')
        expect(view.container.querySelector('th[aria-sort]')).toBeNull()
        await view.click(0)
        expect(view.ids()).toEqual(['a', 'z'])
        expect(icon()).toBe('▲')
        await view.click(0)
        expect(view.ids()).toEqual(['z', 'a'])
        expect(icon()).toBe('▼')
        await view.click(0)
        expect(icon()).toBe('')
    })

    it('retains sorting through a one-row filter and returns focus to its header', async () => {
        const view = mount()
        await view.render()
        await view.click(0)
        const header = view.container.querySelector('th')!
        header.querySelector('button')!.focus()
        await view.render([data[0]])
        expect(view.container.querySelector('th button, th[aria-sort]')).toBeNull()
        expect(document.activeElement).toBe(header)
        await view.render()
        expect(view.ids()).toEqual(['a', 'missing', 'z'])
    })
})
