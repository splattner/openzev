import { act, createElement, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ConfirmDialog } from '../src/components/ConfirmDialog'
import { FormModal } from '../src/components/FormModal'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}))

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>

beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
})

afterEach(() => {
    act(() => root.unmount())
    container.remove()
})

describe('FormModal stacking', () => {
    function renderStacked(outerOpen: boolean, innerOpen: boolean, onCloseOuter: () => void, onCloseInner: () => void) {
        act(() => {
            root.render(createElement('div', null,
                createElement(FormModal, { isOpen: outerOpen, title: 'Outer', onClose: onCloseOuter }, 'outer'),
                createElement(FormModal, { isOpen: innerOpen, title: 'Inner', onClose: onCloseInner }, 'inner'),
            ))
        })
    }

    it('Escape cancels the overwrite confirmation without closing the import modal', () => {
        const onCloseModal = vi.fn()
        const onCancelConfirm = vi.fn()
        act(() => {
            root.render(createElement('div', null,
                createElement(FormModal, { isOpen: true, title: 'Import', onClose: onCloseModal }, 'import'),
                createElement(ConfirmDialog, {
                    title: 'Overwrite',
                    message: 'Confirm overwrite',
                    onConfirm: vi.fn(),
                    onCancel: onCancelConfirm,
                }),
            ))
        })

        act(() => {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
        })

        expect(onCancelConfirm).toHaveBeenCalledOnce()
        expect(onCloseModal).not.toHaveBeenCalled()
    })

    it('closing the inner dialog returns focus to the outer dialog', () => {
        const noop = () => undefined
        renderStacked(true, true, noop, noop)
        const dialogs = container.querySelectorAll('[role=dialog]')
        expect(document.activeElement).toBe(dialogs[1])
        renderStacked(true, false, noop, noop)
        expect(document.activeElement).toBe(dialogs[0])
    })

    it('returns focus to the wizard action after cancelling its confirmation', () => {
        const render = (confirmOpen: boolean) => act(() => {
            root.render(createElement(StrictMode, null,
                createElement(FormModal, { isOpen: true, title: 'Import', onClose: vi.fn() },
                    createElement('button', { id: 'start-import' }, 'Start')),
                confirmOpen && createElement(ConfirmDialog, {
                    title: 'Overwrite', message: 'Confirm', onConfirm: vi.fn(), onCancel: vi.fn(),
                }),
            ))
        })
        render(false)
        const opener = container.querySelector('#start-import') as HTMLButtonElement
        opener.focus()
        render(true)
        expect(container.querySelectorAll('[role=dialog]')[1].contains(document.activeElement)).toBe(true)
        render(false)
        expect(document.activeElement).toBe(opener)
    })

    it('only the top dialog traps Tab; background modal stays inert', () => {
        const noop = () => undefined
        act(() => {
            root.render(createElement('div', null,
                createElement(FormModal, {
                    isOpen: true, title: 'Outer', onClose: noop,
                }, createElement('button', { type: 'button' }, 'outer-btn')),
                createElement(FormModal, {
                    isOpen: true, title: 'Inner', onClose: noop,
                }, createElement('button', { type: 'button' }, 'inner-btn')),
            ))
        })
        const dialogs = container.querySelectorAll('[role=dialog]')
        const outerBtn = dialogs[0].querySelector('button') as HTMLButtonElement
        const innerBtn = dialogs[1].querySelector('button') as HTMLButtonElement
        // Focus sits in the background dialog (e.g. wizard input kept focus
        // when the overwrite confirmation opened). Tab must pull it into the
        // top dialog instead of cycling behind the confirmation.
        outerBtn.focus()
        expect(document.activeElement).toBe(outerBtn)
        act(() => {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
        })
        expect(document.activeElement).toBe(innerBtn)
    })

    it('Shift+Tab from outside a newly opened modal wraps to its last control', () => {
        const noop = () => undefined
        act(() => {
            root.render(createElement('div', null,
                createElement('button', { type: 'button', id: 'behind' }, 'behind'),
                createElement(FormModal, {
                    isOpen: true, title: 'Top', onClose: noop,
                }, [
                    createElement('button', { type: 'button', key: 'a' }, 'first'),
                    createElement('button', { type: 'button', key: 'b' }, 'last'),
                ]),
            ))
        })
        const dialog = container.querySelector('[role=dialog]') as HTMLElement
        const buttons = Array.from(dialog.querySelectorAll('button'))
        const behind = container.querySelector('#behind') as HTMLButtonElement
        behind.focus()
        act(() => {
            const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })
            Object.defineProperty(event, 'shiftKey', { value: true })
            document.dispatchEvent(event)
        })
        expect(document.activeElement).toBe(buttons[buttons.length - 1])
    })

    it('overwrite confirmation traps focus and exposes dialog semantics', () => {
        act(() => {
            root.render(createElement('div', null,
                createElement(FormModal, { isOpen: true, title: 'Import', onClose: () => undefined },
                    createElement('button', { type: 'button' }, 'wizard-btn')),
                createElement(ConfirmDialog, {
                    title: 'Overwrite',
                    message: 'Confirm overwrite',
                    onConfirm: vi.fn(),
                    onCancel: vi.fn(),
                }),
            ))
        })
        const dialogs = container.querySelectorAll('[role=dialog]')
        expect(dialogs.length).toBe(2)
        const confirm = dialogs[1] as HTMLElement
        expect(confirm.getAttribute('aria-modal')).toBe('true')
        expect(confirm.getAttribute('aria-labelledby')).toBeTruthy()
        // Focus moved into the confirmation on open, not left in the wizard.
        expect(confirm.contains(document.activeElement as Node)).toBe(true)
        const buttons = Array.from(confirm.querySelectorAll('button'))
        buttons[buttons.length - 1].focus()
        act(() => {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
        })
        expect(document.activeElement).toBe(buttons[0])
    })
})
