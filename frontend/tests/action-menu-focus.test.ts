import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ActionMenu } from '../src/components/ActionMenu'
import { waitForCondition } from './helpers/waitForCondition'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faEllipsis, faTrash } from '@fortawesome/free-solid-svg-icons'

let root: ReturnType<typeof createRoot>
let container: HTMLDivElement

beforeEach(() => {
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
})

afterEach(() => {
    act(() => root.unmount())
    container.remove()
    document.body.innerHTML = ''
})

it('moves focus to the trigger before an item runs, so a dialog it opens returns there on close', async () => {
    let focusedWhenRun: Element | null = null
    await act(async () => root.render(createElement(MantineProvider, null,
        createElement(ActionMenu, {
            label: 'More',
            items: [{ key: 'edit', label: 'Edit', onClick: () => { focusedWhenRun = document.activeElement } }],
        }))))
    const trigger = container.querySelector<HTMLButtonElement>('button[aria-haspopup="menu"]')!
    await act(async () => trigger.click())
    await waitForCondition(() => document.querySelector('[role="menuitem"]') !== null, 'menu items')
    const item = document.querySelector<HTMLButtonElement>('[role="menuitem"]')!
    await act(async () => item.focus())
    await act(async () => item.click())
    expect(focusedWhenRun).toBe(trigger)
})

it('names an icon-only menu and shows its tooltip on focus while keeping the menu usable', async () => {
    await act(async () => root.render(createElement(MantineProvider, null,
        createElement(ActionMenu, {
            label: 'More actions for Anna', iconOnly: true,
            icon: createElement(FontAwesomeIcon, { icon: faEllipsis }),
            items: [
                { key: 'edit', label: 'Edit', onClick: () => {} },
                { key: 'delete', label: 'Delete', disabled: true, onClick: () => {} },
            ],
        }))))
    const trigger = container.querySelector<HTMLButtonElement>('button[aria-haspopup="menu"]')!
    expect(trigger.textContent).toBe('')
    expect(trigger.getAttribute('aria-label')).toBe('More actions for Anna')
    expect(trigger.classList.contains('button-icon')).toBe(true)
    act(() => trigger.focus())
    await waitForCondition(() => document.querySelector('[role="tooltip"]')?.textContent === 'More actions for Anna', 'menu tooltip on focus')
    await act(async () => trigger.click())
    await waitForCondition(() => document.querySelector('[role="menuitem"]')?.textContent === 'Edit', 'menu item')
})

it('names a standalone icon and retains the action’s disabled state and focus target', async () => {
    let focusedWhenRun: Element | null = null
    const onClick = vi.fn(() => { focusedWhenRun = document.activeElement })
    const render = (disabled: boolean) => act(() => root.render(createElement(MantineProvider, null,
        createElement(ActionMenu, {
            label: 'More', iconOnly: true, compact: false, actionKey: 'delete-record',
            items: [{
                key: 'delete', label: 'Delete record', iconButtonLabel: 'Delete record: Sample',
                icon: createElement(FontAwesomeIcon, { icon: faTrash }), danger: true, disabled, onClick,
            }],
        }))))

    render(true)
    const button = container.querySelector('button')!
    expect(button.textContent).toBe('')
    expect(button.getAttribute('aria-label')).toBe('Delete record: Sample')
    expect(button.getAttribute('data-action-key')).toBe('delete-record')
    expect(button.hasAttribute('aria-haspopup')).toBe(false)
    expect(button.classList.contains('button-destructive')).toBe(true)
    expect(button.classList.contains('button-icon')).toBe(true)
    expect(button.disabled).toBe(true)
    act(() => button.click())
    expect(onClick).not.toHaveBeenCalled()

    render(false)
    act(() => button.focus())
    await waitForCondition(() => document.querySelector('[role="tooltip"]')?.textContent === 'Delete record: Sample', 'delete tooltip on focus')
    act(() => button.click())
    expect(onClick).toHaveBeenCalledOnce()
    expect(focusedWhenRun).toBe(button)

    render(true)
    await waitForCondition(() => document.querySelector('[role="tooltip"]') === null, 'tooltip closes while disabled')
    expect(container.querySelector('button')).toBe(button)
})
