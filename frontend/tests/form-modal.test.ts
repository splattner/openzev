import { act, createElement, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FormModal } from '../src/components/FormModal'
import { FormModalFooter } from '../src/components/FormModalFooter'

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

    it('restores an explicit opener after loading has moved focus elsewhere', () => {
        const opener = document.createElement('button')
        document.body.appendChild(opener)
        const returnFocusRef = { current: opener }
        const render = (isOpen: boolean) => act(() => root.render(createElement(StrictMode, null,
            createElement(FormModal, { isOpen, title: 'Loaded', onClose: vi.fn(), returnFocusRef }, 'history'))))
        opener.focus()
        opener.disabled = true
        opener.blur()
        render(true)
        expect(document.activeElement?.getAttribute('role')).toBe('dialog')
        opener.disabled = false
        render(false)
        expect(document.activeElement).toBe(opener)
        opener.remove()
    })

    it('keeps input focus across re-renders with a fresh returnFocusRef', () => {
        const render = () => act(() => root.render(createElement(FormModal,
            { isOpen: true, title: 'Title', onClose: vi.fn(), returnFocusRef: { current: null } },
            createElement('input'),
        )))
        render()
        const input = container.querySelector('input')!
        input.focus()
        render()
        expect(document.activeElement).toBe(input)
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

describe('FormModal size', () => {
    const render = (props: Record<string, unknown>) => act(() => root.render(
        createElement(FormModal, { isOpen: true, title: 'Title', onClose: vi.fn(), ...props }, 'body'),
    ))

    it('defaults to sm and maps each size to its class', () => {
        render({})
        const dialog = () => container.querySelector('[role=dialog]') as HTMLElement
        expect(dialog().classList.contains('form-modal-sm')).toBe(true)
        for (const size of ['xs', 'sm', 'md', 'lg', 'xl']) {
            render({ size })
            expect(dialog().classList.contains(`form-modal-${size}`)).toBe(true)
        }
    })

    it('lets a legacy maxWidth win until the last caller has moved', () => {
        render({ maxWidth: '520px' })
        expect((container.querySelector('[role=dialog]') as HTMLElement).style.maxWidth).toBe('520px')
        render({})
        expect((container.querySelector('[role=dialog]') as HTMLElement).style.maxWidth).toBe('')
    })
})

describe('FormModal dirty guard', () => {
    const onClose = vi.fn()

    function Form({ cancel = false }: { cancel?: boolean }) {
        return createElement('form', null,
            createElement('input', { name: 'name', defaultValue: 'saved' }),
            cancel ? createElement(FormModalFooter, { onCancel: onClose, isPending: false }) : null,
        )
    }

    function open(props: Record<string, unknown> = {}, cancel = false) {
        act(() => root.render(createElement(FormModal, { isOpen: true, title: 'Title', onClose, ...props }, createElement(Form, { cancel }))))
    }

    /** What a user does: press a key in the field, then the value changes. */
    function type(value: string) {
        const input = container.querySelector('input') as HTMLInputElement
        act(() => { input.dispatchEvent(new KeyboardEvent('keydown', { key: 'x', bubbles: true })) })
        input.value = value
    }

    const close = () => act(() => { (container.querySelector('[aria-label="common.close"]') as HTMLButtonElement).click() })
    const escape = () => act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    const scrim = () => act(() => { (container.querySelector('.dialog-scrim') as HTMLElement).click() })
    const asked = () => document.body.querySelector('.confirm-dialog')
    const choose = (label: string) => act(() => {
        Array.from(document.body.querySelectorAll('.confirm-dialog button')).find((b) => b.textContent === label)!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    beforeEach(() => onClose.mockClear())

    it('closes straight away when nothing was changed', () => {
        open()
        close()
        expect(onClose).toHaveBeenCalledOnce()
        expect(asked()).toBeNull()
    })

    it('treats a form the user only looked at as clean', () => {
        open()
        act(() => { (container.querySelector('input') as HTMLInputElement).dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })) })
        escape()
        expect(onClose).toHaveBeenCalledOnce()
    })

    it.each([
        ['X', close],
        ['Escape', escape],
        ['a click on the scrim', scrim],
    ])('asks before %s drops a change', (_name, dismiss) => {
        open()
        type('changed')
        dismiss()
        expect(onClose).not.toHaveBeenCalled()
        expect(asked()?.textContent).toContain('common.unsavedChanges.title')
    })

    it('asks before Cancel in the footer drops a change', () => {
        open({}, true)
        type('changed')
        act(() => { (Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'common.cancel') as HTMLButtonElement).click() })
        expect(onClose).not.toHaveBeenCalled()
        expect(asked()).not.toBeNull()
    })

    it('keeps the dialog and the draft when the user stays', () => {
        open()
        type('changed')
        close()
        choose('common.unsavedChanges.keepEditing')
        expect(onClose).not.toHaveBeenCalled()
        expect(asked()).toBeNull()
        expect((container.querySelector('input') as HTMLInputElement).value).toBe('changed')
    })

    it('closes once the user agrees to discard', () => {
        open()
        type('changed')
        close()
        choose('common.unsavedChanges.discard')
        expect(onClose).toHaveBeenCalledOnce()
    })

    it('is clean again after the change is undone', () => {
        open()
        type('changed')
        type('saved')
        close()
        expect(onClose).toHaveBeenCalledOnce()
    })

    it('lets the confirmation take Escape before the dialog', () => {
        open()
        type('changed')
        escape()
        escape()
        expect(asked()).toBeNull()
        expect(onClose).not.toHaveBeenCalled()
    })

    it('obeys an explicit dirty flag over the controls', () => {
        open({ dirty: false })
        type('changed')
        close()
        expect(onClose).toHaveBeenCalledOnce()
        onClose.mockClear()
        open({ dirty: true })
        close()
        expect(onClose).not.toHaveBeenCalled()
        expect(asked()).not.toBeNull()
    })

    it('has the browser warn on reload only while there is something to lose', () => {
        const unload = () => { const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented }
        open()
        expect(unload()).toBe(false)
        type('changed')
        expect(unload()).toBe(true)
    })

    it('blocks in-app navigation while dirty', async () => {
        const router = createMemoryRouter([
            { path: '/', element: createElement(FormModal, { isOpen: true, title: 'Title', onClose }, createElement(Form)) },
            { path: '/other', element: null },
        ])
        await act(async () => root.render(createElement(RouterProvider, { router })))
        type('changed')
        await act(async () => { void router.navigate('/other') })
        expect(router.state.location.pathname).toBe('/')
        expect(asked()).not.toBeNull()
        choose('common.unsavedChanges.discard')
        await act(async () => undefined)
        expect(router.state.location.pathname).toBe('/other')
    })
})
