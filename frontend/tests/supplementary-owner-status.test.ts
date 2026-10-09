import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SupplementarySourceStatus } from '../src/features/meteringPoints/SupplementarySourceStatus'
import { ParticipantTableCard } from '../src/components/dashboard/ParticipantTableCard'
import type { GrossEnergy, MeteringPoint, SupplementarySource, ZevOwnerDashboardSummary } from '../src/types/api'
import { renderWithProviders } from './helpers/render'
import { waitForCondition } from './helpers/waitForCondition'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options ? `${key}${JSON.stringify(options)}` : key) }),
}))
const pushToast = vi.fn()
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return { ...actual, useAppSettings: () => ({ settings: actual.DEFAULT_APP_SETTINGS, isLoading: false }) }
})
const api = vi.hoisted(() => ({
    listSupplementarySources: vi.fn(),
    updateSupplementarySource: vi.fn(),
    purgeSupplementaryReadings: vi.fn(),
    deleteSupplementarySource: vi.fn(),
}))
vi.mock('../src/lib/api/supplementary', () => api)

const point = (status: MeteringPoint['supplementary_source_status']): MeteringPoint => ({
    id: 'mp-1', zev: 'zev-1', meter_id: 'CH-100', meter_type: 'bidirectional', is_active: true, building: 'b-1', building_name: 'Haus',
    has_behind_meter_generation: true, reading_count: 0, assignment_count: 1, first_reading_at: null, last_reading_at: null,
    supplementary_source_status: status,
})

const source: SupplementarySource = {
    id: 'src-1', metering_point: 'mp-1', metering_point_meter_id: 'CH-100', participant: 'p-1', participant_name: 'Pia Muster',
    provider: 'solar_manager', label: '', external_id: 'ABC123', enabled: true, status: 'ok', consented_at: '2026-07-01T00:00:00Z',
    last_sync_at: null, last_success_at: '2026-07-03T10:00:00Z', last_error: '', synced_through: '2026-07-03T10:00:00Z',
    covers_from: '2026-07-01T00:00:00Z', reconciliation: { state: 'warn', days_compared: 7, export_deviation_pct: 14.2, import_deviation_pct: 2, best_shift_intervals: 1 },
    has_credential: true, push_token_prefix: null, created_at: '2026-07-01T00:00:00Z', updated_at: '2026-07-03T10:00:00Z',
}

const cleanups: Array<() => void> = []
const confirm = vi.fn()
beforeEach(() => {
    vi.clearAllMocks()
    api.listSupplementarySources.mockResolvedValue([source])
})
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

const buttonWith = (root: ParentNode, label: string) =>
    Array.from(root.querySelectorAll<HTMLButtonElement>('button')).find((b) => b.textContent?.includes(label))!
const dialog = () => document.querySelector<HTMLElement>('[role="dialog"]')

async function openPanel(canManage: boolean, status: MeteringPoint['supplementary_source_status'] = 'ok') {
    const view = await renderWithProviders(createElement(SupplementarySourceStatus, { point: point(status), canManage, confirm }), cleanups)
    await act(async () => { view.container.querySelector<HTMLButtonElement>('button.badge')!.click() })
    await waitForCondition(() => (dialog()?.textContent ?? '').includes('Pia Muster'), 'the panel')
    return view
}

describe('SupplementarySourceStatus (owner)', () => {
    it('shows nothing for a metering point without a source', async () => {
        const { container } = await renderWithProviders(
            createElement(SupplementarySourceStatus, { point: point(null), canManage: true, confirm }), cleanups)

        expect(container.querySelector('button')).toBeNull()
    })

    it('is a button chip that names the status', async () => {
        const { container } = await renderWithProviders(
            createElement(SupplementarySourceStatus, { point: point('reconnect_required'), canManage: true, confirm }), cleanups)

        const chip = container.querySelector<HTMLButtonElement>('button.badge')!
        expect(chip.className).toContain('badge-danger')
        expect(chip.textContent).toContain('supplementary.status.reconnect_required')
        expect(chip.getAttribute('aria-haspopup')).toBe('dialog')
    })

    it('shows status, last sync, coverage and the comparison with the meter, but no credential field', async () => {
        await openPanel(true)

        const text = dialog()!.textContent ?? ''
        expect(text).toContain('supplementary.owner.readOnlyNote')
        expect(text).toContain('supplementary.status.ok')
        expect(text).toContain('supplementary.reconciliation.state.warn')
        expect(text).toContain('supplementary.reconciliation.shifted')
        expect(dialog()!.querySelector('input')).toBeNull()
    })

    it('lets a manager switch the source off, delete its data and remove it, each behind a confirmation', async () => {
        api.updateSupplementarySource.mockResolvedValue({ ...source, enabled: false })
        await openPanel(true)

        await act(async () => { buttonWith(dialog()!, 'supplementary.owner.disable').click() })
        await waitForCondition(() => api.updateSupplementarySource.mock.calls.length === 1, 'the update')
        expect(api.updateSupplementarySource).toHaveBeenCalledWith('src-1', { enabled: false })

        await act(async () => { buttonWith(dialog()!, 'supplementary.actions.deleteData').click() })
        await act(async () => { buttonWith(dialog()!, 'supplementary.actions.remove').click() })
        expect(confirm).toHaveBeenCalledTimes(2)
        expect(confirm.mock.calls[0][0]).toMatchObject({ isDangerous: true, confirmText: 'supplementary.actions.deleteData' })
        expect(api.purgeSupplementaryReadings).not.toHaveBeenCalled()
        expect(api.deleteSupplementarySource).not.toHaveBeenCalled()
    })

    it('shows a viewer the status without any action', async () => {
        await openPanel(false)

        const labels = Array.from(dialog()!.querySelectorAll('button')).map((b) => b.textContent).join('|')
        expect(labels).not.toContain('supplementary.owner.disable')
        expect(labels).not.toContain('supplementary.actions.deleteData')
        expect(labels).not.toContain('supplementary.actions.remove')
        expect(dialog()!.textContent).toContain('supplementary.status.ok')
    })
})

describe('ParticipantTableCard rate cell', () => {
    const gross = (overrides: Partial<GrossEnergy> = {}): GrossEnergy => ({
        source_provider: 'solar_manager', covered_from: '2026-07-01T00:00:00Z', covered_to: '2026-07-04T00:00:00Z', coverage_pct: 100,
        production_kwh: 1, consumption_kwh: 1, import_kwh: 1, export_kwh: 1, self_consumption_kwh: 1,
        self_consumption_rate: 25, self_sufficiency_rate: 75, rates_withheld_reason: null, ...overrides,
    })
    const row = (overrides: Partial<ZevOwnerDashboardSummary['participant_stats'][number]> = {}) => ({
        participant_id: 'p-1', participant_name: 'Pia Muster', total_consumed_kwh: 100, total_produced_kwh: 50, from_zev_kwh: 40,
        from_grid_kwh: 60, has_behind_meter_generation: true, gross_energy: null, ...overrides,
    })
    const rateCell = (container: Element) => container.querySelectorAll('tbody tr td')[5]

    async function render(participant: ReturnType<typeof row>) {
        return renderWithProviders(
            createElement(ParticipantTableCard, { participantStats: [participant], selectedParticipantId: '', onSelect: vi.fn() }), cleanups)
    }

    it('keeps the dash for a net-metered participant without a source', async () => {
        const { container } = await render(row())

        expect(rateCell(container).textContent).toBe('—')
    })

    it('shows the participant\'s own-system rate, marked as such', async () => {
        const { container } = await render(row({ gross_energy: gross() }))

        expect(rateCell(container).textContent).toContain('75')
        expect(rateCell(container).querySelector('[title="supplementary.rateHint"]')).not.toBeNull()
    })

    it('keeps the dash when coverage was too low', async () => {
        const { container } = await render(row({ gross_energy: gross({ rates_withheld_reason: 'low_coverage', self_sufficiency_rate: null }) }))

        expect(rateCell(container).textContent).toBe('—')
    })

    it('does not touch a participant who is not net-metered', async () => {
        const { container } = await render(row({ has_behind_meter_generation: false, gross_energy: gross() }))

        expect(rateCell(container).textContent).toContain('40')
        expect(rateCell(container).querySelector('[title]')).toBeNull()
    })
})
