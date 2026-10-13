import { queryKeys } from '../src/lib/api/queryKeys'
import { waitForCondition } from './helpers/waitForCondition'
import { act, createElement, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, useNavigate } from 'react-router-dom'
import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useMeteringPointActions } from '../src/features/meteringPoints/useMeteringPointActions'

const state = vi.hoisted(() => ({
    zevId: '42', relation: 'manager', userId: 1, disabled: false, role: 'user', scopeFailed: false,
    quality: vi.fn(), assignments: vi.fn(), navigate: null as ReturnType<typeof useNavigate> | null,
    toast: vi.fn(), write: vi.fn(), actions: null as ReturnType<typeof useMeteringPointActions> | null,
}))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: state.userId, role: state.role } }) }))
vi.mock('../src/lib/managedZev', () => {
    const context = { useManagedZev: () => ({
        selectedZevId: state.zevId, selectedZev: { id: state.zevId, name: state.zevId, disabled_at: state.disabled ? '2026-10-03T12:00:00Z' : null }, relation: state.relation, isError: state.scopeFailed, refetch: vi.fn(),
    }) }
    return { ...context, useOptionalManagedZev: context.useManagedZev }
})
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: state.toast }) }))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }), formatShortDate: (value: string) => value,
    formatDateTime: (value: string) => value, toDayJsDateFormat: () => 'DD.MM.YYYY',
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }))
vi.mock('../src/lib/api/zev', async importOriginal => ({
    ...await importOriginal(),
    createMeteringPoint: state.write, updateMeteringPoint: state.write, deleteMeteringPoint: state.write,
    createMeteringPointAssignment: state.write, updateMeteringPointAssignment: state.write,
    deleteMeteringPointAssignment: state.write, deleteMeteringPointReadings: state.write,
    fetchParticipants: async () => [], fetchMeteringPointAssignments: state.assignments,
    fetchMeteringPoints: async () => ['42', '43'].map(zev => ({
        id: `mp${zev}`, zev, meter_id: `MP-${zev}`, meter_type: 'consumption',
        is_active: true, reading_count: 0, has_behind_meter_generation: false,
    })),
}))
vi.mock('../src/lib/api/metering', () => ({ fetchMeteringDataQualityStatus: state.quality }))

vi.mock('../src/features/meteringPoints/useMeteringPointActions', async importOriginal => {
    const original = await importOriginal<typeof import('../src/features/meteringPoints/useMeteringPointActions')>()
    return {
        ...original,
        useMeteringPointActions: (...args: Parameters<typeof original.useMeteringPointActions>) => {
            state.actions = original.useMeteringPointActions(...args)
            return state.actions
        },
    }
})

import { MeteringPointsPage } from '../src/pages/MeteringPointsPage'

let root: ReturnType<typeof createRoot>
let client: QueryClient
let container: HTMLDivElement

function NavigationProbe() {
    const navigate = useNavigate()
    useEffect(() => { state.navigate = navigate }, [navigate])
    return null
}

async function render() {
    await act(async () => root.render(createElement(MemoryRouter, null,
        createElement(NavigationProbe),
        createElement(QueryClientProvider, { client },
            createElement(MantineProvider, null, createElement(MeteringPointsPage))),
    )))
    await waitForCondition(() => !!container.querySelector('.metering-point-card'), 'meter rows')
}

async function openDraft(mode: 'create' | 'edit' | 'assignment' | 'delete') {
    act(() => {
        const button = mode === 'create'
            ? container.querySelector<HTMLButtonElement>('.metering-toolbar .toolbar-actions button')!
            : mode === 'assignment'
                ? container.querySelector<HTMLButtonElement>('.metering-point-holder .button-primary')!
                : container.querySelector<HTMLButtonElement>('.metering-point-actions [aria-haspopup="menu"]')!
        button.click()
    })
    if (mode === 'edit' || mode === 'delete') {
        await waitForCondition(() => !!document.querySelector('[role="menuitem"]'), 'meter actions')
        act(() => Array.from(document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'))
            .find(button => button.textContent?.includes(mode === 'edit' ? 'common.edit' : 'common.delete'))!.click())
    }
    expect(document.querySelector('[role="dialog"]')).not.toBeNull()
}

beforeEach(async () => {
    state.zevId = '42'
    state.relation = 'manager'
    state.userId = 1
    state.disabled = false
    state.role = 'user'
    state.scopeFailed = false
    vi.clearAllMocks()
    state.assignments.mockResolvedValue([])
    state.quality.mockResolvedValue({ metering_points: [] })
    state.write.mockResolvedValue({ deleted_count: 1 })
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    await render()
})

afterEach(() => {
    act(() => root.unmount())
    client.clear()
    onlineManager.setOnline(true)
    container.remove()
})

describe('metering draft context', () => {
    it('connects the counted attention tab to the scoped list and URL state', () => {
        const attention = Array.from(container.querySelectorAll<HTMLButtonElement>('.filter-tab')).find(button => button.textContent?.includes('pages.meteringPoints.summary.attention'))!
        expect(attention.textContent).toContain('1')
        act(() => attention.click())
        expect(state.actions!.view).toBe('attention')
        expect(state.actions!.meteringPoints.map(point => point.id)).toEqual(['mp42'])
        act(() => attention.click())
        expect(state.actions!.view).toBe('all')
    })

    for (const mode of ['create', 'edit'] as const) {
        for (const change of ['community', 'write access', 'account']) {
            it(`closes a ${mode} draft when ${change} changes`, async () => {
                await openDraft(mode)
                if (change === 'community') state.zevId = '43'
                else if (change === 'account') {
                    state.userId = 2
                    client.clear() // AuthProvider resets both query and mutation caches at session boundaries.
                } else state.relation = 'viewer'
                await render()
                expect(document.querySelector('[role="dialog"]')).toBeNull()
                expect(container.textContent).toContain(`MP-${state.zevId}`)
                if (change === 'write access') {
                    expect(container.querySelector('.metering-toolbar .toolbar-actions')).toBeNull()
                }
            })
        }
    }
})

const writes = [
    { name: 'meter create', run: (actions: ReturnType<typeof useMeteringPointActions>) => actions.saveMpMutation.mutateAsync({
        scope: actions.scope,
        payload: { zev: '42', meter_id: 'draft', meter_type: 'consumption', is_active: true, has_behind_meter_generation: false },
    }) },
    { name: 'meter edit', run: (actions: ReturnType<typeof useMeteringPointActions>) => actions.saveMpMutation.mutateAsync({
        scope: actions.scope,
        id: 'mp42', payload: { zev: '42', meter_id: 'edited', meter_type: 'consumption', is_active: true, has_behind_meter_generation: false },
    }) },
    { name: 'meter delete', run: (actions: ReturnType<typeof useMeteringPointActions>) => actions.deleteMpMutation.mutateAsync({ id: 'mp42', scope: actions.scope }) },
    { name: 'assignment save', run: (actions: ReturnType<typeof useMeteringPointActions>) => actions.saveAssignMutation.mutateAsync({
        scope: actions.scope,
        payload: { metering_point: 'mp42', participant: 'p42', valid_from: '2026-01-01', valid_to: null, allocation_mode: 'normal' },
    }) },
    { name: 'assignment delete', run: (actions: ReturnType<typeof useMeteringPointActions>) => actions.deleteAssignMutation.mutateAsync({ id: 'assignment42', scope: actions.scope }) },
    { name: 'reading delete', run: (actions: ReturnType<typeof useMeteringPointActions>) => actions.deleteMeteringDataMutation.mutateAsync({
        scope: actions.scope,
        meteringPointId: 'mp42', payload: { delete_all: true },
    }) },
]

describe('metering write ownership', () => {
    it.each(['create', 'edit', 'assignment', 'delete'] as const)('closes the %s dialog when the community is disabled', async mode => {
        await openDraft(mode)
        state.disabled = true
        await render()
        expect(document.querySelector('[role="dialog"]')).toBeNull()
        expect(container.querySelector('.toolbar-actions')).toBeNull()
        expect(container.querySelector('.metering-point-actions .button-primary')).toBeNull()
    })

    it.each(['create', 'edit', 'assignment', 'delete'] as const)('keeps the %s dialog mounted during a failed scope refresh', async mode => {
        await openDraft(mode)
        const dialog = document.querySelector('[role="dialog"]')
        state.scopeFailed = true
        await render()
        expect(document.querySelector('[role="dialog"]')).toBe(dialog)
        expect(container.querySelector('.warning-banner')).not.toBeNull()
    })

    it('closes reading deletion when the admin override is lost', async () => {
        state.role = 'admin'
        await render()
        act(() => container.querySelector<HTMLButtonElement>('.metering-point-actions [aria-haspopup="menu"]')!.click())
        await waitForCondition(() => !!document.querySelector('[role="menuitem"]'), 'admin meter actions')
        act(() => Array.from(document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'))
            .find(button => button.textContent?.includes('pages.meteringPoints.deleteData.button'))!.click())
        expect(document.querySelector('[role="dialog"]')).not.toBeNull()
        state.role = 'user'
        await render()
        expect(document.querySelector('[role="dialog"]')).toBeNull()
        expect(container.querySelector('.toolbar-actions')).not.toBeNull()
    })

    it('keeps the admin override for a disabled community', async () => {
        state.role = 'admin'
        state.disabled = true
        await render()
        await openDraft('create')
        expect(document.querySelector('[role="dialog"]')).not.toBeNull()
    })

    it.each(writes)('rejects a retained $name callback after losing write access', async ({ name, run }) => {
        if (name === 'reading delete') { state.role = 'admin'; await render() }
        const previous = state.actions!
        state.relation = 'viewer'
        state.role = 'user'
        await render()
        await act(async () => { await expect(run(previous)).rejects.toThrow() })
        expect(state.write).not.toHaveBeenCalled()
        expect(state.toast).not.toHaveBeenCalled()
    })

    for (const change of ['account', 'community'] as const) {
        for (const outcome of ['success', 'failure'] as const) {
            it.each(writes)(`ignores an obsolete $name ${outcome} after changing ${change}`, async ({ name, run }) => {
                state.role = 'admin'
                await render()
                let resolve!: (value: { deleted_count: number }) => void
                let reject!: (error: Error) => void
                const pending = new Promise<{ deleted_count: number }>((yes, no) => { resolve = yes; reject = no })
                state.write.mockReturnValue(pending)
                let operation!: Promise<unknown>
                act(() => { operation = run(state.actions!) })
                const settled = operation.catch(() => undefined)
                await waitForCondition(() => state.write.mock.calls.length === 1, 'original write')
                const submitted = state.write.mock.calls[0]
                if (change === 'account') {
                    state.userId = 2
                    client.clear() // AuthProvider resets both query and mutation caches at session boundaries.
                } else state.zevId = '43'
                await render()
                const invalidate = vi.spyOn(client, 'invalidateQueries')
                await openDraft('create')
                const replacement = document.querySelector('[role="dialog"]')
                await act(async () => {
                    if (outcome === 'success') resolve({ deleted_count: 1 })
                    else reject(new Error('Old write failed'))
                    await settled
                })
                expect(state.write.mock.calls).toEqual([submitted])
                expect(state.toast).not.toHaveBeenCalled()
                if (change === 'community' && outcome === 'success') {
                    // Building counts and the map's current participants follow
                    // metering points and assignments (#890); readings do not.
                    const keys = name.includes('assignment')
                        ? [queryKeys.metering.pointAssignments(), queryKeys.metering.points('42'), queryKeys.zev.participants('42'), queryKeys.zev.buildings('42')]
                        : name === 'meter delete'
                            ? [['metering'], queryKeys.zev.buildings('42')]
                            : name === 'reading delete'
                                ? [['metering']]
                                : [queryKeys.metering.points('42'), queryKeys.zev.buildings('42')]
                    expect(invalidate.mock.calls.map(([filters]) => filters?.queryKey)).toEqual(keys)
                } else {
                    expect(invalidate).not.toHaveBeenCalled()
                }
                expect(document.querySelector('[role="dialog"]')).toBe(replacement)
            })
        }
    }
})

it.each(writes)('refreshes the original caches after a successful $name while another page is open', async ({ run }) => {
    state.role = 'admin'
    await render()
    let resolve!: (value: { deleted_count: number }) => void
    state.write.mockReturnValue(new Promise(done => { resolve = done }))
    let operation!: Promise<unknown>
    act(() => { operation = run(state.actions!) })
    await waitForCondition(() => state.write.mock.calls.length === 1, 'original write')
    act(() => root.render(createElement(QueryClientProvider, { client }, createElement('p', null, 'Another page'))))
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    await act(async () => { resolve({ deleted_count: 1 }); await operation })
    expect(invalidate).toHaveBeenCalled()
    expect(container.textContent).toBe('Another page')
    expect(state.toast).not.toHaveBeenCalled()
})


// Keep one observer mounted so React Query replaces pending mutation options.
// The keyed page tests above cover remounts, which otherwise hide this race.
function UnkeyedHarness() {
    useMeteringPointActions({ selectedZevId: state.zevId, isManagedScope: true, canWrite: true, canDeleteData: true })
    return null
}
async function renderUnkeyed() {
    await act(async () => root.render(createElement(MemoryRouter, null,
        createElement(NavigationProbe),
        createElement(QueryClientProvider, { client }, createElement(UnkeyedHarness)),
    )))
}

it.each(writes)('rejects offline queued $name after a community switch on the same observer', async ({ run }) => {
    await renderUnkeyed()
    onlineManager.setOnline(false)
    let operation!: Promise<unknown>
    act(() => { operation = run(state.actions!) })
    const settled = operation.catch(error => error)
    await waitForCondition(() => client.getMutationCache().getAll().some(mutation => mutation.state.isPaused), 'offline write')
    state.zevId = '43'
    await renderUnkeyed()
    await act(async () => { onlineManager.setOnline(true); await client.resumePausedMutations(); await settled })
    expect(await settled).toBeInstanceOf(Error)
    expect(state.write).not.toHaveBeenCalled()
    expect(state.toast).not.toHaveBeenCalled()
})

it.each(writes)('suppresses delayed $name failure after a community switch on the same observer', async ({ run }) => {
    await renderUnkeyed()
    let reject!: (error: Error) => void
    state.write.mockReturnValue(new Promise((_, no) => { reject = no }))
    let operation!: Promise<unknown>
    act(() => { operation = run(state.actions!) })
    const settled = operation.catch(() => undefined)
    await waitForCondition(() => state.write.mock.calls.length === 1, 'original write')
    state.zevId = '43'
    await renderUnkeyed()
    await act(async () => { reject(new Error('A failed')); await settled })
    expect(state.toast).not.toHaveBeenCalled()
})

async function healthyPoint() {
    await waitForCondition(() => !!state.actions!.assignmentsQuery.data && !!state.actions!.dataQualityQuery.data, 'dependent queries')
    act(() => {
        client.setQueryData(queryKeys.metering.points('42'), [{ id: 'mp42', zev: '42', meter_id: 'MP-42', meter_type: 'consumption', is_active: true, reading_count: 10 }])
        client.setQueriesData({ queryKey: ['metering', 'quality-status'] }, { metering_points: [{ id: 'mp42', severity: 'green' }] })
        client.setQueryData(queryKeys.metering.pointAssignments(), [{ id: 'a42', metering_point: 'mp42', participant: 'p42', valid_from: '2020-01-01', valid_to: null }])
    })
    await waitForCondition(() => state.actions!.needsAttentionCount === 0, 'healthy point')
}

describe('metering status availability', () => {
    it('retains an assignment after failed removal, reports the error and allows retry', async () => {
        await healthyPoint()
        act(() => container.querySelector<HTMLButtonElement>('.metering-point-expand')!.click())
        const remove = () => container.querySelector<HTMLButtonElement>('.metering-assignment-actions .button-danger')!
        act(() => remove().click())
        act(() => Array.from(document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')).find(button => button.textContent === 'common.cancel')!.click())
        expect(state.write).not.toHaveBeenCalled()
        state.write.mockRejectedValueOnce(new Error('removal failed')).mockResolvedValueOnce(undefined)
        act(() => remove().click())
        act(() => Array.from(document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')).find(button => button.textContent === 'pages.meteringPoints.removeAssignConfirm')!.click())
        await waitForCondition(() => state.actions!.deleteAssignMutation.isError, 'failed removal')
        expect(container.querySelectorAll('.metering-assignment-row')).toHaveLength(1)
        expect(state.toast).toHaveBeenCalledWith(expect.any(String), 'error')
        act(() => remove().click())
        act(() => Array.from(document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')).find(button => button.textContent === 'pages.meteringPoints.removeAssignConfirm')!.click())
        await waitForCondition(() => container.querySelectorAll('.metering-assignment-row').length === 0, 'successful removal')
        expect(state.write.mock.calls).toEqual([['a42'], ['a42']])
    })
    it('checks incomplete quality only for the selected community', async () => {
        await healthyPoint()
        act(() => {
            client.setQueryData(queryKeys.metering.points('42'), ['42', '43'].map(zev => ({
                id: `mp${zev}`, zev, meter_id: `MP-${zev}`, meter_type: 'consumption', is_active: true, reading_count: 10,
            })))
        })
        await waitForCondition(() => state.actions!.meteringPointHealthById.get('mp43') === 'unknown', 'other community quality')
        expect(container.textContent).not.toContain('pages.meteringPoints.qualityIncomplete')
    })

    it('uses the selected community assignments and quality after switching communities', async () => {
        await healthyPoint()
        state.quality.mockImplementation(({ zevId }: { zevId: string }) => Promise.resolve({ metering_points: [{ id: `mp${zevId}`, severity: 'green' }] }))
        state.zevId = '43'
        await render()
        await waitForCondition(() => state.actions!.dataQualityQuery.data?.metering_points[0]?.id === 'mp43' && !state.actions!.meteringPointsQuery.isFetching, 'new community responses')
        act(() => client.setQueryData(queryKeys.metering.points('43'), [{ id: 'mp43', zev: '43', meter_id: 'MP-43', meter_type: 'consumption', is_active: true, reading_count: 10 }]))
        await waitForCondition(() => state.actions!.meteringPointHealthById.get('mp43') === 'green', 'new community quality')
        expect(state.actions!.needsAttentionCount).toBe(1)
        expect(state.actions!.meteringPointHolderLessById.get('mp43')).toBe(true)
        act(() => client.setQueryData(queryKeys.metering.pointAssignments(), [{ id: 'a43', metering_point: 'mp43', participant: 'p43', valid_from: '2020-01-01', valid_to: null }]))
        await waitForCondition(() => state.actions!.needsAttentionCount === 0, 'new community assignment')
        expect(state.actions!.scopedMeteringPoints.map(point => point.id)).toEqual(['mp43'])
    })
    it('does not count pending quality, then updates when a confirmed problem arrives', async () => {
        await healthyPoint()
        let resolve!: (value: unknown) => void
        state.quality.mockImplementation(() => new Promise(done => { resolve = done }))
        act(() => { void client.resetQueries({ queryKey: ['metering', 'quality-status'] }) })
        await waitForCondition(() => state.actions!.dataQualityQuery.isFetching && state.actions!.meteringPointHealthById.get('mp42') === 'unknown', 'pending quality')
        expect(state.actions!.needsAttentionCount).toBe(0)
        expect(container.textContent).toContain('pages.meteringPoints.qualityLoading')
        resolve({ metering_points: [{ id: 'mp42', severity: 'red' }] })
        await waitForCondition(() => state.actions!.needsAttentionCount === 1, 'confirmed data problem')
    })

    it('does not count failed quality and offers a retry', async () => {
        await healthyPoint()
        state.quality.mockRejectedValue(new Error('quality unavailable'))
        await act(async () => { await client.resetQueries({ queryKey: ['metering', 'quality-status'] }) })
        await waitForCondition(() => state.actions!.dataQualityQuery.isError, 'failed quality')
        expect(state.actions!.needsAttentionCount).toBe(0)
        expect(container.textContent).toContain('pages.meteringPoints.qualityLoadFailed')
        state.quality.mockResolvedValue({ metering_points: [{ id: 'mp42', severity: 'green' }] })
        const notice = container.querySelector('.notice--retry')!
        act(() => notice.querySelector<HTMLButtonElement>('button')!.click())
        await waitForCondition(() => state.actions!.meteringPointHealthById.get('mp42') === 'green', 'retried quality')
    })

    it('keeps a missing quality entry unknown and preserves an independently known assignment problem', async () => {
        await healthyPoint()
        act(() => { client.setQueriesData({ queryKey: ['metering', 'quality-status'] }, { metering_points: [] }) })
        await waitForCondition(() => state.actions!.meteringPointHealthById.get('mp42') === 'unknown', 'missing quality entry')
        expect(state.actions!.needsAttentionCount).toBe(0)
        expect(container.textContent).toContain('pages.meteringPoints.qualityIncomplete')
        act(() => { client.setQueryData(queryKeys.metering.pointAssignments(), []) })
        await waitForCondition(() => state.actions!.needsAttentionCount === 1, 'confirmed missing assignment')
    })

    for (const failure of [false, true]) {
        it(`does not infer an absent assignment from ${failure ? 'failed' : 'pending'} assignments`, async () => {
            await healthyPoint()
            if (failure) state.assignments.mockRejectedValue(new Error('assignments unavailable'))
            else state.assignments.mockImplementation(() => new Promise(() => {}))
            act(() => { void client.resetQueries({ queryKey: queryKeys.metering.pointAssignments() }) })
            await waitForCondition(() => failure ? state.actions!.assignmentsQuery.isError : state.actions!.assignmentsQuery.isFetching, 'assignment request')
            await waitForCondition(() => !state.actions!.meteringPointHolderLessById.has('mp42'), 'unknown assignment status')
            expect(state.actions!.needsAttentionCount).toBe(0)
            expect(state.actions!.unassignedCount).toBe(0)
            expect(container.querySelector('.metering-point-holder .button-primary')).toBeNull()
            expect(container.textContent).toContain(failure ? 'pages.meteringPoints.assignmentsLoadFailed' : 'pages.meteringPoints.assignmentsLoading')
            act(() => state.actions!.setView('unassigned'))
            expect(state.actions!.meteringPoints).toEqual([])
        })
    }

    it('retains the last confirmed status if a refresh fails', async () => {
        await healthyPoint()
        state.quality.mockRejectedValue(new Error('refresh failed'))
        await act(async () => { await state.actions!.dataQualityQuery.refetch() })
        await waitForCondition(() => state.actions!.dataQualityQuery.isError, 'failed refresh')
        expect(state.actions!.meteringPointHealthById.get('mp42')).toBe('green')
        expect(state.actions!.needsAttentionCount).toBe(0)
        expect(container.textContent).toContain('pages.meteringPoints.qualityLoadFailed')
    })

    it('updates all filters on same-page navigation and back navigation', () => {
        act(() => state.navigate!('/metering/points?view=inactive&search=roof&type=production&building=b1&sort=location'))
        expect(state.actions!).toMatchObject({ view: 'inactive', searchTerm: 'roof', typeFilter: 'production', buildingFilter: 'b1', sort: 'location' })
        expect(state.actions!.meteringPoints).toEqual([])
        act(() => state.navigate!(-1))
        expect(state.actions!).toMatchObject({ view: 'all', searchTerm: '', typeFilter: 'all', buildingFilter: 'all', sort: 'meter_id' })
        expect(state.actions!.meteringPoints.map(point => point.id)).toEqual(['mp42'])
    })
})
