import { act, createElement, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Disclosure } from '../src/components/Disclosure'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>

beforeEach(() => {
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
})

afterEach(() => {
    act(() => root.unmount())
    container.remove()
})

const details = () => container.querySelector('details') as HTMLDetailsElement

/** jsdom does not fire `toggle` itself; do what a click on the summary does. */
function toggle() {
    act(() => {
        details().open = !details().open
        details().dispatchEvent(new Event('toggle'))
    })
}

describe('Disclosure', () => {
    it('is a closed details element with the shared class and its summary', () => {
        act(() => root.render(createElement(Disclosure, { summary: 'History' }, 'body')))
        expect(details().classList.contains('disclosure')).toBe(true)
        expect(details().open).toBe(false)
        expect(details().querySelector('summary')?.textContent).toBe('History')
    })

    it('adds the host modifier next to the shared class', () => {
        act(() => root.render(createElement(Disclosure, { summary: 's', className: 'overview-period-details' }, 'body')))
        expect(details().className).toBe('disclosure overview-period-details')
    })

    it('opens by default when asked to', () => {
        act(() => root.render(createElement(Disclosure, { summary: 's', defaultOpen: true }, 'body')))
        expect(details().open).toBe(true)
    })

    it('mounts a lazy body only while open', () => {
        act(() => root.render(createElement(Disclosure, { summary: 's', lazy: true }, createElement('p', { className: 'body' }, 'x'))))
        expect(container.querySelector('.body')).toBeNull()
        toggle()
        expect(container.querySelector('.body')).not.toBeNull()
        toggle()
        expect(container.querySelector('.body')).toBeNull()
    })

    it('keeps a body that is not lazy mounted while closed', () => {
        act(() => root.render(createElement(Disclosure, { summary: 's' }, createElement('p', { className: 'body' }, 'x'))))
        expect(container.querySelector('.body')).not.toBeNull()
    })

    it('follows a caller that owns the open state, and reports only real changes', () => {
        const seen = vi.fn()
        function Host() {
            const [open, setOpen] = useState(false)
            return createElement(Disclosure, { summary: 's', open, onOpenChange: (next: boolean) => { seen(next); setOpen(next) } }, 'body')
        }
        act(() => root.render(createElement(Host)))
        // The attribute set from `open` raises a toggle of its own: not a change.
        act(() => { details().dispatchEvent(new Event('toggle')) })
        expect(seen).not.toHaveBeenCalled()
        toggle()
        expect(seen).toHaveBeenCalledExactlyOnceWith(true)
        expect(details().open).toBe(true)
    })
})
