import { act, createElement, createRef } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppTabs } from '../src/components/AppTabs'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>

beforeEach(() => {
    window.matchMedia ??= (() => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined })) as unknown as typeof window.matchMedia
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
})

afterEach(() => {
    act(() => root.unmount())
    container.remove()
})

function render(props: Record<string, unknown> = {}) {
    act(() => root.render(createElement(MantineProvider, null,
        createElement(AppTabs, { defaultValue: 'a', ...props },
            createElement(AppTabs.List, { 'aria-label': 'Views' },
                createElement(AppTabs.Tab, { value: 'a' }, 'A'),
                createElement(AppTabs.Tab, { value: 'b' }, 'B'),
            ),
            createElement(AppTabs.Panel, { value: 'a' }, 'panel a'),
            createElement(AppTabs.Panel, { value: 'b' }, 'panel b'),
        ),
    )))
}

describe('AppTabs', () => {
    it('applies the shared class mapping to the root, list, tabs and panels', () => {
        render()
        expect(container.querySelector('.app-tabs')).not.toBeNull()
        expect(container.querySelector('[role=tablist].app-tabs-list')).not.toBeNull()
        expect(container.querySelectorAll('[role=tab].app-tabs-tab')).toHaveLength(2)
        expect(container.querySelectorAll('[role=tabpanel].app-tabs-panel').length).toBeGreaterThan(0)
    })

    it('merges a caller class instead of dropping the shared one', () => {
        render({ classNames: { root: 'mine', tab: 'mine-tab' } })
        expect(container.querySelector('.app-tabs.mine')).not.toBeNull()
        expect(container.querySelectorAll('[role=tab].app-tabs-tab.mine-tab')).toHaveLength(2)
        expect(container.querySelector('[role=tablist].app-tabs-list')).not.toBeNull()
    })

    it('merges classes given as a function too', () => {
        render({ classNames: () => ({ list: 'mine-list' }) })
        expect(container.querySelector('[role=tablist].app-tabs-list.mine-list')).not.toBeNull()
        expect(container.querySelector('.app-tabs')).not.toBeNull()
    })

    it('keeps Mantine behaviour: roles, selection, keyboard and onChange', () => {
        const onChange = vi.fn()
        render({ onChange })
        const [a, b] = Array.from(container.querySelectorAll<HTMLElement>('[role=tab]'))
        expect(a.getAttribute('aria-selected')).toBe('true')
        expect(container.querySelector('[role=tablist]')?.getAttribute('aria-label')).toBe('Views')
        act(() => a.focus())
        act(() => { a.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })) })
        expect(document.activeElement).toBe(b)
        act(() => b.click())
        expect(onChange).toHaveBeenCalledWith('b')
        expect(b.getAttribute('aria-selected')).toBe('true')
    })

    it('does not mount an inactive panel with keepMounted off', () => {
        render({ keepMounted: false })
        expect(container.textContent).toContain('panel a')
        expect(container.textContent).not.toContain('panel b')
    })

    it('forwards its ref to the root element', () => {
        const ref = createRef<HTMLDivElement>()
        render({ ref })
        expect(ref.current).toBe(container.querySelector('.app-tabs'))
    })
})
