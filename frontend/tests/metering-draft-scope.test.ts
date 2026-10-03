import { waitForCondition } from './helpers/waitForCondition'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { useMeteringPointActions } from '../src/features/meteringPoints/useMeteringPointActions'

const state = vi.hoisted(() => ({
    zevId: '42', relation: 'manager', userId: 1, disabled: false, role: 'user', scopeFailed: false,
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
    fetchParticipants: async () => [], fetchMeteringPointAssignments: async () => [],
    fetchMeteringPoints: async () => ['42', '43'].map(zev => ({
        id: `mp${zev}`, zev, meter_id: `MP-${zev}`, meter_type: 'consumption',
        is_active: true, has_behind_meter_generation: false,
    })),
}))
vi.mock('../src/lib/api/metering', () => ({ fetchMeteringDataQualityStatus: async () => ({ metering_points: [] }) }))

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

async function render() {
    await act(async () => root.render(createElement(MemoryRouter, null,
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
                ? container.querySelector<HTMLButtonElement>('.metering-point-actions .button-primary')!
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
    container.remove()
})

describe('metering draft context', () => {
    for (const mode of ['create', 'edit'] as const) {
        for (const change of ['community', 'write access', 'account']) {
            it(`closes a ${mode} draft when ${change} changes`, async () => {
                await openDraft(mode)
                if (change === 'community') state.zevId = '43'
                else if (change === 'account') state.userId = 2
                else state.relation = 'viewer'
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
        payload: { zev: '42', meter_id: 'draft', meter_type: 'consumption', is_active: true, has_behind_meter_generation: false },
    }) },
    { name: 'meter edit', run: (actions: ReturnType<typeof useMeteringPointActions>) => actions.saveMpMutation.mutateAsync({
        id: 'mp42', payload: { zev: '42', meter_id: 'edited', meter_type: 'consumption', is_active: true, has_behind_meter_generation: false },
    }) },
    { name: 'meter delete', run: (actions: ReturnType<typeof useMeteringPointActions>) => actions.deleteMpMutation.mutateAsync('mp42') },
    { name: 'assignment save', run: (actions: ReturnType<typeof useMeteringPointActions>) => actions.saveAssignMutation.mutateAsync({
        payload: { metering_point: 'mp42', participant: 'p42', valid_from: '2026-01-01', valid_to: null, allocation_mode: 'normal' },
    }) },
    { name: 'assignment delete', run: (actions: ReturnType<typeof useMeteringPointActions>) => actions.deleteAssignMutation.mutateAsync('assignment42') },
    { name: 'reading delete', run: (actions: ReturnType<typeof useMeteringPointActions>) => actions.deleteMeteringDataMutation.mutateAsync({
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
            it.each(writes)(`ignores an obsolete $name ${outcome} after changing ${change}`, async ({ run }) => {
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
                if (change === 'account') state.userId = 2
                else state.zevId = '43'
                await render()
                const invalidate = vi.spyOn(client, 'invalidateQueries')
                await act(async () => {
                    if (outcome === 'success') resolve({ deleted_count: 1 })
                    else reject(new Error('Old write failed'))
                    await settled
                })
                expect(state.write.mock.calls).toEqual([submitted])
                expect(state.toast).not.toHaveBeenCalled()
                expect(invalidate).not.toHaveBeenCalled()
                expect(document.querySelector('[role="dialog"]')).toBeNull()
            })
        }
    }
})
