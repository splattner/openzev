import { act, createElement, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { ResponsiveTableHead, SortableHeader } from '../src/components/tableSorting'

const cleanups: Array<() => void> = []
afterEach(() => {
    cleanups.splice(0).reverse().forEach(cleanup => cleanup())
    vi.unstubAllGlobals()
})

async function render(children?: ReactNode) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    await act(async () => root.render(createElement('table', { tabIndex: -1 },
        createElement(ResponsiveTableHead, {}, children))))
    return container
}

it('allows an empty heading without inspecting a missing row', async () => {
    const view = await render()
    expect(view.querySelector('thead')?.dataset.cardLayout).toBe('false')
})

it('reads CSS card mode initially and on viewport resize without ResizeObserver', async () => {
    vi.stubGlobal('ResizeObserver', undefined)
    const style = document.createElement('style')
    style.textContent = '.responsive-table-head { --table-card-layout: 1; }'
    document.head.append(style)
    cleanups.push(() => style.remove())
    const view = await render(createElement('tr', { style: { display: 'grid' } },
        createElement(SortableHeader, { onSort: vi.fn(), direction: 'desc' }, 'Name')))
    const head = view.querySelector('thead')!
    expect(head.dataset.cardLayout).toBe('true')
    expect(head.querySelector('button')).toBeNull()
    expect(head.textContent).toBe('Name')

    head.style.setProperty('--table-card-layout', '0')
    await act(async () => window.dispatchEvent(new Event('resize')))
    expect(head.querySelector('button')).not.toBeNull()
    head.querySelector('button')!.focus()
    head.style.setProperty('--table-card-layout', '1')
    await act(async () => window.dispatchEvent(new Event('resize')))
    expect(head.querySelector('button')).toBeNull()
    expect(document.activeElement).toBe(view.querySelector('table'))
})
