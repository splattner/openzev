import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { TariffsPage } from '../src/pages/TariffsPage'
import { queryKeys } from '../src/lib/api/queryKeys'
import { setInputValue } from './helpers/render'
import { waitForCondition } from './helpers/waitForCondition'
import type { TariffSeries, TariffVersion } from '../src/types/api'

const api = vi.hoisted(() => ({ fetchSeries: vi.fn(), save: vi.fn(), remove: vi.fn() }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: 1, role: 'admin' } }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => ({ selectedZevId: 'z', selectedZev: { id: 'z', name: 'Z', vat_mode: 'exclusive' } }),
}))
vi.mock('../src/lib/communityAccess', () => ({
    useCommunityAccess: () => ({ isZevScope: true, canWriteSelectedCommunity: true }),
    useScopeNote: () => undefined,
}))
vi.mock('../src/lib/appSettings', async (importOriginal) => ({
    ...await importOriginal<typeof import('../src/lib/appSettings')>(),
    useAppSettings: () => ({ settings: { date_format_short: 'dd.MM.yyyy', date_format_long: 'd MMMM yyyy', date_time_format: 'dd.MM.yyyy HH:mm', updated_at: '' } }),
}))
vi.mock('../src/lib/api/tariffs', () => ({
    fetchTariffSeries: api.fetchSeries,
    updateTariff: api.save, createTariff: api.save, deleteTariff: api.remove,
    fetchDynamicTariffSources: vi.fn().mockResolvedValue([]),
}))
vi.mock('../src/lib/api/invoices', () => ({ downloadTariffOverview: vi.fn() }))
// The import dialog is its own feature; the page's part is when it opens.
vi.mock('../src/features/tariffs/VseTariffImportModal', () => ({
    VseTariffImportModal: ({ isOpen }: { isOpen: boolean }) => (isOpen ? createElement('div', { 'data-testid': 'import-modal' }) : null),
}))
vi.mock('../src/components/PageHeader', () => ({
    PageHeader: ({ actions }: { actions?: unknown }) => createElement('header', null, actions as never),
}))
vi.mock('../src/components/ScopeGuard', () => ({ ScopeGuard: ({ children }: { children: unknown }) => children }))

// Leaving, deleting and importing while a form holds a changed draft or a save
// is in flight (#1134; guard from SPEC-2026-10-ui-patterns §6.1, §6.2).

const version = (id: string, name: string): TariffVersion => ({
    id, zev: 'z', name, category: 'grid_fees', billing_mode: 'monthly_fee', energy_type: null,
    valid_from: '2000-01-01', valid_to: null, fixed_price_chf: '10.00', split_key: 'equal', notes: '', periods: [],
}) as unknown as TariffVersion
const seriesOf = (id: string, name: string) => ({
    zev: 'z', name, category: 'grid_fees', billing_mode: 'monthly_fee', energy_type: null,
    version_count: 1, active_version_id: id, gaps: [], versions: [version(id, name)],
}) as unknown as TariffSeries
const grid = seriesOf('grid', 'Grid')
const levy = seriesOf('levy', 'Levy')

let root: ReturnType<typeof createRoot>
let client: QueryClient
let container: HTMLDivElement
let router: ReturnType<typeof createMemoryRouter>
let shown: TariffSeries[]

const q = <T extends Element>(selector: string) => container.querySelector<T>(selector)
const click = async (element: Element | null) => { await act(async () => (element as HTMLElement).click()) }
const settle = () => act(async () => undefined)
// An existing version's name is not a field; its price is.
const priceInput = () => q<HTMLInputElement>('.tariff-pane-form input[type="number"]')
const editButton = () => q<HTMLButtonElement>('[data-action-key="edit-grid"]')
const dialogButton = (label: string) => [...document.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === label)

async function openEditForm(draft = '12.50') {
    await click(q('[data-row-key="z:Grid:grid"] .tariff-select, [data-row-key="z:Grid:grid"]'))
    await click(editButton())
    expect(priceInput()).not.toBeNull()
    if (draft) await act(async () => setInputValue(priceInput()!, draft))
}

beforeEach(async () => {
    vi.clearAllMocks()
    shown = [grid, levy]
    api.fetchSeries.mockImplementation(async () => shown)
    api.remove.mockResolvedValue(undefined)
    container = document.createElement('div')
    document.body.append(container)
    client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    router = createMemoryRouter([
        { path: '/tariffs', element: createElement(TariffsPage) },
        { path: '/other', element: createElement('p', null, 'elsewhere') },
    ], { initialEntries: ['/tariffs'] })
    root = createRoot(container)
    await act(async () => root.render(createElement(QueryClientProvider, { client }, createElement(MantineProvider, null, createElement(RouterProvider, { router })))))
    await waitForCondition(() => q('.tariff-select') !== null, 'tariff list')
})
afterEach(() => { act(() => root.unmount()); client.clear(); container.remove() })

const submit = () => click(q('button[type="submit"]'))
const asked = (message: string) => document.body.textContent?.includes(message) ?? false
const importButton = () => [...container.querySelectorAll('button')].find((button) => button.textContent === 'pages.tariffs.import.action')
const moreActions = () => container.querySelector('[aria-label="pages.tariffs.versions.moreActions"]')

/** A save that stays in flight until the test lets it land. */
function holdSave() {
    let land!: (saved: TariffVersion) => void
    api.save.mockReturnValue(new Promise<TariffVersion>((done) => { land = done }))
    return (saved: TariffVersion) => act(async () => land(saved))
}

/** The server now holds a tariff more, as after a VSE import. */
const importArrives = async () => {
    shown = [grid, levy, seriesOf('feed', 'Feed')]
    await act(async () => { await client.invalidateQueries({ queryKey: queryKeys.tariffs.series('z') }) })
}

it('lists the tariffs the harness serves', () => {
    expect(container.textContent).toContain('Grid')
    expect(container.textContent).toContain('Levy')
})

// Leaving

it('asks before in-app navigation drops a changed draft, and keeps it when the user stays', async () => {
    await openEditForm()
    await act(async () => { void router.navigate('/other') })
    expect(router.state.location.pathname).toBe('/tariffs')
    expect(asked('common.unsavedChanges.message')).toBe(true)
    await click(dialogButton('common.unsavedChanges.keepEditing') ?? null)
    expect(router.state.location.pathname).toBe('/tariffs')
    expect(priceInput()?.value).toBe('12.50')
    await act(async () => { void router.navigate('/other') })
    await click(dialogButton('common.unsavedChanges.discard') ?? null)
    expect(router.state.location.pathname).toBe('/other')
})

it('asks before in-app navigation while a save is in flight, and says it may still complete', async () => {
    holdSave()
    await openEditForm()
    await submit()
    expect(api.save).toHaveBeenCalledOnce()
    await act(async () => { void router.navigate('/other') })
    expect(router.state.location.pathname).toBe('/tariffs')
    expect(asked('common.unsavedChanges.messageSaving')).toBe(true)
})

it.each(['a changed draft', 'a save in flight'])('asks before switching to another tariff with %s', async (state) => {
    if (state === 'a save in flight') holdSave()
    await openEditForm()
    if (state === 'a save in flight') await submit()
    await click(q('[data-row-key="z:Levy:levy"] .tariff-select'))
    expect(asked(state === 'a save in flight' ? 'common.unsavedChanges.messageSaving' : 'common.unsavedChanges.message')).toBe(true)
    expect(router.state.location.search).toContain('Grid')
    expect(priceInput()).not.toBeNull()
})

it('leaves a save that lands after the draft was discarded where it was: no reopened form, no selection moved', async () => {
    const land = holdSave()
    await openEditForm()
    await submit()
    await click(q('[data-row-key="z:Levy:levy"] .tariff-select'))
    await click(dialogButton('common.unsavedChanges.discard') ?? null)
    expect(router.state.location.search).toContain('Levy')
    await land(version('grid', 'Grid (changed)'))
    await settle()
    expect(priceInput()).toBeNull()
    expect(router.state.location.search).toContain('Levy')
})

// Deleting

it.each(['a changed draft', 'a save in flight'])('offers no delete while a form holds %s', async (state) => {
    if (state === 'a save in flight') holdSave()
    await openEditForm()
    if (state === 'a save in flight') await submit()
    expect(moreActions()).toBeNull()
    expect(container.querySelector('.button-danger')).toBeNull()
})

it('deletes only the tariff asked about once a pending save has been let go, and the late save changes nothing', async () => {
    const land = holdSave()
    await openEditForm()
    await submit()
    await click(q('[data-row-key="z:Levy:levy"] .tariff-select'))
    await click(dialogButton('common.unsavedChanges.discard') ?? null)
    await click(q('[data-row-key="z:Grid:grid"] .tariff-select'))
    await click(moreActions())
    const deleteItem = () => [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((item) => item.textContent === 'pages.tariffs.versions.deleteVersion')
    await waitForCondition(() => deleteItem() !== undefined, 'the delete menu item')
    await click(deleteItem() ?? null)
    await click(dialogButton('pages.tariffs.deleteConfirm') ?? null)
    expect(api.remove).toHaveBeenCalledExactlyOnceWith('grid')
    shown = [levy]
    await land(version('grid', 'Grid (changed)'))
    await settle()
    expect(priceInput()).toBeNull()
})

// Importing

it('lets an import run over a changed draft: the draft is still there, and saves to its own tariff', async () => {
    await openEditForm()
    await click(importButton() ?? null)
    expect(q('[data-testid="import-modal"]')).not.toBeNull()
    expect(asked('common.unsavedChanges')).toBe(false)
    await importArrives()
    expect(priceInput()?.value).toBe('12.50')
    api.save.mockResolvedValue(version('grid', 'Grid (changed)'))
    await submit()
    expect(api.save).toHaveBeenCalledOnce()
    expect(api.save.mock.calls[0][0]).toBe('grid')
    expect(api.save.mock.calls[0][1]).toMatchObject({ fixed_price_chf: '12.50', zev: 'z' })
})

it('lets an import run while a save is in flight: the save still lands on its tariff', async () => {
    const land = holdSave()
    await openEditForm()
    await submit()
    await click(importButton() ?? null)
    await importArrives()
    shown = [seriesOf('grid', 'Grid (changed)'), levy, seriesOf('feed', 'Feed')]
    await land(version('grid', 'Grid (changed)'))
    await waitForCondition(() => priceInput() === null, 'form closed after the save')
    expect(router.state.location.search).toContain('Grid')
})
