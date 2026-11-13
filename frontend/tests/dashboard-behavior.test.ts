import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, type ReactElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { HourlyProfileEntry, MembershipParticipant } from '../src/types/api'
import { waitForCondition } from './helpers/waitForCondition'

type ProfileData = HourlyProfileEntry[] | null
type ProfileMock = ProfileData | Promise<ProfileData> | ((args: Record<string, unknown>) => ProfileData | Promise<ProfileData>)

function deferred<T>() {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise })
    return { promise, resolve }
}

const eligibility = vi.hoisted(() => ({
    eligible: [] as Array<{ metering_point: string; meter_id: string; zev: string; zev_name: string; participant: string; source: string | null }>,
}))

const mockState = vi.hoisted(() => ({
    // The account's relation to the selected community (#761).
    relation: 'manager',
    selectedZevId: 'z1',
    membershipInterval: 'monthly' as string | undefined,
    secondMembershipInterval: null as string | null,
    secondMembershipSelectable: true,
    summary: null as unknown,
    summaryCalls: [] as Array<Record<string, unknown>>,
    hourlyProfile: null as ProfileMock,
    hourlyCalls: [] as Array<Record<string, unknown>>,
    participantMemberships: [{ id: 'me', valid_from: '2026-01-01', valid_to: null, live: true }] as MembershipParticipant[],
    membershipsAvailable: true,
}))

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (k: string) => k,
        i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
}))

vi.mock('../src/lib/supplementary', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/supplementary')>()
    return {
        ...actual,
        useEnergyDataEligibility: () => ({
            isLoading: false,
            featureOn: true,
            eligible: eligibility.eligible,
            historyEligible: eligibility.eligible,
            liveEligible: [],
            canConnect: eligibility.eligible.length > 0,
        }),
    }
})

vi.mock('../src/lib/auth', () => ({
    useAuth: () => ({
        user: {
            role: 'user',
            memberships: mockState.membershipsAvailable
                ? [
                    ...(mockState.participantMemberships.length ? [{ zev: 'z1', zev_billing_interval: mockState.membershipInterval, participants: mockState.participantMemberships }] : []),
                    ...(mockState.secondMembershipInterval ? [{ zev: 'z2', zev_billing_interval: mockState.secondMembershipInterval, participants: [{ id: 'me-z2', valid_from: '2026-01-01', valid_to: null, live: true }] }] : []),
                ]
                : undefined,
        },
    }),
}))

vi.mock('../src/lib/managedZev', () => {
    const context = {
        useManagedZev: () => ({
            managedZevs: [{ id: 'z1', name: 'Z1' }, { id: 'z2', name: 'Z2' }],
            selectedZevId: mockState.selectedZevId,
            selectedZev:
                mockState.relation === 'participant'
                    ? null
                    : { id: mockState.selectedZevId, name: mockState.selectedZevId.toUpperCase(), billing_interval: 'monthly' },
            relation: mockState.relation,
            entries: (mockState.secondMembershipInterval && mockState.secondMembershipSelectable ? ['z1', 'z2'] : [mockState.selectedZevId]).map((id) => ({
                id, name: id.toUpperCase(), relation: mockState.relation,
            })),
            isLoading: false,
        }),
    }
    return { ...context, useOptionalManagedZev: context.useManagedZev }
})

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (d: string) => d,
}))

vi.mock('../src/lib/api/metering', () => ({
    fetchMeteringDashboardSummary: (args: Record<string, unknown>) => {
        mockState.summaryCalls.push(args ?? {})
        const value =
            typeof mockState.summary === 'function'
                ? (mockState.summary as (a: Record<string, unknown>) => unknown)(args ?? {})
                : mockState.summary
        return Promise.resolve(value)
    },
    fetchHourlyProfile: (args: Record<string, unknown>) => {
        mockState.hourlyCalls.push(args)
        const value = typeof mockState.hourlyProfile === 'function'
            ? mockState.hourlyProfile(args)
            : mockState.hourlyProfile
        return Promise.resolve(value).then((hourly_profile) => ({ hourly_profile }))
    },
}))

vi.mock('../src/lib/api/invoices', () => ({ fetchInvoices: vi.fn(), openInvoicePdf: vi.fn() }))

vi.mock('../src/components/dashboard/HourlyProfileCard', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/components/dashboard/HourlyProfileCard')>()
    return { ...actual, HourlyProfileCard: vi.fn(actual.HourlyProfileCard) }
})

import { DashboardPage } from '../src/pages/DashboardPage'
import { ParticipantDashboardBody } from '../src/features/dashboard/ParticipantDashboardBody'
import { HourlyProfileCard } from '../src/components/dashboard/HourlyProfileCard'
import { ToastProvider } from '../src/lib/toast'

const cleanups: Array<() => void> = []
afterEach(() => {
    cleanups.splice(0).forEach((cleanup) => cleanup())
    mockState.selectedZevId = 'z1'
    vi.clearAllMocks()
    vi.useRealTimers()
    mockState.membershipInterval = 'monthly'
    mockState.secondMembershipInterval = null
    mockState.secondMembershipSelectable = true
    mockState.participantMemberships = [{ id: 'me', valid_from: '2026-01-01', valid_to: null, live: true }]
    mockState.membershipsAvailable = true
    eligibility.eligible = []
})

function managerSummary() {
    return {
        summary_kind: 'zev',
        bucket: 'day',
        zev_totals: { produced_kwh: 100, consumed_kwh: 80, imported_kwh: 20, exported_kwh: 40 },
        timeline: [],
        participant_stats: [
            {
                participant_id: 'p1',
                participant_name: 'Alice',
                total_consumed_kwh: 50,
                total_produced_kwh: 10,
                from_zev_kwh: 35,
                from_grid_kwh: 15,
            },
            {
                participant_id: 'p2',
                participant_name: 'Bob',
                total_consumed_kwh: 30,
                total_produced_kwh: 5,
                from_zev_kwh: 20,
                from_grid_kwh: 10,
            },
        ],
        selected_participant_name: null,
    }
}

function participantSummary(currentParticipantId: string | null) {
    return {
        summary_kind: 'participant',
        bucket: 'day',
        totals: { consumed_from_zev_kwh: 35, imported_from_grid_kwh: 15, total_consumed_kwh: 50 },
        timeline: [],
        zev_totals: { produced_kwh: 100, consumed_kwh: 80, imported_kwh: 20, exported_kwh: 40 },
        zev_participant_stats: [
            {
                participant_id: 'me',
                participant_name: 'Me',
                total_consumed_kwh: 50,
                total_produced_kwh: 10,
                from_zev_kwh: 35,
                from_grid_kwh: 15,
            },
        ],
        current_participant_id: currentParticipantId,
    }
}

// Re-renders the last mounted dashboard, as a community switch in the provider would.
let rerenderDashboard: () => Promise<void> = async () => {}

async function renderDashboard(page?: ReactElement, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    const render = () =>
        root.render(
            createElement(
                MantineProvider,
                null,
                createElement(
                    QueryClientProvider,
                    { client },
                    // The page header's community switcher confirms through a toast.
                    createElement(ToastProvider, null,
                        createElement(MemoryRouter, null, page ?? createElement(DashboardPage))),
                ),
            ),
        )
    await act(async () => {
        render()
    })
    rerenderDashboard = async () => {
        await act(async () => {
            render()
        })
    }
    await flush()
    cleanups.push(() => {
        act(() => root.unmount())
        client.clear()
        container.remove()
    })
    return container
}

async function flush() {
    await act(async () => {
        const settled = new Promise<void>((resolve) => setTimeout(resolve, 20))
        if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(20)
        await settled
    })
}

function participantSelect(container: HTMLElement) {
    const label = Array.from(container.querySelectorAll('label')).find((label) =>
        label.querySelector('span')?.textContent === 'pages.dashboard.participant',
    )
    const select = label?.querySelector('select')
    expect(select).toBeTruthy()
    return select as HTMLSelectElement
}

function profileHeading(container: HTMLElement) {
    return Array.from(container.querySelectorAll('h3')).find((heading) =>
        heading.textContent?.includes('pages.dashboard.hourlyProfile.title'),
    )
}

function profileNotice(container: HTMLElement, key = 'failed') {
    return Array.from(container.querySelectorAll('[role="alert"]')).find((notice) =>
        notice.textContent?.includes(`pages.dashboard.hourlyProfile.${key}`),
    )
}

async function changeParticipant(container: HTMLElement, id: string) {
    await act(async () => {
        const select = participantSelect(container)
        select.value = id
        select.dispatchEvent(new Event('change', { bubbles: true }))
    })
}

async function previousPeriod(container: HTMLElement) {
    const button = Array.from(container.querySelectorAll('button')).find((button) =>
        button.textContent?.includes('pages.invoices.prevPeriod'),
    )
    expect(button).toBeTruthy()
    await act(async () => button!.click())
}

async function renderProfile(relation: 'participant' | 'manager', client?: QueryClient) {
    mockState.relation = relation
    mockState.summaryCalls = []
    mockState.hourlyCalls = []
    mockState.summary = relation === 'manager'
        ? (args: Record<string, unknown>) => ({
            ...managerSummary(),
            selected_participant_name: args.participantId === 'p1' ? 'Alice' : null,
        })
        : participantSummary('me')
    const container = await renderDashboard(undefined, client)
    if (relation === 'manager') {
        expect(mockState.hourlyCalls).toHaveLength(0)
        await waitForCondition(() => participantSelect(container).querySelector('option[value="p1"]') !== null, 'participant options')
        await changeParticipant(container, 'p1')
        await waitForCondition(() => mockState.hourlyCalls.length === 1, 'selected participant profile request')
    }
    return container
}

describe('dashboard behavior preservation', () => {
    it('sorts the per-participant table by name and numeric consumption', async () => {
        mockState.relation = 'manager'
        mockState.summary = managerSummary()
        const container = await renderDashboard()
        const table = container.querySelector('.participant-table')!
        const names = () => Array.from(table.querySelectorAll('.participant-select')).map(button => button.textContent)
        const sort = async (column: number) => act(async () => table.querySelectorAll('th')[column].querySelector('button')!.click())
        await sort(0)
        await sort(0)
        expect(names()).toEqual(['Bob', 'Alice'])
        await sort(1)
        expect(names()).toEqual(['Alice', 'Bob'])
        await sort(1)
        expect(names()).toEqual(['Bob', 'Alice'])
    })

    it('manager sees the per-participant breakdown table and no metering migration card', async () => {
        mockState.relation = 'manager'
        mockState.summary = managerSummary()
        mockState.summaryCalls = []
        mockState.hourlyProfile = null
        mockState.hourlyCalls = []
        const container = await renderDashboard()
        expect(container.textContent).toContain('pages.dashboard.col.participant')
        expect(container.textContent).toContain('Alice')
        expect(container.textContent).toContain('Bob')
        expect(container.textContent).toContain('pages.dashboard.perParticipant')
        expect(container.textContent).not.toContain('perParticipantMigrated')
        expect(container.querySelector('a[href^="/metering/chart"]')).toBeNull()

        // ZEV-share column: Alice 35/50 = 70%, Bob 20/30 = 66.7%.
        expect(container.textContent).toContain('pages.dashboard.col.fromZevPercent')
        const rows = container.querySelectorAll('tbody tr')
        expect(rows[0].textContent).toContain('70 %')
        expect(rows[1].textContent).toContain('66.7 %')
    })

    it('flagged participant row shows — for the from-ZEV share and the ZEV-wide note appears', async () => {
        mockState.relation = 'manager'
        const base = managerSummary()
        mockState.summary = {
            ...base,
            zev_has_behind_meter_generation: true,
            participant_stats: base.participant_stats.map((participant) => ({
                ...participant,
                has_behind_meter_generation: participant.participant_id === 'p1',
            })),
        }
        mockState.summaryCalls = []
        mockState.hourlyProfile = null
        mockState.hourlyCalls = []
        const container = await renderDashboard()

        const rows = container.querySelectorAll('.participant-table tbody tr')
        expect(rows.length).toBe(2)
        // Alice (p1) is flagged: her from-ZEV share is suppressed, and the badge appears.
        expect(rows[0].textContent).toContain('—')
        expect(rows[0].textContent).toContain('behindMeter.badge')
        // Bob (p2) is unaffected: his real 66.7 % share still shows, no badge.
        expect(rows[1].textContent).toContain('66.7 %')
        expect(rows[1].textContent).not.toContain('behindMeter.badge')

        expect(container.textContent).toContain('behindMeter.zevNote')
    })

    it('manager row click selects the participant and loads the hourly profile', async () => {
        mockState.relation = 'manager'
        mockState.summaryCalls = []
        mockState.summary = ((args: Record<string, unknown>) => {
            const base = managerSummary()
            if (args?.participantId === 'p1') {
                return { ...base, selected_participant_name: 'Alice' }
            }
            return base
        }) as unknown
        mockState.hourlyProfile = null
        mockState.hourlyCalls = []
        const container = await renderDashboard()
        expect(container.textContent).not.toContain('pages.dashboard.hourlyProfile.title')

        mockState.hourlyProfile = [{ hour: 10, from_zev_kwh: 1.5, from_grid_kwh: 0.5 }]
        const rows = container.querySelectorAll('tbody tr')
        expect(rows.length).toBe(2)
        await act(async () => {
            rows[0].dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        await waitForCondition(() => profileHeading(container) !== undefined, 'selected participant profile')

        expect(mockState.hourlyCalls.some((call) => call.participantId === 'p1')).toBe(true)
        expect(mockState.summaryCalls.some((call) => call.participantId === 'p1')).toBe(true)
        expect(container.textContent).toContain('pages.dashboard.hourlyProfile.title')

        // Dropdown reflects the selection.
        expect(participantSelect(container).value).toBe('p1')

        // Selected row is highlighted (re-query after re-render).
        const updatedRows = container.querySelectorAll('tbody tr')
        expect(updatedRows.length).toBe(2)
        expect(updatedRows[0].classList.contains('is-selected')).toBe(true)
        const selectedButton = updatedRows[0].querySelector('button.participant-select')
        expect(selectedButton?.getAttribute('aria-current')).toBe('true')
        expect(updatedRows[1].querySelector('button.participant-select')?.hasAttribute('aria-current')).toBe(false)

        // Hourly heading names the participant.
        const hourlyHeading = Array.from(container.querySelectorAll('h3')).find((h) =>
            h.textContent?.includes('pages.dashboard.hourlyProfile.title'),
        )
        expect(hourlyHeading?.textContent).toContain('Alice')

        // Table shows Alice's actual breakdown values.
        expect(updatedRows[0].textContent).toContain('35 kWh')
        expect(updatedRows[0].textContent).toContain('15 kWh')

        // Community KPIs stay ZEV-wide.
        const kpiRow = container.querySelector('.kpi-row')
        expect(kpiRow?.textContent).toContain('100\u00a0kWh')
        expect(kpiRow?.textContent).toContain('80\u00a0kWh')
        expect(kpiRow?.textContent).toContain('20\u00a0kWh')
        expect(kpiRow?.textContent).toContain('40\u00a0kWh')

        // Balance chart heading is filtered to the participant.
        const balanceHeading = Array.from(container.querySelectorAll('h3')).find((h) =>
            h.textContent?.includes('pages.dashboard.consumptionAndProduction'),
        )
        expect(balanceHeading?.textContent).toContain('Alice')
    })

    it('manager community switch clears the participant filter before requesting', async () => {
        mockState.relation = 'manager'
        mockState.summaryCalls = []
        mockState.summary = managerSummary()
        mockState.hourlyProfile = null
        mockState.hourlyCalls = []
        const container = await renderDashboard()

        await act(async () => {
            container.querySelector('tbody tr')?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        await flush()
        expect(mockState.summaryCalls.some((call) => call.zevId === 'z1' && call.participantId === 'p1')).toBe(true)

        mockState.summary = new Promise(() => {})
        mockState.selectedZevId = 'z2'
        await rerenderDashboard()
        await flush()

        const z2Summaries = mockState.summaryCalls.filter((call) => call.zevId === 'z2')
        expect(z2Summaries.length).toBeGreaterThan(0)
        expect(z2Summaries.every((call) => call.participantId === undefined)).toBe(true)
        expect(mockState.hourlyCalls.some((call) => call.zevId === 'z2')).toBe(false)
        expect(participantSelect(container).value).toBe('')
        expect(participantSelect(container).textContent).not.toContain('Alice')
    })

    it('manager participant buttons and numeric cells select their rows', async () => {
        mockState.relation = 'manager'
        mockState.summaryCalls = []
        mockState.summary = managerSummary()
        mockState.hourlyProfile = null
        mockState.hourlyCalls = []
        const container = await renderDashboard()
        const rows = container.querySelectorAll('.participant-table tbody tr')
        expect(rows.length).toBe(2)
        const button = rows[1].querySelector('button.participant-select') as HTMLButtonElement
        expect(button.tabIndex).toBeGreaterThanOrEqual(0)
        button.focus()
        expect(document.activeElement).toBe(button)
        await act(async () => {
            button.click()
        })
        // jsdom cannot synthesize native Enter/Space button activation; the real browser check covers it.
        await waitForCondition(() => {
            const settledRows = container.querySelectorAll('.participant-table tbody tr')
            return settledRows.length === 2 && settledRows[1].classList.contains('is-selected') &&
                mockState.hourlyCalls.some((call) => call.participantId === 'p2')
        }, 'Bob selection')
        expect(mockState.hourlyCalls.filter((call) => call.participantId === 'p2').length).toBe(1)

        const numericCell = container.querySelector('.participant-table tbody tr:first-child td.numeric')
        await act(async () => {
            numericCell?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        await waitForCondition(() => {
            const settledRows = container.querySelectorAll('.participant-table tbody tr')
            return settledRows.length === 2 && settledRows[0].classList.contains('is-selected') &&
                mockState.hourlyCalls.some((call) => call.participantId === 'p1')
        }, 'Alice selection')
        expect(mockState.hourlyCalls.some((call) => call.participantId === 'p1')).toBe(true)
        expect(container.querySelector('.participant-table tbody tr:first-child')?.classList.contains('is-selected')).toBe(true)
    })

    it('participant energy flow requires current_participant_id', async () => {
        mockState.relation = 'participant'
        mockState.hourlyProfile = null
        mockState.hourlyCalls = []
        mockState.summaryCalls = []

        mockState.summary = participantSummary(null)
        const withoutId = await renderDashboard()
        expect(withoutId.textContent).not.toContain('pages.dashboard.energyFlow.title')

        mockState.summary = participantSummary('me')
        const withId = await renderDashboard()
        expect(withId.textContent).toContain('pages.dashboard.energyFlow.title — Z1')

        // From-ZEV share KPI: 35 of 50 kWh = 70 %.
        expect(withId.textContent).toContain('pages.dashboard.participantStats.fromZevShare')
        expect(withId.textContent).toContain('70\u00a0%')
    })

    it('a participant uses its membership interval and subtitle', async () => {
        vi.useFakeTimers({ toFake: ['Date'] })
        vi.setSystemTime(new Date(2026, 10, 15, 12))
        mockState.relation = 'participant'
        mockState.membershipInterval = 'quarterly'
        mockState.summary = participantSummary('me')
        mockState.summaryCalls = []
        const container = await renderDashboard()
        expect(container.textContent).toContain('pages.zevs.billingIntervals.quarterly')
        expect(container.textContent).toContain('dashboard.participantDescription')
        expect(container.textContent).not.toContain('dashboard.description')
        expect(mockState.summaryCalls[0]).toMatchObject({ dateFrom: '2026-10-01', dateTo: '2026-12-31' })
    })

    it('a manager uses the ZEV record interval and energy balance subtitle', async () => {
        mockState.relation = 'manager'
        mockState.membershipInterval = 'quarterly'
        mockState.summary = managerSummary()
        const container = await renderDashboard()
        expect(container.textContent).toContain('pages.zevs.billingIntervals.monthly')
        expect(container.textContent).toContain('pages.energyBalancePage.description')
    })

    it('waits for a missing participant interval before requesting data', async () => {
        vi.useFakeTimers({ toFake: ['Date'] })
        vi.setSystemTime(new Date(2026, 10, 15, 12))
        mockState.relation = 'participant'
        mockState.membershipInterval = undefined
        mockState.summary = participantSummary('me')
        mockState.summaryCalls = []
        mockState.hourlyCalls = []
        const container = await renderDashboard()
        expect(mockState.summaryCalls).toHaveLength(0)
        expect(mockState.hourlyCalls).toHaveLength(0)
        expect(container.querySelector('.period-selector-trigger')).toBeNull()
        mockState.membershipInterval = 'quarterly'
        await rerenderDashboard()
        await flush()
        expect(mockState.summaryCalls[0]).toMatchObject({ dateFrom: '2026-10-01', dateTo: '2026-12-31' })
        expect(container.textContent).toContain('pages.zevs.billingIntervals.quarterly')
    })

    it.each([
        ['quarterly', '2026-10-01', '2026-12-31'],
        ['semi_annual', '2026-07-01', '2026-12-31'],
        ['annual', '2026-01-01', '2026-12-31'],
    ])('switching a participant to a %s community resets the selected period', async (interval, dateFrom, dateTo) => {
        vi.useFakeTimers({ toFake: ['Date'] })
        vi.setSystemTime(new Date(2026, 10, 15, 12))
        mockState.relation = 'participant'
        mockState.secondMembershipInterval = interval
        mockState.summary = participantSummary('me')
        mockState.summaryCalls = []
        const container = await renderDashboard()
        expect(mockState.summaryCalls[0]).toMatchObject({ zevId: 'z1', dateFrom: '2026-11-01', dateTo: '2026-11-30' })
        const previous = Array.from(container.querySelectorAll('button')).find((button) =>
            button.textContent?.includes('pages.invoices.prevPeriod'),
        )
        expect(previous).toBeDefined()
        await act(async () => previous?.click())
        await flush()
        expect(mockState.summaryCalls.at(-1)).toMatchObject({ dateFrom: '2026-10-01', dateTo: '2026-10-31' })

        mockState.selectedZevId = 'z2'
        await rerenderDashboard()
        await flush()
        expect(container.textContent).toContain(`pages.zevs.billingIntervals.${interval}`)
        expect(container.querySelector('.period-selector-trigger')?.textContent).toContain(`${dateFrom} → ${dateTo}`)
        const requests = mockState.summaryCalls.filter((call) => call.zevId === 'z2')
        expect(requests.length).toBeGreaterThan(0)
        expect(requests.every((call) => call.dateFrom === dateFrom && call.dateTo === dateTo)).toBe(true)
    })

    it.each(['missing', 'empty'])('participant flow falls back to the summary ID with %s membership data', async (membershipState) => {
        mockState.relation = 'participant'
        mockState.hourlyProfile = null
        mockState.membershipsAvailable = membershipState !== 'missing'
        mockState.participantMemberships = []
        const base = participantSummary('me')
        mockState.summary = {
            ...base,
            zev_participant_stats: [
                ...base.zev_participant_stats,
                { participant_id: 'other', participant_name: 'Other', total_consumed_kwh: 30, total_produced_kwh: 0, from_zev_kwh: 20, from_grid_kwh: 10 },
            ],
        }
        const container = await renderDashboard(createElement(ParticipantDashboardBody, {
            interval: 'monthly',
            period: { from: '2026-10-01', to: '2026-10-31' },
            onPeriodChange: vi.fn(),
            periodReady: true,
        }))
        const titles = Array.from(container.querySelectorAll('svg title'), title => title.textContent)
        expect(titles).toContain('Me: 50 kWh')
        expect(titles).toContain('pages.dashboard.energyFlow.others: 30 kWh')
        expect(titles).not.toContain('Other: 30 kWh')
        expect(titles).toContain('pages.dashboard.energyFlow.localConsumption → Me: 35 kWh')
        expect(titles).toContain('pages.dashboard.energyFlow.gridImport → Me: 15 kWh')
    })

    it('participant flow omits a zero-consumption account node and groups consuming records as others', async () => {
        mockState.relation = 'participant'
        mockState.hourlyProfile = null
        const base = participantSummary('me')
        mockState.summary = {
            ...base,
            totals: { consumed_from_zev_kwh: 0, imported_from_grid_kwh: 0, total_consumed_kwh: 0 },
            zev_totals: { produced_kwh: 20, consumed_kwh: 30, imported_kwh: 10, exported_kwh: 0 },
            zev_participant_stats: [
                { ...base.zev_participant_stats[0], total_consumed_kwh: 0, total_produced_kwh: 0, from_zev_kwh: 0, from_grid_kwh: 0 },
                { participant_id: 'other', participant_name: 'Other', total_consumed_kwh: 30, total_produced_kwh: 0, from_zev_kwh: 20, from_grid_kwh: 10 },
            ],
        }
        const container = await renderDashboard()
        const titles = Array.from(container.querySelectorAll('svg title'), title => title.textContent)
        expect(titles).toContain('pages.dashboard.energyFlow.others: 30 kWh')
        expect(titles.some(title => title?.includes('Me'))).toBe(false)
        expect(titles.some(title => title?.includes('pages.dashboard.participantStats.totalConsumption'))).toBe(false)
        expect(titles).toContain('pages.dashboard.energyFlow.localConsumption → pages.dashboard.energyFlow.others: 20 kWh')
        expect(titles).toContain('pages.dashboard.energyFlow.gridImport → pages.dashboard.energyFlow.others: 10 kWh')
    })

    it('participant flow combines all current records and leaves ended records with others', async () => {
        mockState.relation = 'participant'
        mockState.hourlyProfile = null
        mockState.participantMemberships = [
            { id: 'me', valid_from: '2026-01-01', valid_to: null, live: true },
            { id: 'parking', valid_from: '2026-01-01', valid_to: null, live: true },
            { id: 'ended', valid_from: '2026-01-01', valid_to: '2026-01-31', live: false },
        ]
        const base = participantSummary('me')
        mockState.summary = {
            ...base,
            totals: { consumed_from_zev_kwh: 55, imported_from_grid_kwh: 25, total_consumed_kwh: 80 },
            zev_totals: { produced_kwh: 100, consumed_kwh: 130, imported_kwh: 75, exported_kwh: 45 },
            zev_participant_stats: [
                ...base.zev_participant_stats,
                { participant_id: 'parking', participant_name: 'Me', total_consumed_kwh: 30, total_produced_kwh: 0, from_zev_kwh: 20, from_grid_kwh: 10 },
                { participant_id: 'ended', participant_name: 'Former me', total_consumed_kwh: 40, total_produced_kwh: 0, from_zev_kwh: 0, from_grid_kwh: 40 },
                { participant_id: 'other', participant_name: 'Other', total_consumed_kwh: 10, total_produced_kwh: 0, from_zev_kwh: 0, from_grid_kwh: 10 },
            ],
        }
        const container = await renderDashboard()
        const titles = Array.from(container.querySelectorAll('svg title'), title => title.textContent)
        expect(titles).toContain('pages.dashboard.participantStats.totalConsumption: 80 kWh')
        expect(titles).toContain('pages.dashboard.energyFlow.others: 50 kWh')
        expect(titles).not.toContain('Me: 50 kWh')
        expect(titles).toContain('pages.dashboard.energyFlow.localConsumption → pages.dashboard.participantStats.totalConsumption: 55 kWh')
        expect(titles).toContain('pages.dashboard.energyFlow.gridImport → pages.dashboard.participantStats.totalConsumption: 25 kWh')
    })

    it.each(['loading', 'error'] as const)('participant hourly profile remains available while the summary is %s', async (summaryState) => {
        mockState.relation = 'participant'
        mockState.summary = summaryState === 'loading'
            ? new Promise(() => {})
            : () => Promise.reject(new Error('Summary unavailable'))
        mockState.hourlyProfile = [{ hour: 10, from_zev_kwh: 1.5, from_grid_kwh: 0.5 }]
        const container = await renderDashboard()

        await waitForCondition(() => profileHeading(container) !== undefined, 'participant profile')
        if (summaryState === 'error') {
            await waitForCondition(() => container.textContent?.includes('pages.dashboard.failedAnalytics') === true, 'summary error')
        }
        expect(container.textContent).toContain('pages.dashboard.hourlyProfile.title')
        expect(container.textContent).not.toContain('pages.dashboard.participantStats.totalConsumption')
    })

    it('participant profile retry refetches only the profile when both queries fail', async () => {
        mockState.relation = 'participant'
        mockState.summaryCalls = []
        mockState.hourlyCalls = []
        mockState.summary = () => Promise.reject(new Error('Summary unavailable'))
        mockState.hourlyProfile = () => Promise.reject(new Error('Profile unavailable'))
        const container = await renderDashboard()
        await waitForCondition(() => profileNotice(container) !== undefined &&
            container.textContent?.includes('pages.dashboard.failedAnalytics') === true, 'summary and profile errors')
        expect(container.querySelectorAll('[role="alert"]')).toHaveLength(2)
        expect(profileHeading(container)).toBeUndefined()

        const profile = deferred<ProfileData>()
        mockState.hourlyProfile = profile.promise
        const summaryCallsBeforeRetry = mockState.summaryCalls.length
        const retry = profileNotice(container)!.querySelector<HTMLButtonElement>('button')!
        expect(retry.textContent).toContain('common.retry')
        retry.focus()
        await act(async () => retry.click())
        await waitForCondition(() => container.querySelector('[role="status"][aria-label="pages.dashboard.hourlyProfile.loading"]') !== null, 'profile loading feedback')
        const section = container.querySelector('[role="group"][aria-label="pages.dashboard.hourlyProfile.title"]')
        expect(document.activeElement).toBe(section)
        expect(container.querySelector('[role="status"]')?.textContent).toContain('pages.dashboard.hourlyProfile.loading')
        expect(profileNotice(container)).toBeUndefined()
        expect(mockState.hourlyCalls).toHaveLength(2)
        expect(mockState.hourlyCalls[1].participantId).toBeUndefined()

        await act(async () => profile.resolve([{ hour: 10, from_zev_kwh: 1.5, from_grid_kwh: 0.5 }]))
        await waitForCondition(() => profileHeading(container) !== undefined, 'retried profile')
        expect(document.activeElement).toBe(section)
        expect(profileNotice(container)).toBeUndefined()
        expect(container.querySelector('[role="status"][aria-label="pages.dashboard.hourlyProfile.loading"]')).toBeNull()
        expect(container.querySelector('[role="alert"]')?.textContent).toContain('pages.dashboard.failedAnalytics')
        expect(mockState.summaryCalls).toHaveLength(summaryCallsBeforeRetry)
    })

    it.each(['loading', 'error'] as const)('manager profile stays identifiable with an uncached %s summary', async (summaryState) => {
        mockState.hourlyProfile = [{ hour: 10, from_zev_kwh: 1.5, from_grid_kwh: 0.5 }]
        const container = await renderProfile('manager')
        await waitForCondition(() => profileHeading(container) !== undefined, 'initial profile')
        const initialDate = mockState.summaryCalls.at(-1)?.dateFrom
        mockState.summary = summaryState === 'loading'
            ? new Promise(() => {})
            : () => Promise.reject(new Error('Summary unavailable'))
        const profile = deferred<ProfileData>()
        mockState.hourlyProfile = profile.promise
        await previousPeriod(container)
        await waitForCondition(() => mockState.hourlyCalls.length === 2, 'new period profile request')
        expect(mockState.summaryCalls.at(-1)?.dateFrom).not.toBe(initialDate)
        expect(container.querySelector('.participant-table')).toBeNull()
        expect(participantSelect(container).value).toBe('p1')
        expect(participantSelect(container).selectedOptions[0].textContent).toBe('Alice')

        await act(async () => profile.resolve([{ hour: 10, from_zev_kwh: 1.5, from_grid_kwh: 0.5 }]))
        await waitForCondition(() => profileHeading(container) !== undefined, 'new period profile')
        if (summaryState === 'error') {
            await waitForCondition(() => container.textContent?.includes('pages.dashboard.failedAnalytics') === true, 'new period summary error')
        }
        expect(profileHeading(container)?.textContent).toContain('Alice')
        expect(mockState.hourlyCalls.at(-1)?.participantId).toBe('p1')
        expect(container.querySelectorAll('[role="alert"]')).toHaveLength(summaryState === 'error' ? 1 : 0)
        await changeParticipant(container, '')
        expect(profileHeading(container)).toBeUndefined()
        expect(participantSelect(container).value).toBe('')
        expect(mockState.hourlyCalls).toHaveLength(2)
        expect(mockState.summaryCalls.at(-1)?.participantId).toBeUndefined()
    })

    it('manager profile retry refetches only the selected profile when both queries fail', async () => {
        mockState.hourlyProfile = [{ hour: 10, from_zev_kwh: 1.5, from_grid_kwh: 0.5 }]
        const container = await renderProfile('manager')
        await waitForCondition(() => profileHeading(container) !== undefined, 'initial profile')
        mockState.summary = () => Promise.reject(new Error('Summary unavailable'))
        mockState.hourlyProfile = () => Promise.reject(new Error('Profile unavailable'))
        await previousPeriod(container)
        await waitForCondition(() => container.querySelectorAll('[role="alert"]').length === 2, 'summary and profile errors')
        const summaryCallsBeforeRetry = mockState.summaryCalls.length
        const profile = deferred<ProfileData>()
        mockState.hourlyProfile = profile.promise
        const retry = profileNotice(container)!.querySelector<HTMLButtonElement>('button')!
        retry.focus()
        await act(async () => retry.click())
        await waitForCondition(() => container.querySelector('[role="status"][aria-label="pages.dashboard.hourlyProfile.loading"]') !== null, 'selected profile loading feedback')
        const section = container.querySelector('[role="group"][aria-label="pages.dashboard.hourlyProfile.title"]')
        expect(document.activeElement).toBe(section)
        expect(container.querySelector('[role="status"]')?.textContent).toContain('pages.dashboard.hourlyProfile.loading')
        await act(async () => profile.resolve([{ hour: 10, from_zev_kwh: 1.5, from_grid_kwh: 0.5 }]))
        await waitForCondition(() => profileHeading(container) !== undefined, 'retried selected profile')
        expect(document.activeElement).toBe(section)
        expect(profileHeading(container)?.textContent).toContain('Alice')
        expect(profileNotice(container)).toBeUndefined()
        expect(mockState.hourlyCalls.at(-1)?.participantId).toBe('p1')
        expect(mockState.summaryCalls).toHaveLength(summaryCallsBeforeRetry)
        expect(container.querySelector('[role="alert"]')?.textContent).toContain('pages.dashboard.failedAnalytics')
    })

    it.each(['participant', 'manager'] as const)('%s profile stays visible after a failed refresh', async (relation) => {
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        mockState.hourlyProfile = [{ hour: 10, from_zev_kwh: 1.5, from_grid_kwh: 0.5 }]
        const container = await renderProfile(relation, client)
        await waitForCondition(() => profileHeading(container) !== undefined, 'initial profile')
        const summaryCallsBeforeRefresh = mockState.summaryCalls.length
        mockState.hourlyProfile = () => Promise.reject(new Error('Profile unavailable'))
        await act(async () => { await client.invalidateQueries({ queryKey: ['metering', 'hourly-profile'] }) })
        await waitForCondition(() => profileNotice(container, 'refreshFailed') !== undefined, 'profile refresh error')
        expect(profileHeading(container)).toBeDefined()
        expect(vi.mocked(HourlyProfileCard).mock.lastCall?.[0].data).toEqual([
            { hour: 10, from_zev_kwh: 1.5, from_grid_kwh: 0.5, label: '10:00' },
        ])
        expect(profileNotice(container)).toBeUndefined()

        const profile = deferred<ProfileData>()
        mockState.hourlyProfile = profile.promise
        await act(async () => profileNotice(container, 'refreshFailed')!.querySelector<HTMLButtonElement>('button')!.click())
        await waitForCondition(() => profileNotice(container, 'refreshFailed')?.querySelector('button')?.disabled === true, 'busy profile retry')
        expect(profileHeading(container)).toBeDefined()
        expect(profileNotice(container, 'refreshFailed')?.textContent).toContain('common.loading')
        expect(profileNotice(container, 'refreshFailed')?.querySelector('button')?.getAttribute('aria-busy')).toBe('true')
        await act(async () => profile.resolve([{ hour: 11, from_zev_kwh: 2, from_grid_kwh: 1 }]))
        await waitForCondition(() => profileNotice(container, 'refreshFailed') === undefined, 'successful profile retry')
        expect(profileHeading(container)).toBeDefined()
        expect(vi.mocked(HourlyProfileCard).mock.lastCall?.[0].data).toEqual([
            { hour: 11, from_zev_kwh: 2, from_grid_kwh: 1, label: '11:00' },
        ])
        expect(mockState.hourlyCalls).toHaveLength(3)
        expect(mockState.summaryCalls).toHaveLength(summaryCallsBeforeRefresh)
    })

    it.each<{ relation: 'participant' | 'manager'; case: string; profile: ProfileData }>([
        { relation: 'participant', case: 'null', profile: null },
        { relation: 'participant', case: 'empty', profile: [] },
        { relation: 'manager', case: 'null', profile: null },
        { relation: 'manager', case: 'empty', profile: [] },
    ])('$relation hides a successful $case profile', async ({ relation, profile }) => {
        mockState.hourlyProfile = profile
        const container = await renderProfile(relation)
        await waitForCondition(() => container.querySelector('[role="status"][aria-label="pages.dashboard.hourlyProfile.loading"]') === null, 'empty profile response')
        expect(mockState.hourlyCalls).toHaveLength(1)
        expect(profileHeading(container)).toBeUndefined()
        expect(profileNotice(container)).toBeUndefined()
        expect(profileNotice(container, 'refreshFailed')).toBeUndefined()
    })
})


describe('manager dashboard: the manager as a participant', () => {
    const gross = (rate: number) => ({
        source_provider: 'solar_manager', covered_from: '2026-07-01T00:00:00Z', covered_to: '2026-07-04T00:00:00Z', coverage_pct: 100,
        production_kwh: 100, consumption_kwh: 50, import_kwh: 20, export_kwh: 60, self_consumption_kwh: 30,
        self_consumption_rate: 30, self_sufficiency_rate: rate, rates_withheld_reason: null, timeline: [],
    })
    const withOwnBlock = (own: unknown, extra: Record<string, unknown> = {}) => ({ ...managerSummary(), own_gross_energy: own, selected_gross_energy: null, ...extra })
    const cards = (container: Element) => container.querySelectorAll('section[aria-labelledby]').length
    // Selecting starts a new query: settle it before looking at the page again.
    const click = async (element: Element) => {
        await act(async () => { element.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
        await flush()
        await flush()
    }

    function asManagerAndParticipant(participantId: string) {
        mockState.relation = 'manager'
        mockState.participantMemberships = [{ id: participantId, valid_from: '2026-01-01', valid_to: null, live: true }]
    }

    it('marks the manager\'s own row in the table and the dropdown', async () => {
        asManagerAndParticipant('p2')
        mockState.summary = managerSummary()
        const container = await renderDashboard()

        const rows = container.querySelectorAll('tbody tr')
        expect(rows[0].textContent).not.toContain('pages.dashboard.youBadge')
        expect(rows[1].textContent).toContain('pages.dashboard.youBadge')
        const options = Array.from(container.querySelectorAll('select option')).map((option) => option.textContent)
        expect(options.some((text) => text?.includes('Bob') && text.includes('pages.dashboard.youBadge'))).toBe(true)
        expect(options.some((text) => text?.includes('Alice') && text.includes('pages.dashboard.youBadge'))).toBe(false)

        mockState.summary = new Promise(() => {})
        await changeParticipant(container, 'p2')
        await flush()
        const selectedOption = participantSelect(container).selectedOptions[0]
        expect(selectedOption.value).toBe('p2')
        expect(selectedOption.textContent).toContain('Bob')
        expect(selectedOption.textContent).toContain('pages.dashboard.youBadge')
        expect(participantSelect(container).textContent).not.toContain('Alice')
    })

    const note = (container: Element) => container.querySelector('p.muted a[href^="/my-energy"]')
    const noteText = (container: Element) => note(container)?.parentElement?.textContent ?? ''

    it('points a manager to My energy system where their own figures used to be, never showing the card itself', async () => {
        asManagerAndParticipant('p2')
        mockState.summary = ((args: Record<string, unknown>) =>
            withOwnBlock(gross(61), args?.participantId ? { selected_participant_name: 'x', selected_gross_energy: gross(args.participantId === 'p2' ? 61 : 40) } : {})) as unknown
        const container = await renderDashboard()

        // Nobody selected: the own note, with the period but no participant.
        expect(noteText(container)).toContain('myEnergy.balanceNote')
        expect(noteText(container)).not.toContain('balanceNoteParticipant')
        expect(note(container)?.getAttribute('href')).toMatch(/^\/my-energy\?range=period/)
        expect(note(container)?.getAttribute('href')).not.toContain('participant=')
        expect(cards(container)).toBe(0)
        expect(container.textContent).not.toContain('supplementary.gross.titleOwn')

        // Somebody else: the participant's note names them in the link, and no own note.
        await click(container.querySelectorAll('tbody tr')[0]) // Alice
        expect(container.querySelectorAll('a[href^="/my-energy"]')).toHaveLength(1)
        expect(noteText(container)).toContain('myEnergy.balanceNoteParticipant')
        expect(note(container)?.getAttribute('href')).toContain('participant=')

        // Themselves: the own note, once.
        await click(container.querySelectorAll('tbody tr')[1]) // Bob, the manager
        expect(container.querySelectorAll('a[href^="/my-energy"]')).toHaveLength(1)
        expect(noteText(container)).toContain('myEnergy.balanceNote')
        expect(noteText(container)).not.toContain('balanceNoteParticipant')
        expect(note(container)?.getAttribute('href')).not.toContain('participant=')

        // Cleared again: back to the own note.
        await click(container.querySelectorAll('tbody tr')[1])
        expect(noteText(container)).toContain('myEnergy.balanceNote')
    })

    it('shows the note, not the call to action, to a manager with an unconnected net-metered meter, unless they look at someone else', async () => {
        asManagerAndParticipant('p2')
        eligibility.eligible = [{ metering_point: 'mp', meter_id: 'M', zev: 'z1', zev_name: 'Z1', participant: 'p2', source: null }]
        mockState.summary = withOwnBlock(null)
        const container = await renderDashboard()

        expect(container.textContent).not.toContain('supplementary.gross.ctaTitle')
        expect(note(container)).not.toBeNull()

        await click(container.querySelectorAll('tbody tr')[0]) // Alice: nothing to say about her
        expect(note(container)).toBeNull()
        await click(container.querySelectorAll('tbody tr')[1]) // Bob, the manager
        expect(note(container)).not.toBeNull()
    })

    it('shows no note for a manager who has no own energy data and no meter to connect', async () => {
        asManagerAndParticipant('p2')
        mockState.summary = withOwnBlock(null)
        const container = await renderDashboard()

        expect(cards(container)).toBe(0)
        expect(note(container)).toBeNull()
        expect(container.textContent).not.toContain('supplementary.gross.ctaTitle')
    })

    it('does not offer to connect a meter of another community', async () => {
        asManagerAndParticipant('p2')
        eligibility.eligible = [{ metering_point: 'mp', meter_id: 'M', zev: 'z2', zev_name: 'Z2', participant: 'p9', source: null }]
        mockState.summary = withOwnBlock(null)
        const container = await renderDashboard()

        expect(container.textContent).not.toContain('supplementary.gross.ctaTitle')
    })

    it('clicking the selected row again clears the selection, and so does its name button', async () => {
        asManagerAndParticipant('p2')
        mockState.summaryCalls = []
        mockState.summary = managerSummary()
        const container = await renderDashboard()

        await click(container.querySelectorAll('tbody tr')[0])
        expect(container.querySelectorAll('tbody tr')[0].classList.contains('is-selected')).toBe(true)
        expect((container.querySelector('select') as HTMLSelectElement).value).toBe('p1')

        await click(container.querySelectorAll('tbody tr')[0])
        expect(container.querySelectorAll('tbody tr')[0].classList.contains('is-selected')).toBe(false)
        expect((container.querySelector('select') as HTMLSelectElement).value).toBe('')
        expect(mockState.summaryCalls.at(-1)?.participantId).toBeUndefined()

        // Select again and clear through the name button inside the row.
        await click(container.querySelectorAll('tbody tr')[0].querySelector('button.participant-select')!)
        expect(container.querySelectorAll('tbody tr')[0].classList.contains('is-selected')).toBe(true)
        await click(container.querySelectorAll('tbody tr')[0].querySelector('button.participant-select')!)
        expect(container.querySelectorAll('tbody tr')[0].classList.contains('is-selected')).toBe(false)
    })

    it('exposes the selection state of a row to assistive technology', async () => {
        asManagerAndParticipant('p2')
        mockState.summary = managerSummary()
        const container = await renderDashboard()

        const button = () => container.querySelectorAll('tbody tr')[0].querySelector('button.participant-select')!
        expect(button().getAttribute('aria-pressed')).toBe('false')
        await click(button())
        expect(button().getAttribute('aria-pressed')).toBe('true')
    })
})
