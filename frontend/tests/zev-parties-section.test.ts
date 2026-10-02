import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import type { Party, ZevPartyRole } from '../src/types/api'

// ZEV settings → Parties (#761, SPEC-2026-10-zev-parties §8.3).

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, values?: Record<string, string>) => (values?.name ? `${key}:${values.name}` : key) }),
}))
const pushToast = vi.fn()
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast }) }))
vi.mock('../src/lib/dates', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../src/lib/dates')>()),
    todayBusinessIso: () => '2026-06-15',
}))
vi.mock('../src/lib/appSettings', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../src/lib/appSettings')>()),
    useAppSettings: () => ({ settings: { date_format_short: 'dd.MM.yyyy' } }),
}))
vi.mock('../src/lib/api/zev', () => ({
    fetchParties: vi.fn(),
    fetchPartyRoles: vi.fn(),
    createParty: vi.fn(),
    updateParty: vi.fn(),
    deleteParty: vi.fn(),
    assignPartyRole: vi.fn(),
    endPartyRole: vi.fn(),
}))

import { assignPartyRole, endPartyRole, fetchParties, fetchPartyRoles } from '../src/lib/api/zev'
import { ZevPartiesSection } from '../src/features/zev/ZevPartiesSection'

const party = (id: string, name: string, over: Partial<Party> = {}): Party => ({
    id, zev: 'z1', kind: 'person', title: '', first_name: '', last_name: name, organisation_name: '', name_addition: '',
    email: '', phone: '', address_line1: '', address_line2: '', postal_code: '', city: '', notes: '',
    display_name: name, participations: [{ id: `p-${id}`, valid_from: '2026-01-01', valid_to: null }], roles: [],
    created_at: '', updated_at: '', ...over,
})
const role = (id: string, partyId: string, name: string, kind: ZevPartyRole['role'], validFrom: string, validTo: string | null = null): ZevPartyRole => ({
    id, zev: 'z1', party: partyId, party_display_name: name, role: kind, valid_from: validFrom, valid_to: validTo,
    created_at: '', updated_at: '',
})

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))
beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchParties).mockResolvedValue([
        party('a', 'Alt'),
        party('n', 'Neu'),
        party('v', 'Verwaltung Nord', { kind: 'organisation', organisation_name: 'Verwaltung Nord', participations: [] }),
    ])
    vi.mocked(fetchPartyRoles).mockResolvedValue([
        role('r1', 'a', 'Alt', 'issuer', '2025-01-01', '2026-03-31'),
        role('r2', 'n', 'Neu', 'issuer', '2026-04-01'),
        role('r3', 'a', 'Alt', 'landowner', '2025-01-01'),
    ])
    vi.mocked(assignPartyRole).mockResolvedValue(role('r9', 'a', 'Alt', 'representative', '2026-06-15'))
    vi.mocked(endPartyRole).mockResolvedValue(role('r3', 'a', 'Alt', 'landowner', '2025-01-01', '2026-06-15'))
})

async function render(canManage: boolean) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    await act(async () => root.render(
        createElement(MantineProvider, null,
            createElement(QueryClientProvider, { client }, createElement(ZevPartiesSection, { zevId: 'z1', canManage }))),
    ))
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
    return container
}

const buttons = (container: Element, label: string) =>
    Array.from(container.querySelectorAll('button')).filter((button) => button.textContent?.includes(label))

async function click(element: Element) {
    await act(async () => { (element as HTMLElement).click() })
}

describe('ZevPartiesSection', () => {
    it('shows today\'s issuer, the missing representative, landowners and other contacts', async () => {
        const container = await render(true)
        const text = container.textContent ?? ''
        expect(text).toContain('Neu')
        expect(text).toContain('pages.zevSettings.parties.representativeNone')
        expect(text).toContain('Verwaltung Nord')
        // The earlier issuer is history, behind "Show history".
        expect(container.querySelectorAll('.zev-parties-history')).toHaveLength(0)
    })

    it('gives a viewer no actions', async () => {
        const container = await render(false)
        expect(container.textContent).toContain('Neu')
        expect(buttons(container, 'pages.zevSettings.parties.changeFrom')).toHaveLength(0)
        expect(buttons(container, 'pages.zevSettings.parties.addContact')).toHaveLength(0)
        expect(buttons(container, 'pages.zevSettings.parties.end')).toHaveLength(0)
    })

    it('sets a representative from a date', async () => {
        const container = await render(true)
        await click(buttons(container, 'pages.zevSettings.parties.set')[0])
        const select = container.querySelector<HTMLSelectElement>('.zev-access-form select')!
        await act(async () => {
            select.value = 'v'
            select.dispatchEvent(new Event('change', { bubbles: true }))
        })
        await click(buttons(container, 'pages.zevSettings.parties.apply')[0])
        expect(assignPartyRole).toHaveBeenCalledWith({ zev: 'z1', party: 'v', role: 'representative', valid_from: '2026-06-15' })
    })

    it('ends a landowner on a chosen day', async () => {
        const container = await render(true)
        await click(buttons(container, 'pages.zevSettings.parties.end')[0])
        const form = container.querySelector('.zev-parties-inline-date')!.closest('form')!
        await act(async () => { form.requestSubmit() })
        expect(endPartyRole).toHaveBeenCalledWith('r3', '2026-06-15')
    })
})
