import { act, createElement, useLayoutEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { waitForCondition } from './helpers/waitForCondition'
import type { Participant, ParticipantInput } from '../src/types/api'
import type { ParticipantFormModal } from '../src/features/participants/ParticipantFormModal'
import type { ParticipantCardsSection } from '../src/features/participants/ParticipantCardsSection'
import type { ParticipantToolbar } from '../src/features/participants/ParticipantToolbar'
import type { ComponentProps } from 'react'

const state = vi.hoisted(() => ({
    zevId: 'A', userId: 1, relation: 'manager', write: vi.fn(), onboardingWrite: vi.fn(), toast: vi.fn(),
    form: null as ComponentProps<typeof ParticipantFormModal> | null,
    cards: null as ComponentProps<typeof ParticipantCardsSection> | null,
    toolbar: null as ComponentProps<typeof ParticipantToolbar> | null,
}))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: state.userId, role: 'user' } }) }))
vi.mock('../src/lib/managedZev', () => {
    const useManagedZev = () => ({ selectedZevId: state.zevId, selectedZev: { id: state.zevId, name: state.zevId }, relation: state.relation, isLoading: false })
    return { useManagedZev, useOptionalManagedZev: useManagedZev }
})
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: state.toast }) }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/appSettings', () => ({ useAppSettings: () => ({ settings: {} }) }))
vi.mock('../src/lib/api/zev', async importOriginal => ({
    ...await importOriginal(), createParticipant: state.write, updateParticipant: state.write,
    sendOnboardingLink: state.onboardingWrite, getOnboardingLink: state.onboardingWrite, revokeOnboardingLink: state.onboardingWrite,
    fetchParticipants: async () => participants, fetchParticipantGeocodingEnabled: async () => false,
}))
vi.mock('../src/features/participants/useParticipantAccountLinking', () => ({ useParticipantAccountLinking: () => ({}) }))
vi.mock('../src/features/participants/ParticipantFormModal', () => ({
    ParticipantFormModal: (props: ComponentProps<typeof ParticipantFormModal>) => {
        useLayoutEffect(() => { state.form = props }, [props])
        return props.isOpen ? createElement('input', { 'data-draft': props.selectedZevId, defaultValue: props.initialParticipant?.id ?? 'new' }) : null
    },
}))
vi.mock('../src/features/participants/ParticipantToolbar', () => ({
    ParticipantToolbar: (props: ComponentProps<typeof ParticipantToolbar>) => {
        useLayoutEffect(() => { state.toolbar = props }, [props])
        return null
    },
}))
vi.mock('../src/features/participants/ParticipantCardsSection', () => ({
    ParticipantCardsSection: (props: ComponentProps<typeof ParticipantCardsSection>) => {
        useLayoutEffect(() => { state.cards = props }, [props])
        return null
    },
}))
import { ParticipantsPage } from '../src/pages/ParticipantsPage'
import { queryKeys } from '../src/lib/api/queryKeys'

const participants = ['A', 'B'].map(zev => ({ id: `p${zev}`, zev, first_name: 'Name', last_name: zev, valid_from: '2026-01-01' } as Participant))
let root: ReturnType<typeof createRoot>
let client: QueryClient
let container: HTMLDivElement
async function render(path = '/participants') {
    await act(async () => root.render(createElement(MemoryRouter, { initialEntries: [path] },
        createElement(QueryClientProvider, { client }, createElement(ParticipantsPage)),
    )))
}
beforeEach(async () => {
    vi.clearAllMocks()
    state.zevId = 'A'
    state.userId = 1
    state.relation = 'manager'
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } })
    for (const zev of ['A', 'B']) client.setQueryData(queryKeys.zev.participants(zev), participants)
    await render()
})
afterEach(() => { act(() => root.unmount()); client.clear(); container.remove() })

it.each([
    ['create', 'success'], ['update', 'success'], ['create', 'error'], ['update', 'error'],
])('keeps B’s replacement draft after A’s delayed %s %s', async (mode, outcome) => {
    let resolve!: (value: Participant) => void
    let reject!: (error: Error) => void
    state.write.mockReturnValue(new Promise<Participant>((done, fail) => { resolve = done; reject = fail }))
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    act(() => {
        if (mode === 'create') state.toolbar!.onOpenCreateModal()
        else state.cards!.onStartEdit(participants[0])
    })
    act(() => state.form!.onSubmit({ first_name: 'Saved A' } as ParticipantInput))
    await waitForCondition(() => state.write.mock.calls.length > 0, 'participant write submitted')
    state.zevId = 'B'
    await render()
    act(() => {
        if (mode === 'create') state.toolbar!.onOpenCreateModal()
        else state.cards!.onStartEdit(participants[1])
    })
    const draft = container.querySelector('input')!
    draft.value = 'B’s unsaved work'
    await act(async () => {
        if (outcome === 'success') resolve(participants[0])
        else reject(new Error('Old failure'))
    })
    await waitForCondition(() => client.getMutationCache().getAll()[0].state.status === (outcome === 'success' ? 'success' : 'error'), 'participant write completion')
    expect(container.querySelector('input')).toBe(draft)
    expect(draft.value).toBe('B’s unsaved work')
    expect(state.form!.initialParticipant?.id).toBe(mode === 'update' ? 'pB' : undefined)
    expect(state.toast).not.toHaveBeenCalled()
    if (outcome === 'success') expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.zev.participants('A') })
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: queryKeys.zev.participants('B') })
})

it('closes a successful participant save in the submitting scope', async () => {
    state.write.mockResolvedValue(participants[0])
    act(() => state.toolbar!.onOpenCreateModal())
    act(() => state.form!.onSubmit({ first_name: 'Saved A' } as ParticipantInput))
    await waitForCondition(() => !container.querySelector('input'), 'submitted dialog closes')
    expect(state.toast).toHaveBeenCalledWith('pages.participants.messages.created', 'success')
})

it('classifies membership inclusively using the Swiss civil date for card shares', async () => {
    // It is already 7 October in Zurich, while the UTC date is still 6 October.
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-06T22:30:00Z'))
    try {
        const membershipDates = [
            { id: 'starts-today', valid_from: '2026-10-07', valid_to: null },
            { id: 'ends-today', valid_from: '2026-01-01', valid_to: '2026-10-07' },
            { id: 'ended-yesterday', valid_from: '2026-01-01', valid_to: '2026-10-06' },
            { id: 'starts-tomorrow', valid_from: '2026-10-08', valid_to: null },
        ].map(dates => ({ ...participants[0], ...dates }))
        client.setQueryData(queryKeys.zev.participants('A'), membershipDates)
        await render()
        expect(Object.fromEntries(state.cards!.participantCards.map(({ participant, validityState }) => [
            participant.id, validityState,
        ]))).toEqual({
            'starts-today': 'current', 'ends-today': 'current',
            'ended-yesterday': 'ended', 'starts-tomorrow': 'upcoming',
        })
    } finally {
        vi.useRealTimers()
    }
})

it('counts and lists the same participants under No metering point', async () => {
    client.setQueryData(queryKeys.zev.participants('A'), [
        { ...participants[0], id: 'metered', has_metering_point_assignment: true },
        { ...participants[0], id: 'unmetered', has_metering_point_assignment: false },
    ])
    await render()
    expect(state.toolbar!.noMeteringCount).toBe(1)
    act(() => state.toolbar!.onReadinessFilterChange('noMetering'))
    expect(state.cards!.filteredParticipants.map(({ participant }) => participant.id)).toEqual(['unmetered'])
})

it('hides ended participants until the Ended tab is chosen', async () => {
    client.setQueryData(queryKeys.zev.participants('A'), [
        { ...participants[0], id: 'current', has_metering_point_assignment: false },
        { ...participants[0], id: 'ended', valid_to: '2026-03-31', has_metering_point_assignment: false },
    ])
    await render()
    expect(state.cards!.filteredParticipants.map(({ participant }) => participant.id)).toEqual(['current'])
    expect(state.toolbar!).toMatchObject({ activeCount: 1, endedCount: 1, noMeteringCount: 1 })
    act(() => state.toolbar!.onReadinessFilterChange('ended'))
    expect(state.cards!.filteredParticipants.map(({ participant }) => participant.id)).toEqual(['ended'])
})

it('offers the Ended tab when every participation has ended', async () => {
    client.setQueryData(queryKeys.zev.participants('A'), [
        { ...participants[0], id: 'ended', valid_to: '2026-03-31' },
    ])
    await render()
    expect(state.cards!.filteredParticipants).toEqual([])
    act(() => state.cards!.onShowEnded!())
    expect(state.cards!.filteredParticipants.map(({ participant }) => participant.id)).toEqual(['ended'])
    expect(state.cards!.onShowEnded).toBeUndefined()
})

it('opens a deep link to an ended participation on the Ended tab', async () => {
    client.setQueryData(queryKeys.zev.participants('A'), [
        { ...participants[0], id: 'current' },
        { ...participants[0], id: 'ended', valid_to: '2026-03-31' },
    ])
    // A mounted router keeps its location, so start a fresh one on the link.
    act(() => root.unmount())
    root = createRoot(container)
    await render('/participants?focus=ended')
    await waitForCondition(() => state.cards?.focusParticipantId === 'ended', 'deep link consumed')
    expect(state.cards!.filteredParticipants.map(({ participant }) => participant.id)).toEqual(['ended'])
})

const onboarding = [
    { name: 'send', run: () => state.cards!.onSendOnboardingLink('pA') },
    { name: 'copy', run: () => state.cards!.onCopyOnboardingLink('pA') },
    { name: 'revoke', run: () => state.cards!.onRevokeOnboardingLink('pA') },
]
const link = { onboarding_url: 'https://example.test/onboard/A', onboarding_expires_at: null }
for (const change of ['community', 'permission', 'account'] as const) {
    for (const outcome of ['success', 'error'] as const) {
        it.each(onboarding)(`ignores an old $name onboarding ${outcome} after changing ${change}`, async ({ run }) => {
            let resolve!: (value: typeof link) => void
            let reject!: (error: Error) => void
            state.onboardingWrite.mockReturnValue(new Promise((done, fail) => { resolve = done; reject = fail }))
            const invalidate = vi.spyOn(client, 'invalidateQueries')
            act(() => run())
            await waitForCondition(() => state.onboardingWrite.mock.calls.length > 0, 'onboarding request sent')
            if (change === 'community') state.zevId = 'B'
            if (change === 'permission') state.relation = 'viewer'
            if (change === 'account') state.userId = 2
            await render()
            await act(async () => {
                if (outcome === 'success') resolve(link)
                else reject(new Error('Old failure'))
            })
            await waitForCondition(() => client.getMutationCache().getAll()[0].state.status === outcome, 'onboarding request completion')
            expect(container.textContent).not.toContain(link.onboarding_url)
            expect(state.toast).not.toHaveBeenCalled()
            if (outcome === 'success') expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.zev.participants('A') })
            expect(invalidate).not.toHaveBeenCalledWith({ queryKey: queryKeys.zev.participants('B') })
        })
    }
    it(`clears an existing onboarding URL after changing ${change}`, async () => {
        state.onboardingWrite.mockResolvedValue(link)
        act(() => state.cards!.onCopyOnboardingLink('pA'))
        await waitForCondition(() => !!container.textContent?.includes(link.onboarding_url), 'onboarding notice visible')
        if (change === 'community') state.zevId = 'B'
        if (change === 'permission') state.relation = 'viewer'
        if (change === 'account') state.userId = 2
        await render()
        expect(container.textContent).not.toContain(link.onboarding_url)
    })
    it(`rejects a retained participant submit after changing ${change}`, async () => {
        act(() => state.toolbar!.onOpenCreateModal())
        const previousSubmit = state.form!.onSubmit
        if (change === 'community') state.zevId = 'B'
        if (change === 'permission') state.relation = 'viewer'
        if (change === 'account') state.userId = 2
        await render()
        await act(async () => previousSubmit({ first_name: 'Old draft' } as ParticipantInput))
        expect(state.write).not.toHaveBeenCalled()
        expect(state.toast).not.toHaveBeenCalled()
    })
}

it('shows an onboarding result in its submitting scope', async () => {
    state.onboardingWrite.mockResolvedValue(link)
    act(() => state.cards!.onSendOnboardingLink('pA'))
    await waitForCondition(() => !!container.textContent?.includes(link.onboarding_url), 'onboarding notice visible')
    expect(state.toast).toHaveBeenCalledWith('pages.participants.messages.onboardingLinkSent', 'success')
})

it('rejects a participant write queued before its scope changes', async () => {
    act(() => state.toolbar!.onOpenCreateModal())
    act(() => {
        state.form!.onSubmit({ first_name: 'Queued A' } as ParticipantInput)
        state.zevId = 'B'
        root.render(createElement(MemoryRouter, null,
            createElement(QueryClientProvider, { client }, createElement(ParticipantsPage))))
    })
    await act(async () => undefined)
    expect(state.write).not.toHaveBeenCalled()
    expect(state.toast).not.toHaveBeenCalled()
})
