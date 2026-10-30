import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { queryKeys } from '../src/lib/api/queryKeys'
import { ZevListPage } from '../src/pages/ZevListPage'
import { AdminDynamicSourcesPanel } from '../src/pages/AdminDynamicSourcesPanel'
import { waitForCondition } from './helpers/waitForCondition'

const submitted = vi.hoisted(() => ({
    handleConfirm: null as (() => Promise<void>) | null,
    purge: vi.fn(), clear: vi.fn(), delete: vi.fn(), toast: vi.fn(),
}))
const zev = { id: '42', name: 'Disabled ZEV', disabled_at: '2026-10-01', zev_type: 'zev', billing_interval: 'monthly', start_date: '2026-01-01' }
const source = { id: 's1', label: 'Operator source', enabled: true, point_count: 1, linked_tariff_count: 0, linked_zev_count: 0 }
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: 1, role: 'admin' } }) }))
vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => ({ selectedZevId: '', setSelectedZevId: vi.fn() }),
    useOptionalManagedZev: () => ({ selectedZevId: '' }),
}))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }), formatShortDate: (value: string) => value,
    formatDateTime: (value: string) => value,
}))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: submitted.toast }) }))
vi.mock('../src/lib/api/zev', async importOriginal => ({
    ...await importOriginal<typeof import('../src/lib/api/zev')>(),
    fetchZevs: async () => [zev], purgeZev: submitted.purge,
}))
vi.mock('../src/lib/api/tariffs', async importOriginal => ({
    ...await importOriginal<typeof import('../src/lib/api/tariffs')>(),
    fetchDynamicTariffSources: async () => [source], clearDynamicSourcePrices: submitted.clear,
    deleteDynamicTariffSource: submitted.delete,
}))
// Capture the real hook handler to test dispatch even when the button is disabled.
vi.mock('../src/components/ConfirmDialog', async importOriginal => {
    const actual = await importOriginal<typeof import('../src/components/ConfirmDialog')>()
    return { ...actual, useConfirmDialog: () => {
        const dialog = actual.useConfirmDialog()
        submitted.handleConfirm = dialog.handleConfirm
        return dialog
    } }
})

let root: ReturnType<typeof createRoot>, container: HTMLDivElement, client: QueryClient
beforeEach(() => {
    vi.clearAllMocks()
    submitted.handleConfirm = null
    submitted.purge.mockResolvedValue({})
    submitted.clear.mockResolvedValue({ deleted_points: 1 })
    submitted.delete.mockResolvedValue(undefined)
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    client.setQueryData(queryKeys.zev.list(), [zev])
    client.setQueryData(queryKeys.tariffs.dynamicSources(), [source])
})
afterEach(() => { act(() => root.unmount()); client.clear(); container.remove() })

async function render(page: typeof ZevListPage | typeof AdminDynamicSourcesPanel) {
    await act(async () => root.render(createElement(QueryClientProvider, { client },
        createElement(MemoryRouter, null, createElement(MantineProvider, null, createElement(page))),
    )))
}
async function click(text: string) {
    const find = () => Array.from(document.querySelectorAll<HTMLElement>('button, [role=menuitem]'))
        .find(element => element.textContent?.trim() === text)
    await waitForCondition(() => !!find(), text)
    const button = find()
    expect(button).toBeDefined()
    await act(async () => button!.click())
}
function fill(value: string) {
    const input = container.querySelector<HTMLInputElement>('[role=dialog] input')!
    act(() => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
        input.dispatchEvent(new Event('input', { bubbles: true }))
    })
}

describe('typed confirmation dispatch', () => {
    for (const action of ['purge', 'clear', 'delete'] as const) {
        it(`rejects invalid current input before dispatching ${action}`, async () => {
            await render(action === 'purge' ? ZevListPage : AdminDynamicSourcesPanel)
            if (action === 'purge') await click('pages.zevs.purge')
            else {
                await click('common.actions')
                await click(action === 'clear' ? 'pages.dynamicSources.clearAction' : 'pages.dynamicSources.deleteAction')
            }
            const expected = action === 'purge' ? zev.name : source.label
            fill(expected)
            fill('Incorrect confirmation')
            await act(async () => { await submitted.handleConfirm!() })
            expect(submitted[action]).not.toHaveBeenCalled()
            expect(container.querySelector('[role=dialog]')).not.toBeNull()
            fill(expected)
            await act(async () => { await submitted.handleConfirm!() })
            expect(submitted[action]).toHaveBeenCalledOnce()
            expect(submitted[action]).toHaveBeenCalledWith(action === 'purge' ? zev.id : source.id, expected)
        })
    }
})


it('shows the translated coded source error without exposing response metadata', async () => {
    submitted.clear.mockRejectedValue({ isAxiosError: true, response: { data: {
        confirmation: ['Reworded diagnostic'], validation_errors: [{
            code: 'source_busy', field: null, path: ['detail'], params: {}, message: 'Reworded diagnostic',
        }],
    } } })
    await render(AdminDynamicSourcesPanel)
    await click('common.actions')
    await click('pages.dynamicSources.clearAction')
    fill(source.label)
    await act(async () => { await submitted.handleConfirm!() })
    await waitForCondition(() => submitted.toast.mock.calls.length > 0, 'coded source error toast')
    expect(submitted.toast).toHaveBeenCalledWith('pages.tariffs.apiErrors.sourceBusy', 'error')
})
