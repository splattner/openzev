import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, type ReactElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { MembershipParticipant } from '../src/types/api'

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
    hourlyProfile: null as unknown,
    hourlyCalls: [] as Array<Record<string, unknown>>,
    invoices: [] as Invoice[],
    invoiceCalls: [] as Array<unknown>,
    invoiceError: null as Error | null,
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
            tabAvailable: eligibility.eligible.length > 0,
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
        return Promise.resolve({ hourly_profile: mockState.hourlyProfile })
    },
}))

vi.mock('../src/lib/api/invoices', () => ({
    fetchInvoices: (...args: unknown[]) => {
        mockState.invoiceCalls.push(args)
        if (mockState.invoiceError) return Promise.reject(mockState.invoiceError)
        return Promise.resolve(mockState.invoices)
    },
    openInvoicePdf: vi.fn(),
}))

import { DashboardPage } from '../src/pages/DashboardPage'
import { ParticipantDashboardBody } from '../src/features/dashboard/ParticipantDashboardBody'
import { ParticipantInvoicesCard } from '../src/components/dashboard/ParticipantInvoicesCard'
import { openInvoicePdf } from '../src/lib/api/invoices'
import type { Invoice } from '../src/types/api'

const cleanups: Array<() => void> = []
afterEach(() => {
    cleanups.splice(0).forEach((cleanup) => cleanup())
    mockState.selectedZevId = 'z1'
    vi.clearAllMocks()
    vi.useRealTimers()
    mockState.membershipInterval = 'monthly'
    mockState.secondMembershipInterval = null
    mockState.secondMembershipSelectable = true
    mockState.invoiceError = null
    mockState.invoiceCalls = []
    mockState.participantMemberships = [{ id: 'me', valid_from: '2026-01-01', valid_to: null, live: true }]
    mockState.membershipsAvailable = true
    eligibility.eligible = []
})

function makeInvoice(overrides: Partial<Invoice> = {}): Invoice {
    return {
        id: '3', invoice_number: 'INV-3', zev: 'z1', zev_name: 'Z1',
        participant: 'me', participant_name: 'Me', status: 'sent',
        period_start: '2026-01-01', period_end: '2026-01-31', total_chf: '75.00',
        pdf_url: null, pdf_status: 'none', ...overrides,
    }
}

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

async function renderDashboard(page?: ReactElement) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
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
                    createElement(MemoryRouter, null, page ?? createElement(DashboardPage)),
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

describe('dashboard behavior preservation', () => {
    it('manager sees the per-participant breakdown table and no metering migration card', async () => {
        mockState.relation = 'manager'
        mockState.summary = managerSummary()
        mockState.summaryCalls = []
        mockState.invoiceCalls = []
        mockState.hourlyProfile = null
        mockState.hourlyCalls = []
        mockState.invoices = []
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
        mockState.invoiceCalls = []
        mockState.hourlyProfile = null
        mockState.hourlyCalls = []
        mockState.invoices = []
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
        mockState.invoices = []
        const container = await renderDashboard()
        expect(container.textContent).not.toContain('pages.dashboard.hourlyProfile.title')

        mockState.hourlyProfile = [{ hour: 10, from_zev_kwh: 1.5, from_grid_kwh: 0.5 }]
        const rows = container.querySelectorAll('tbody tr')
        expect(rows.length).toBe(2)
        await act(async () => {
            rows[0].dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        for (let i = 0; i < 15 && !container.textContent?.includes('pages.dashboard.hourlyProfile.title'); i++) {
            await flush()
        }

        expect(mockState.hourlyCalls.some((call) => call.participantId === 'p1')).toBe(true)
        expect(mockState.summaryCalls.some((call) => call.participantId === 'p1')).toBe(true)
        expect(container.textContent).toContain('pages.dashboard.hourlyProfile.title')

        // Dropdown reflects the selection.
        const selects = container.querySelectorAll('select')
        expect(selects.length).toBeGreaterThan(0)
        expect((selects[0] as HTMLSelectElement).value).toBe('p1')

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
        expect(kpiRow?.textContent).toContain('100 kWh')
        expect(kpiRow?.textContent).toContain('80 kWh')
        expect(kpiRow?.textContent).toContain('20 kWh')
        expect(kpiRow?.textContent).toContain('40 kWh')

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
        mockState.invoices = []
        const container = await renderDashboard()

        await act(async () => {
            container.querySelector('tbody tr')?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        await flush()
        expect(mockState.summaryCalls.some((call) => call.zevId === 'z1' && call.participantId === 'p1')).toBe(true)

        mockState.selectedZevId = 'z2'
        await rerenderDashboard()
        await flush()

        const z2Summaries = mockState.summaryCalls.filter((call) => call.zevId === 'z2')
        expect(z2Summaries.length).toBeGreaterThan(0)
        expect(z2Summaries.every((call) => call.participantId === undefined)).toBe(true)
        expect(mockState.hourlyCalls.some((call) => call.zevId === 'z2')).toBe(false)
        expect((container.querySelector('select') as HTMLSelectElement).value).toBe('')
    })

    it('manager participant buttons and numeric cells select their rows', async () => {
        mockState.relation = 'manager'
        mockState.summaryCalls = []
        mockState.summary = managerSummary()
        mockState.hourlyProfile = null
        mockState.hourlyCalls = []
        mockState.invoices = []
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
        for (let i = 0; i < 20; i++) {
            await flush()
            const settledRows = container.querySelectorAll('.participant-table tbody tr')
            const profileLoaded = mockState.hourlyCalls.some((call) => call.participantId === 'p2')
            if (settledRows.length === 2 && settledRows[1].classList.contains('is-selected') && profileLoaded) break
        }
        expect(mockState.hourlyCalls.filter((call) => call.participantId === 'p2').length).toBe(1)

        const numericCell = container.querySelector('.participant-table tbody tr:first-child td.numeric')
        await act(async () => {
            numericCell?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        for (let i = 0; i < 20; i++) {
            await flush()
            const settledRows = container.querySelectorAll('.participant-table tbody tr')
            const profileLoaded = mockState.hourlyCalls.some((call) => call.participantId === 'p1')
            if (settledRows.length === 2 && settledRows[0].classList.contains('is-selected') && profileLoaded) break
        }
        expect(mockState.hourlyCalls.some((call) => call.participantId === 'p1')).toBe(true)
        expect(container.querySelector('.participant-table tbody tr:first-child')?.classList.contains('is-selected')).toBe(true)
    })

    it('participant energy flow requires current_participant_id', async () => {
        mockState.relation = 'participant'
        mockState.hourlyProfile = null
        mockState.hourlyCalls = []
        mockState.summaryCalls = []
        mockState.invoiceCalls = []
        mockState.invoices = []

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
        mockState.invoices = []
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
        mockState.invoices = []
        const container = await renderDashboard()
        expect(container.textContent).toContain('pages.zevs.billingIntervals.monthly')
        expect(container.textContent).toContain('pages.energyBalancePage.description')
    })

    it('waits for a missing participant interval while still showing invoices', async () => {
        vi.useFakeTimers({ toFake: ['Date'] })
        vi.setSystemTime(new Date(2026, 10, 15, 12))
        mockState.relation = 'participant'
        mockState.membershipInterval = undefined
        mockState.summary = participantSummary('me')
        mockState.summaryCalls = []
        mockState.hourlyCalls = []
        mockState.invoices = [makeInvoice()]
        const container = await renderDashboard()
        expect(mockState.summaryCalls).toHaveLength(0)
        expect(mockState.hourlyCalls).toHaveLength(0)
        expect(container.querySelector('.period-selector-trigger')).toBeNull()
        expect(container.textContent).toContain('INV-3')
        mockState.membershipInterval = 'quarterly'
        await rerenderDashboard()
        await flush()
        expect(mockState.summaryCalls[0]).toMatchObject({ dateFrom: '2026-10-01', dateTo: '2026-12-31' })
        expect(container.textContent).toContain('pages.zevs.billingIntervals.quarterly')
    })

    it('shows community names for invoices from a membership absent from the switcher', async () => {
        mockState.relation = 'participant'
        mockState.secondMembershipInterval = 'monthly'
        mockState.secondMembershipSelectable = false
        mockState.summary = participantSummary('me')
        mockState.invoices = [makeInvoice(), makeInvoice({ id: '8', participant: 'me-z2', zev: 'z2', zev_name: 'Z2' })]
        const container = await renderDashboard()
        expect(container.textContent).toContain('pages.dashboard.invoicesAllCommunitiesSection')
        expect(container.querySelector('thead')?.textContent).toContain('pages.dashboard.invoiceCol.community')
        expect(container.querySelector('tbody')?.textContent).toContain('Z2')
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
        mockState.invoices = []
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

    it.each(['ready', 'failed'] as const)('polls a pending personal PDF after 15 seconds and stops when %s', async (status) => {
        vi.useFakeTimers()
        mockState.relation = 'participant'
        mockState.summary = participantSummary('me')
        mockState.invoices = [makeInvoice({ pdf_status: 'pending' })]
        const container = await renderDashboard()
        expect(mockState.invoiceCalls).toHaveLength(1)
        expect(container.textContent).toContain('pages.invoices.pdfGenerating')
        mockState.invoices = [makeInvoice({ pdf_status: status, pdf_url: status === 'ready' ? '/new.pdf' : null })]
        await act(async () => { await vi.advanceTimersByTimeAsync(14900) })
        expect(mockState.invoiceCalls).toHaveLength(1)
        await act(async () => { await vi.advanceTimersByTimeAsync(100) })
        await flush()
        expect(mockState.invoiceCalls).toHaveLength(2)
        expect(container.textContent).not.toContain('pages.invoices.pdfGenerating')
        if (status === 'ready') {
            const button = container.querySelector<HTMLButtonElement>('tbody button')
            expect(button?.textContent).toContain('common.openPdf')
            await act(async () => button?.click())
            expect(openInvoicePdf).toHaveBeenCalledWith('3')
        } else expect(container.textContent).toContain('pages.invoices.pdfFailed')
        await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
        expect(mockState.invoiceCalls).toHaveLength(2)
    })

    it.each([
        { participant: 'other', status: 'sent' },
        { participant: 'me', status: 'draft' },
    ])('does not poll a hidden pending invoice ($participant, $status)', async (overrides) => {
        vi.useFakeTimers()
        mockState.relation = 'participant'
        mockState.summary = participantSummary('me')
        mockState.invoices = [makeInvoice({ ...overrides, pdf_status: 'pending' })]
        const container = await renderDashboard()
        expect(container.textContent).not.toContain('INV-3')
        await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
        expect(mockState.invoiceCalls).toHaveLength(1)
    })

    it('keeps an existing PDF usable while polling a replacement', async () => {
        vi.useFakeTimers()
        mockState.relation = 'participant'
        mockState.summary = participantSummary('me')
        mockState.invoices = [makeInvoice({ pdf_url: '/existing.pdf', pdf_status: 'pending' })]
        const container = await renderDashboard()
        const button = container.querySelector<HTMLButtonElement>('tbody button')
        expect(button?.textContent).toContain('common.openPdf')
        await act(async () => button?.click())
        expect(openInvoicePdf).toHaveBeenCalledWith('3')
        await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
        expect(mockState.invoiceCalls).toHaveLength(2)
        expect(container.querySelector('tbody button')?.textContent).toContain('common.openPdf')
    })

    it('keeps cached invoices after a failed query refetch and retries successfully', async () => {
        vi.useFakeTimers()
        mockState.relation = 'participant'
        mockState.summary = participantSummary('me')
        mockState.invoices = [makeInvoice({ pdf_status: 'pending' })]
        const container = await renderDashboard()
        mockState.invoiceError = new Error('invoices down')
        await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
        await flush()
        expect(mockState.invoiceCalls).toHaveLength(2)
        expect(container.querySelector('tbody')?.textContent).toContain('INV-3')
        expect(container.querySelector('.warning-banner')?.textContent).toContain('pages.dashboard.failedInvoices')
        mockState.invoiceError = null
        mockState.invoices = [makeInvoice({ pdf_status: 'ready', pdf_url: '/new.pdf' })]
        await act(async () => container.querySelector<HTMLButtonElement>('.warning-banner button')?.click())
        await flush()
        expect(container.querySelector('.warning-banner')).toBeNull()
        expect(container.querySelector('tbody button')?.textContent).toContain('common.openPdf')
        await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
        expect(mockState.invoiceCalls).toHaveLength(3)
    })

    it.each(['missing', 'empty'])('participant flow falls back to the summary ID with %s membership data', async (membershipState) => {
        mockState.relation = 'participant'
        mockState.hourlyProfile = null
        mockState.invoices = []
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
        mockState.invoices = []
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
        mockState.invoices = []
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

    it('participant invoices list sent/paid rows with details actions, with or without a PDF', async () => {
        mockState.relation = 'participant'
        mockState.hourlyProfile = null
        mockState.hourlyCalls = []
        mockState.summaryCalls = []
        mockState.invoiceCalls = []
        mockState.invoices = [
            makeInvoice({ id: '1', invoice_number: 'INV-1', status: 'approved', pdf_url: 'http://x/1', pdf_status: 'ready', total_chf: '100.00' }),
            makeInvoice({ id: '2', invoice_number: 'INV-2', status: 'draft', pdf_url: 'http://x/2', pdf_status: 'ready', total_chf: '50.00' }),
            makeInvoice({ pdf_url: 'http://x/3', pdf_status: 'ready' }),
            makeInvoice({ id: '4', invoice_number: 'INV-4', status: 'paid', total_chf: '20.00' }),
            makeInvoice({ id: '5', invoice_number: 'INV-5', status: 'paid', pdf_url: 'http://x/5', pdf_status: 'ready', total_chf: '30.00' }),
            // Sent, then cancelled: still listed, as on "My invoices".
            makeInvoice({ id: '6', invoice_number: 'INV-6', status: 'cancelled', sent_at: '2026-02-01T08:00:00Z', total_chf: '10.00' }),
            // Another participant's invoice.
            makeInvoice({ id: '7', invoice_number: 'INV-7', participant: 'other', pdf_url: 'http://x/7', pdf_status: 'ready', total_chf: '40.00' }),
        ]
        // Defer the summary so the test proves invoices start loading independently.
        let resolveSummary!: (value: unknown) => void
        mockState.summary = new Promise((resolve) => {
            resolveSummary = resolve
        }) as unknown
        const container = await renderDashboard()
        expect(mockState.invoiceCalls.length).toBeGreaterThan(0)
        await act(async () => {
            resolveSummary(participantSummary('me'))
        })
        for (let i = 0; i < 15 && !container.textContent?.includes('INV-5'); i++) {
            await flush()
        }
        expect(container.textContent).not.toContain('INV-1')
        expect(container.textContent).toContain('INV-3')
        expect(container.textContent).toContain('INV-5')
        expect(container.textContent).not.toContain('INV-2')
        expect(container.textContent).toContain('INV-6')
        expect(container.textContent).not.toContain('INV-7')
        // A missing PDF does not hide the invoice; the row says the PDF is missing.
        const unrenderedRow = Array.from(container.querySelectorAll('tbody tr')).find((row) =>
            row.textContent?.includes('INV-4'),
        )
        expect(unrenderedRow?.textContent).toContain('pages.invoices.pdfMissing')
        expect(unrenderedRow?.querySelector('button')).toBeNull()
        expect(container.querySelector('a[href="/billing/invoices/3"]')).not.toBeNull()
        expect(container.querySelector('a[href="/billing/invoices/5"]')).not.toBeNull()

        const paidRow = Array.from(container.querySelectorAll('tbody tr')).find((row) =>
            row.textContent?.includes('INV-5'),
        )
        expect(paidRow).not.toBeUndefined()
        const pdfButton = paidRow?.querySelector('button')
        expect(pdfButton).not.toBeNull()
        await act(async () => {
            pdfButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        expect(openInvoicePdf).toHaveBeenCalledWith('5')
    })

    it('participant invoices show even when the analytics request fails', async () => {
        mockState.relation = 'participant'
        mockState.summary = () => {
            throw new Error('analytics down')
        }
        mockState.invoices = [
            makeInvoice({ pdf_url: 'http://x/3', pdf_status: 'ready' }),
        ]
        const container = await renderDashboard()
        await flush()
        expect(container.textContent).toContain('pages.dashboard.failedAnalytics')
        expect(container.textContent).toContain('INV-3')
    })

    it('shows an error with retry when invoices have never loaded', async () => {
        const onRetry = vi.fn()
        const empty = await renderDashboard(createElement(ParticipantInvoicesCard, {
            invoices: undefined,
            isError: true,
            isRetrying: false,
            onRetry,
            showCommunity: false,
        }))
        expect(empty.querySelector('.error-banner')?.textContent).toContain('pages.dashboard.failedInvoices')
        expect(empty.querySelector('table')).toBeNull()
        empty.querySelector<HTMLButtonElement>('.error-banner button')?.click()
        expect(onRetry).toHaveBeenCalledOnce()
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
        mockState.invoices = []
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
    })

    it('shows the manager\'s own figures when nobody is selected and when they select themselves, not for someone else', async () => {
        asManagerAndParticipant('p2')
        mockState.summary = ((args: Record<string, unknown>) =>
            withOwnBlock(gross(61), args?.participantId ? { selected_participant_name: 'x', selected_gross_energy: gross(args.participantId === 'p2' ? 61 : 40) } : {})) as unknown
        const container = await renderDashboard()

        // Nobody selected: the own block, and nothing else of this kind.
        expect(container.textContent).toContain('supplementary.gross.titleOwn')
        expect(container.textContent).toContain('61')
        expect(cards(container)).toBe(1)

        // Somebody else: only that participant's card, and no own block.
        await click(container.querySelectorAll('tbody tr')[0]) // Alice
        expect(cards(container)).toBe(1)
        expect(container.textContent).toContain('supplementary.gross.titleParticipant')
        expect(container.textContent).not.toContain('supplementary.gross.titleOwn')

        // Themselves: the own block, once.
        await click(container.querySelectorAll('tbody tr')[1]) // Bob, the manager
        expect(cards(container)).toBe(1)
        expect(container.textContent).toContain('supplementary.gross.titleOwn')
        expect(container.textContent).not.toContain('supplementary.gross.titleParticipant')

        // Cleared again: back to the own block.
        await click(container.querySelectorAll('tbody tr')[1])
        expect(container.textContent).toContain('supplementary.gross.titleOwn')
        expect(cards(container)).toBe(1)
    })

    it('gives the call to action to a manager with an unconnected net-metered meter, unless they look at someone else', async () => {
        asManagerAndParticipant('p2')
        eligibility.eligible = [{ metering_point: 'mp', meter_id: 'M', zev: 'z1', zev_name: 'Z1', participant: 'p2', source: null }]
        mockState.summary = withOwnBlock(null)
        const container = await renderDashboard()

        expect(container.textContent).toContain('supplementary.gross.ctaTitle')
        expect(container.querySelector('a[href="/account?tab=energy-data"]')).not.toBeNull()

        await click(container.querySelectorAll('tbody tr')[0]) // Alice
        expect(container.textContent).not.toContain('supplementary.gross.ctaTitle')
        await click(container.querySelectorAll('tbody tr')[1]) // Bob, the manager
        expect(container.textContent).toContain('supplementary.gross.ctaTitle')
    })

    it('shows neither block for a manager who has no own energy data and no meter to connect', async () => {
        asManagerAndParticipant('p2')
        mockState.summary = withOwnBlock(null)
        const container = await renderDashboard()

        expect(cards(container)).toBe(0)
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
