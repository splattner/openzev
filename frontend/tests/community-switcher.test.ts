import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PageHeader } from '../src/components/PageHeader'
import { setZevUnsavedDraftGuard } from '../src/lib/zevUnsavedGuard'
import { waitForCondition } from './helpers/waitForCondition'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))

type Entry = { id: string; name: string; relation: string }

const state = vi.hoisted(() => ({
    context: undefined as undefined | {
        entries: Entry[]
        selectedZevId: string
        isSelectable: boolean
        setSelectedZevId: ReturnType<typeof vi.fn>
    },
}))

vi.mock('../src/lib/managedZev', () => ({
    useOptionalManagedZev: () => state.context,
}))

const NORTH = { id: '1', name: 'ZEV Nord', relation: 'admin' }
const SOUTH = { id: '2', name: 'ZEV Süd', relation: 'admin' }

function session(entries: Entry[], isSelectable = true) {
    state.context = { entries, selectedZevId: entries[0]?.id ?? '', isSelectable, setSelectedZevId: vi.fn() }
}

let root: ReturnType<typeof createRoot>
let container: HTMLDivElement

async function render(props: Partial<Parameters<typeof PageHeader>[0]> = {}) {
    await act(async () => root.render(createElement(MantineProvider, null,
        createElement(PageHeader, { eyebrow: 'ZEV Nord', communitySwitch: true, title: 'Tariffs', ...props }))))
}

const trigger = () => container.querySelector<HTMLButtonElement>('.community-switch')

async function open() {
    await act(async () => trigger()!.click())
    await waitForCondition(() => document.querySelectorAll('[role="menuitem"]').length > 0, 'community list')
    return Array.from(document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'))
}

async function choose(name: string) {
    const items = await open()
    await act(async () => items.find((item) => item.textContent?.includes(name))!.click())
}

beforeEach(() => {
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
    session([NORTH, SOUTH])
})

afterEach(() => {
    act(() => root.unmount())
    container.remove()
    document.body.innerHTML = ''
    setZevUnsavedDraftGuard(false)
})

describe('the scope line chooses the community', () => {
    it('names the current community and lists every one, marking the current', async () => {
        await render()
        expect(trigger()?.getAttribute('aria-label')).toBe('nav.chooseZevCurrent')
        expect(trigger()?.textContent).toBe('ZEV Nord')
        const items = await open()
        expect(items.map((item) => item.textContent)).toEqual(['ZEV Nord', 'ZEV Süd'])
        expect(items[0].getAttribute('aria-current')).toBe('true')
        expect(items[1].getAttribute('aria-current')).toBeNull()
    })

    it('switches to another community and ignores the current one', async () => {
        await render()
        await choose('ZEV Nord')
        expect(state.context!.setSelectedZevId).not.toHaveBeenCalled()
        await choose('ZEV Süd')
        expect(state.context!.setSelectedZevId).toHaveBeenCalledExactlyOnceWith('2')
    })

    it('names how a non-admin account relates to each community', async () => {
        session([{ ...NORTH, relation: 'manager' }, { ...SOUTH, relation: 'participant' }])
        await render()
        const items = await open()
        expect(items.map((item) => item.querySelector('.community-menu-relation')?.textContent))
            .toEqual(['nav.relation.manager', 'nav.relation.participant'])
    })

    it.each([[[NORTH]], [[]]])('stays plain text with %j — there is nothing to choose', async (entries) => {
        session(entries)
        await render()
        expect(trigger()).toBeNull()
        expect(container.querySelector('.eyebrow')?.textContent).toBe('ZEV Nord')
    })

    it('stays plain text outside a community provider and on pages that do not ask for it', async () => {
        state.context = undefined
        await render()
        expect(trigger()).toBeNull()
        session([NORTH, SOUTH])
        await render({ communitySwitch: false, eyebrow: 'nav.platformScope' })
        expect(trigger()).toBeNull()
        expect(container.querySelector('.eyebrow')?.textContent).toBe('nav.platformScope')
    })

    it('keeps the page and browser title intact', async () => {
        await render()
        const heading = container.querySelector('h1')!
        const eyebrow = container.querySelector('.eyebrow')!
        expect(heading.getAttribute('aria-describedby')).toBe(eyebrow.id)
        // The browser title still names the community (the scoped form).
        expect(document.title).toBe('app.documentTitleScoped')
    })
})

describe('switching with unsaved settings', () => {
    it('asks before dropping a dirty settings draft, and switches only on confirm', async () => {
        setZevUnsavedDraftGuard(true)
        await render()
        await choose('ZEV Süd')
        expect(state.context!.setSelectedZevId).not.toHaveBeenCalled()
        const dialog = document.querySelector('[role="dialog"]')!
        expect(dialog.textContent).toContain('pages.zevSettings.unsavedGuardSwitchMessage')
        // The dialog cannot nest in the scope line's paragraph.
        expect(dialog.closest('p')).toBeNull()
        const cancel = Array.from(dialog.querySelectorAll('button')).find((button) => button.textContent === 'common.cancel')!
        await act(async () => cancel.click())
        expect(document.querySelector('[role="dialog"]')).toBeNull()
        expect(state.context!.setSelectedZevId).not.toHaveBeenCalled()

        await choose('ZEV Süd')
        const confirm = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button'))
            .find((button) => button.textContent === 'pages.zevSettings.switchWithoutSaving')!
        await act(async () => confirm.click())
        expect(state.context!.setSelectedZevId).toHaveBeenCalledExactlyOnceWith('2')
        expect(document.querySelector('[role="dialog"]')).toBeNull()
    })

    it('does not ask for the current community', async () => {
        setZevUnsavedDraftGuard(true)
        await render()
        await choose('ZEV Nord')
        expect(document.querySelector('[role="dialog"]')).toBeNull()
    })
})

it('lists but does not switch when the selection is fixed', async () => {
    session([NORTH, SOUTH], false)
    await render()
    const items = await open()
    expect(items[0].disabled || items[0].hasAttribute('data-disabled')).toBe(false)
    expect(items[1].disabled || items[1].hasAttribute('data-disabled')).toBe(true)
})
