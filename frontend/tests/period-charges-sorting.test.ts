import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PeriodCharges } from '../src/features/charges/PeriodCharges'
import { queryKeys } from '../src/lib/api/queryKeys'
import type { Charge, Participant } from '../src/types/api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => options ? `${key}:${JSON.stringify(options)}` : key, i18n: { language: 'de-CH' } }) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: 1 } }) }))
vi.mock('../src/lib/communityAccess', () => ({ useCommunityAccess: () => ({ canWriteSelectedCommunity: false }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/appSettings', () => ({ useAppSettings: () => ({ settings: {} }), formatShortDate: (day: string) => day }))
vi.mock('../src/features/charges/ChargeFormModal', () => ({ ChargeFormModal: () => null }))
vi.mock('../src/lib/api/charges', () => ({ fetchCharges: () => new Promise(() => {}) }))
vi.mock('../src/lib/api/zev', () => ({ fetchParticipants: () => new Promise(() => {}) }))

const charge = (id: string, participants: string[], allocation: Charge['allocation'] = 'selected_participants'): Charge => ({
    id, participants, allocation, description: id, zev: 'z1', amount_chf: '10.00', charge_date: '2026-10-01',
    split_key: 'equal', vat_treatment: 'taxable', is_locked: false, created_at: '', updated_at: '',
})
const participant = (id: string, name: string, extra: Partial<Participant> = {}): Participant => ({
    id, zev: 'z1', display_name: name, full_name: name, party: name, valid_from: '2026-01-01', valid_to: null,
    metering_points: [], ...extra,
}) as Participant

let cleanup: (() => void) | undefined
afterEach(() => { cleanup?.() })

async function render(charges: Charge[], participants?: Participant[]) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    client.setQueryData(queryKeys.charges.list('z1', '2026-10-01', '2026-10-31'), charges)
    if (participants) client.setQueryData(queryKeys.zev.participants('z1'), participants)
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    cleanup = () => { act(() => root.unmount()); container.remove(); client.clear() }
    await act(async () => root.render(createElement(QueryClientProvider, { client },
        createElement(PeriodCharges, { zevId: 'z1', periodStart: '2026-10-01', periodEnd: '2026-10-31', periodLocked: false }))))
    const sort = () => act(async () => Array.from(container.querySelectorAll<HTMLButtonElement>('th button'))
        .find(button => button.textContent === 'pages.charges.columns.bearers')!.click())
    const descriptions = () => Array.from(container.querySelectorAll('tbody tr')).map(row => row.children[1].textContent)
    const setParticipants = async (next: Participant[]) => {
        await act(async () => { client.setQueryData(queryKeys.zev.participants('z1'), next); await new Promise(resolve => setTimeout(resolve, 0)) })
    }
    return { sort, descriptions, setParticipants }
}

describe('period charge bearer sorting', () => {
    it('groups all participants first, then orders names with Swiss collation and an ID fallback', async () => {
        const view = await render([
            charge('zuercher', ['z']), charge('missing', ['Zzz']), charge('aeberli', ['a']), charge('all', [], 'all_participants'),
        ], [participant('z', 'Zürcher'), participant('a', 'Äberli')])
        await view.sort()
        expect(view.descriptions()).toEqual(['all', 'aeberli', 'zuercher', 'missing'])
    })

    it('refreshes sorting when names arrive and when a participant is renamed', async () => {
        const view = await render([charge('one', ['1']), charge('two', ['2'])])
        await view.sort()
        expect(view.descriptions()).toEqual(['one', 'two'])
        await view.setParticipants([participant('1', 'Zulu'), participant('2', 'Alice')])
        expect(view.descriptions()).toEqual(['two', 'one'])
        await view.setParticipants([participant('1', 'Aaron'), participant('2', 'Alice')])
        expect(view.descriptions()).toEqual(['one', 'two'])
    })

    it('compares name lists without joining them or depending on participant order', async () => {
        const view = await render([
            charge('one-name', ['am']), charge('two-names', ['m', 'a']), charge('reversed', ['a', 'm']),
        ], [participant('am', 'Anna Maria'), participant('a', 'Anna'), participant('m', 'Maria')])
        await view.sort()
        expect(view.descriptions()).toEqual(['two-names', 'reversed', 'one-name'])
    })

    it('keeps equal raw names tied instead of ordering by formatted validity labels', async () => {
        const view = await render([charge('later', ['late']), charge('earlier', ['early'])], [
            participant('late', 'Alice', { valid_from: '2026-02-01' }),
            participant('early', 'Alice', { valid_from: '2026-01-01' }),
        ])
        await view.sort()
        expect(view.descriptions()).toEqual(['later', 'earlier'])
    })
})
