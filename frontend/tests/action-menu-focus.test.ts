import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { ActionMenu } from '../src/components/ActionMenu'
import { waitForCondition } from './helpers/waitForCondition'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faEllipsis } from '@fortawesome/free-solid-svg-icons'

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
            items: [{ key: 'edit', label: 'Edit', onClick: () => {} }],
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
