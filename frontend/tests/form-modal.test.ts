import { act, createElement, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FormModal } from '../src/components/FormModal'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}))

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>

function renderModal(isOpen: boolean, onClose: () => void) {
    act(() => {
        root.render(createElement(StrictMode, null, createElement(FormModal, { isOpen, title: 'Title', onClose }, createElement('button', { type: 'button' }, 'inner'))))
    })
}

beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
})

afterEach(() => {
    act(() => root.unmount())
    container.remove()
})

describe('FormModal accessibility', () => {
    it('exposes dialog semantics with a labelled close button', () => {
        renderModal(true, () => undefined)
        const dialog = container.querySelector('[role=dialog]') as HTMLElement
        expect(dialog.getAttribute('aria-modal')).toBe('true')
        const title = container.querySelector('h2') as HTMLElement
        expect(dialog.getAttribute('aria-labelledby')).toBe(title.id)
        const close = container.querySelector('[aria-label="common.close"]') as HTMLButtonElement
        expect(close.tagName).toBe('BUTTON')
        expect(close.querySelector('[aria-hidden="true"]')).not.toBeNull()
    })

    it('closes on Escape', () => {
        const onClose = vi.fn()
        renderModal(true, onClose)
        act(() => {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
        })
        expect(onClose).toHaveBeenCalled()
    })

    it('only the top-most stacked modal closes on Escape', () => {
        const onCloseOuter = vi.fn()
        const onCloseInner = vi.fn()
        act(() => {
            root.render(createElement('div', null,
                createElement(FormModal, { isOpen: true, title: 'Outer', onClose: onCloseOuter }, 'outer'),
                createElement(FormModal, { isOpen: true, title: 'Inner', onClose: onCloseInner }, 'inner'),
            ))
        })
        act(() => {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
        })
        expect(onCloseInner).toHaveBeenCalledTimes(1)
        expect(onCloseOuter).not.toHaveBeenCalled()
    })

    it('focuses the dialog on open and restores focus on close', () => {
        const opener = document.createElement('button')
        opener.textContent = 'opener'
        document.body.appendChild(opener)
        opener.focus()
        const onClose = vi.fn()
        renderModal(true, onClose)
        expect(document.activeElement?.getAttribute('role')).toBe('dialog')
        renderModal(false, onClose)
        expect(document.activeElement).toBe(opener)
        opener.remove()
    })

    it('traps Tab inside the dialog', () => {
        renderModal(true, () => undefined)
        const dialog = container.querySelector('[role=dialog]') as HTMLElement
        const buttons = Array.from(dialog.querySelectorAll('button'))
        const last = buttons[buttons.length - 1]
        last.focus()
        act(() => {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
        })
        expect(document.activeElement).toBe(buttons[0])
    })

    it('keeps input focus across re-renders with a fresh onClose', () => {
        renderModal(true, () => undefined)
        const dialog = container.querySelector('[role=dialog]') as HTMLElement
        const inner = dialog.querySelector('button') as HTMLButtonElement
        inner.focus()
        expect(document.activeElement).toBe(inner)
        // Parent state updates recreate onClose every render: focus must stay.
        renderModal(true, () => undefined)
        expect(document.activeElement).toBe(inner)
    })
})
