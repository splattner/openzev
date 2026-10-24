import { act, createElement, useLayoutEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { waitForCondition } from './helpers/waitForCondition'
import { useTariffCrud } from '../src/features/tariffs/useTariffCrud'
import { useTariffVersions } from '../src/features/tariffs/useTariffVersions'
import type { Tariff, TariffInput, TariffPeriodInput, TariffSeries, TariffVersion } from '../src/types/api'
import { queryKeys } from '../src/lib/api/queryKeys'

const api = vi.hoisted(() => ({ save: vi.fn(), remove: vi.fn(), rename: vi.fn(), userId: 1 }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: api.userId } }) }))
vi.mock('../src/lib/api/tariffs', () => ({
    createTariff: api.save, updateTariff: api.save, deleteTariff: api.remove,
    createTariffPeriod: api.save, updateTariffPeriod: api.save, deleteTariffPeriod: api.remove,
    createTariffVersion: api.save, duplicateTariff: api.save, renameTariffSeries: api.rename,
}))
let root: ReturnType<typeof createRoot>
let client: QueryClient
let container: HTMLDivElement
let crud: ReturnType<typeof useTariffCrud>
let versions: ReturnType<typeof useTariffVersions>
let zevId: string
let canWrite: boolean
let confirmation: { onConfirm: () => void }
const toast = vi.fn()
const tariffSaved = vi.fn()
const versionSaved = vi.fn()
const tariff = { id: 'tariff-A', zev: 'A' } as Tariff
const series = { zev: 'A' } as TariffSeries
const source = { id: tariff.id } as TariffVersion
function Harness() {
    const shared = { selectedZevId: zevId, canWrite, queryClient: client, pushToast: toast, t: (key: string) => key }
    const currentCrud = useTariffCrud({ ...shared, tariffs: [tariff], periods: [], bandableTariffs: [tariff], tariffNameById: new Map(), confirm: options => { confirmation = options }, onTariffSaved: tariffSaved })
    const currentVersions = useTariffVersions({ ...shared, onSaved: versionSaved })
    useLayoutEffect(() => { crud = currentCrud; versions = currentVersions }, [currentCrud, currentVersions])
    return null
}
async function render() {
    await act(async () => root.render(createElement(QueryClientProvider, { client }, createElement(Harness))))
}
beforeEach(async () => {
    vi.clearAllMocks()
    api.userId = 1
    zevId = 'A'
    canWrite = true
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
    client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    await render()
})
afterEach(() => { act(() => root.unmount()); client.clear(); container.remove() })

it.each(['community', 'permission', 'account'])('resets write dialogs and refuses a captured delete after a %s change', async change => {
    act(() => {
        crud.openCreateTariff()
        crud.openCreatePeriod()
        versions.openRename(series, source)
        crud.confirmDeleteTariff(tariff)
    })
    const captured = confirmation.onConfirm
    if (change === 'community') zevId = 'B'
    if (change === 'permission') canWrite = false
    if (change === 'account') api.userId = 2
    await render()
    expect(crud.tariffFormOpen).toBe(false)
    expect(crud.periodFormOpen).toBe(false)
    expect(versions.dialog).toBeNull()
    act(() => captured())
    expect(api.remove).not.toHaveBeenCalled()
})

it.each(['save', 'rename'])('ignores delayed %s UI completion while invalidating the submitting community', async operation => {
    let resolve!: (value: Tariff) => void
    const pending = new Promise<Tariff>(done => { resolve = done })
    api.save.mockReturnValue(pending)
    api.rename.mockReturnValue(pending)
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    act(() => {
        if (operation === 'save') {
            crud.openCreateTariff()
            crud.submitTariff({ name: 'A' } as TariffInput)
        } else {
            versions.openRename(series, source)
            versions.submitRename(tariff.id, 'renamed A')
        }
    })
    await waitForCondition(() => api.save.mock.calls.length + api.rename.mock.calls.length > 0, 'submitted write')
    zevId = 'B'
    await render()
    act(() => { crud.openCreateTariff(); versions.openRename({ ...series, zev: 'B' }, source) })
    await act(async () => resolve(tariff))
    await waitForCondition(() => invalidate.mock.calls.length > 0, 'cache invalidation')
    expect(crud.tariffFormOpen).toBe(true)
    expect(versions.dialog).not.toBeNull()
    expect(toast).not.toHaveBeenCalled()
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.tariffs.series('A') })
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: queryKeys.tariffs.series('B') })
})


it('does not save a tariff period without a resolved community, even with admin write capability', async () => {
    zevId = ''
    await render()
    act(() => crud.submitPeriod({ tariff: tariff.id } as TariffPeriodInput))
    expect(api.save).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith('pages.tariffs.messages.periodSaveFailed', 'error')
})

const submissions = ['tariff', 'period', 'version', 'duplicate', 'rename'].map(name => ({ name }))
for (const change of ['community', 'permission', 'account'] as const) {
    it.each(submissions)(`rejects a retained $name submission after a ${change} change`, async ({ name }) => {
        const previousCrud = crud
        const previousVersions = versions
        const submit = () => {
            if (name === 'tariff') previousCrud.submitTariff({ name: 'A' } as TariffInput)
            if (name === 'period') previousCrud.submitPeriod({ tariff: tariff.id } as TariffPeriodInput)
            if (name === 'version') previousVersions.submitNewVersion(tariff.id, {} as Parameters<typeof versions.submitNewVersion>[1])
            if (name === 'duplicate') previousVersions.submitDuplicate(tariff.id, { name: 'copy' } as Parameters<typeof versions.submitDuplicate>[1])
            if (name === 'rename') previousVersions.submitRename(tariff.id, 'renamed')
        }
        if (change === 'community') zevId = 'B'
        if (change === 'permission') canWrite = false
        if (change === 'account') api.userId = 2
        await render()
        await act(async () => submit())
        expect(api.save).not.toHaveBeenCalled()
        expect(api.rename).not.toHaveBeenCalled()
        expect(toast).not.toHaveBeenCalled()
    })
}

it('rejects a tariff write queued before its submitting scope changes', async () => {
    act(() => {
        crud.submitTariff({ name: 'A' } as TariffInput)
        zevId = 'B'
        root.render(createElement(QueryClientProvider, { client }, createElement(Harness)))
    })
    await act(async () => undefined)
    expect(api.save).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
})

it('closes the form and selects what was saved once the series has been refetched', async () => {
    api.save.mockResolvedValue(tariff)
    act(() => {
        crud.openCreateTariff()
        crud.submitTariff({ name: 'A' } as TariffInput)
    })
    await waitForCondition(() => tariffSaved.mock.calls.length > 0, 'saved tariff selected')
    expect(tariffSaved).toHaveBeenCalledWith(tariff, 'created')
    expect(crud.tariffFormOpen).toBe(false)
    expect(toast).toHaveBeenCalledWith('pages.tariffs.messages.created', 'success')
})

it('keeps a failed save in the form as a notice, not only a toast', async () => {
    api.save.mockRejectedValue(new Error('boom'))
    act(() => {
        crud.openCreateTariff()
        crud.submitTariff({ name: 'A' } as TariffInput)
    })
    await waitForCondition(() => crud.saveError !== null, 'save error')
    expect(crud.saveError).toBe('pages.tariffs.messages.saveFailed')
    expect(crud.tariffFormOpen).toBe(true)
    expect(toast).not.toHaveBeenCalled()
    act(() => crud.closeTariffForm())
    expect(crud.saveError).toBeNull()
})

it.each(['save', 'rename'])('a %s finishing after its form was closed neither reopens nor selects anything', async operation => {
    let resolve!: (value: Tariff) => void
    const pending = new Promise<Tariff>(done => { resolve = done })
    api.save.mockReturnValue(pending)
    api.rename.mockReturnValue(pending)
    act(() => {
        if (operation === 'save') {
            crud.startTariffEdit(tariff)
            crud.submitTariff({ name: 'A' } as TariffInput)
        } else {
            versions.openRename(series, source)
            versions.submitRename(tariff.id, 'renamed A')
        }
    })
    await waitForCondition(() => api.save.mock.calls.length + api.rename.mock.calls.length > 0, 'submitted write')
    // The user walks away from the form, then starts another one.
    act(() => {
        crud.closeTariffForm()
        versions.closeDialog()
        versions.openDuplicate(series, source)
    })
    await act(async () => resolve(tariff))
    await act(async () => undefined)
    expect(tariffSaved).not.toHaveBeenCalled()
    expect(versionSaved).not.toHaveBeenCalled()
    expect(crud.tariffFormOpen).toBe(false)
    expect(versions.dialog?.kind).toBe('duplicate')
})
