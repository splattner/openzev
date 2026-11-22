import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest'
import { TariffsHubPage } from '../src/pages/TariffsHubPage'
import { queryKeys } from '../src/lib/api/queryKeys'
import { hasUnsavedZevSettingsDraft } from '../src/lib/zevUnsavedGuard'
import { setInputValue } from './helpers/render'
import { waitForCondition } from './helpers/waitForCondition'
import type { TariffSeries, TariffVersion } from '../src/types/api'

const api = vi.hoisted(() => ({ fetchSeries: vi.fn(), save: vi.fn(), remove: vi.fn(), savePeriod: vi.fn() }))
// The selected community, changeable like the real context.
const scope = vi.hoisted(() => {
    const listeners = new Set<() => void>()
    return {
        zevId: 'z',
        subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } },
        set(id: string) { this.zevId = id; listeners.forEach((listener) => listener()) },
    }
})
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: 1, role: 'admin' } }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/managedZev', async () => {
    const { useSyncExternalStore } = await import('react')
    return {
        useManagedZev: () => {
            const zevId = useSyncExternalStore(scope.subscribe, () => scope.zevId)
            return { selectedZevId: zevId, selectedZev: { id: zevId, name: 'Z', vat_mode: 'exclusive' } }
        },
    }
})
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
    updateTariff: api.save, createTariff: api.save, deleteTariff: api.remove, createTariffPeriod: api.savePeriod,
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

// Cold module loading is covered in the browser; keep draft-guard waits about the UI.
beforeAll(async () => { await import('../src/pages/TariffsPage') })

beforeEach(async () => {
    vi.clearAllMocks()
    scope.zevId = 'z'
    shown = [grid, levy]
    api.fetchSeries.mockImplementation(async () => shown)
    api.remove.mockResolvedValue(undefined)
    container = document.createElement('div')
    document.body.append(container)
    client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    router = createMemoryRouter([
        { path: '/tariffs', element: createElement(TariffsHubPage, { tab: 'components' }) },
        { path: '/tariffs/progression', element: createElement('p', null, 'progression') },
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
const deleteVersionButton = () => container.querySelector('.tariff-version-card-actions .button-destructive')

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

it('uses tabs to switch views and preserves the selected tariff in the URL', async () => {
    await click(q('[data-row-key="z:Grid:grid"] .tariff-select'))
    const search = router.state.location.search
    const tabs = [...container.querySelectorAll('[role="tab"]')]
    expect(tabs.map((tab) => tab.textContent)).toEqual([
        'pages.tariffs.tabs.components', 'pages.tariffs.tabs.progression',
    ])
    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
    expect(document.getElementById(tabs[0].getAttribute('aria-controls')!)?.getAttribute('role')).toBe('tabpanel')
    await click(tabs[1])
    expect(router.state.location.pathname).toBe('/tariffs/progression')
    expect(router.state.location.search).toBe(search)
})

it('guards switching tabs with an unsaved draft, allowing keep editing or discard', async () => {
    await openEditForm()
    const progressionTab = () => [...container.querySelectorAll('[role="tab"]')][1]
    await click(progressionTab())
    expect(router.state.location.pathname).toBe('/tariffs')
    expect(asked('common.unsavedChanges.message')).toBe(true)
    await click(dialogButton('common.unsavedChanges.keepEditing') ?? null)
    expect(priceInput()?.value).toBe('12.50')
    expect(q('[role="tab"][aria-selected="true"]')?.textContent).toBe('pages.tariffs.tabs.components')
    await click(progressionTab())
    await click(dialogButton('common.unsavedChanges.discard') ?? null)
    expect(router.state.location.pathname).toBe('/tariffs/progression')
})

it('does not navigate or ask to discard when the selected tab is activated', async () => {
    await openEditForm()
    const location = router.state.location
    await click(q('[role="tab"][aria-selected="true"]'))
    expect(router.state.location).toBe(location)
    expect(asked('common.unsavedChanges.message')).toBe(false)
    expect(priceInput()?.value).toBe('12.50')
})

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
    expect(deleteVersionButton()).toBeNull()
    expect(container.querySelector('.button-danger')).toBeNull()
})

it('deletes only the tariff asked about once a pending save has been let go, and the late save changes nothing', async () => {
    const land = holdSave()
    await openEditForm()
    await submit()
    await click(q('[data-row-key="z:Levy:levy"] .tariff-select'))
    await click(dialogButton('common.unsavedChanges.discard') ?? null)
    await click(q('[data-row-key="z:Grid:grid"] .tariff-select'))
    await click(deleteVersionButton())
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

// The community switcher

it('tells the community switcher about a changed draft, and stops once the page is left', async () => {
    expect(hasUnsavedZevSettingsDraft()).toBe(false)
    await openEditForm('')
    expect(hasUnsavedZevSettingsDraft()).toBe(false)
    await act(async () => setInputValue(priceInput()!, '12.50'))
    expect(hasUnsavedZevSettingsDraft()).toBe(true)
    await act(async () => { void router.navigate('/other') })
    await click(dialogButton('common.unsavedChanges.discard') ?? null)
    expect(hasUnsavedZevSettingsDraft()).toBe(false)
})

it('tells the community switcher about a save in flight from an unchanged form', async () => {
    holdSave()
    await openEditForm('')
    await submit()
    expect(api.save).toHaveBeenCalledOnce()
    expect(hasUnsavedZevSettingsDraft()).toBe(true)
})

it('closes an open form when the community changes', async () => {
    await click([...container.querySelectorAll('button')].find((button) => button.textContent === 'pages.tariffs.newTariff') ?? null)
    expect(q('.tariff-pane-form')).not.toBeNull()
    await act(async () => scope.set('other'))
    expect(q('.tariff-pane-form')).toBeNull()
    expect(hasUnsavedZevSettingsDraft()).toBe(false)
})

// Band coverage

it('adds the band the coverage warning offers with its days and months, and gives focus back on cancel', async () => {
    const summer = '4,5,6,7,8,9'
    const band = (id: string, extra: object) => ({ id, tariff: 'energy', label: '', price_chf_per_kwh: '0.2', percentage: null,
        time_from: null, time_to: null, weekdays: '', months: '', ...extra })
    const energy = { ...version('energy', 'Energy'), billing_mode: 'energy', periods: [
        band('h', { period_type: 'high', time_from: '07:00:00', time_to: '21:00:00', weekdays: '0,1,2,3,4', months: summer }),
        band('w', { period_type: 'low', weekdays: '5,6', months: summer }),
        band('x', { period_type: 'low', months: '1,2,3,10,11,12' }),
    ] } as unknown as TariffVersion
    shown = [{ ...seriesOf('energy', 'Energy'), billing_mode: 'energy', versions: [energy] } as unknown as TariffSeries]
    api.savePeriod.mockResolvedValue({})
    await act(async () => { await client.invalidateQueries({ queryKey: queryKeys.tariffs.series('z') }) })
    await waitForCondition(() => q('[data-row-key="z:Energy:energy"]') !== null, 'energy row')
    await click(q('[data-row-key="z:Energy:energy"] .tariff-select, [data-row-key="z:Energy:energy"]'))
    const offer = () => q<HTMLButtonElement>('[data-action-key="add-gap-band-energy"]')
    const checkedChips = () => container.querySelectorAll('.tariff-pane-form input[type="checkbox"]:checked').length

    await click(offer())
    expect(checkedChips()).toBe(5 + 6)
    await click(dialogButton('common.cancel'))
    expect(document.activeElement).toBe(offer())

    // The plain add starts from no seed: every weekday and month.
    await click(q('[data-action-key="add-period-energy"]'))
    expect(checkedChips()).toBe(7 + 12)
    await click(dialogButton('common.cancel'))

    await click(offer())
    await act(async () => setInputValue(priceInput()!, '0.25'))
    await submit()
    expect(api.savePeriod).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
        tariff: 'energy', period_type: 'band', price_chf_per_kwh: '0.25', time_from: null, time_to: null, weekdays: '0,1,2,3,4', months: summer,
    }))
})
