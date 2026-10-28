import { createElement, type ReactElement } from 'react'
import { act } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TariffDetailPane } from '../src/features/tariffs/TariffDetailPane'
import { renderWithProviders } from './helpers/render'
import type { TariffSeries, TariffVersion } from '../src/types/api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: 1, role: 'admin' } }) }))
vi.mock('../src/lib/api/tariffs', () => ({ fetchDynamicTariffSources: vi.fn().mockResolvedValue([]) }))

// The detail pane is in flow beside the list, not an overlay (SPEC-2026-10-tariff-split-view §5, §6).

const settings = { date_format_short: 'dd.MM.yyyy', date_format_long: 'd MMMM yyyy', date_time_format: 'dd.MM.yyyy HH:mm', updated_at: '' }
const version = (id: string, valid_from: string, valid_to: string | null): TariffVersion => ({
    id, zev: 'z', name: 'Grid', category: 'grid_fees', billing_mode: 'monthly_fee', energy_type: null,
    valid_from, valid_to, fixed_price_chf: '10.00', split_key: 'equal', notes: '', periods: [],
}) as unknown as TariffVersion
const past = version('past', '2000-01-01', '2000-12-31')
const current = version('current', '2001-01-01', null)
const next = version('next', '2999-01-01', null)
const series = { zev: 'z', name: 'Grid', category: 'grid_fees', billing_mode: 'monthly_fee', energy_type: null,
    version_count: 3, active_version_id: 'current', gaps: [], versions: [next, current, past] } as unknown as TariffSeries

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

const noop = () => undefined
const handlers = {
    onShowVersion: noop, onClose: noop, onEditTariff: noop,
    onOpenCreatePeriod: noop, onEditPeriod: noop, onNewVersion: noop,
    onDuplicate: noop, onRenameSeries: noop,
}
async function pane(props: Record<string, unknown> = {}): Promise<HTMLElement> {
    const element = createElement(TariffDetailPane, { series, allSeries: [series], settings, shownVersionId: null, ...handlers, ...props } as never) as ReactElement
    const { container } = await renderWithProviders(element, cleanups)
    return container
}

describe('TariffDetailPane', () => {
    it('is a region named by its title and is not modal', async () => {
        const container = await pane()
        const region = container.querySelector('section.tariff-pane')!
        expect(region.getAttribute('aria-modal')).toBeNull()
        expect(region.getAttribute('role')).toBeNull()
        expect(container.querySelector(`#${region.getAttribute('aria-labelledby')}`)?.textContent).toBe('Grid')
        expect(container.querySelector('h2')?.getAttribute('tabindex')).toBe('-1')
    })

    it('shows the current and the scheduled version in full, and folds the past into the history', async () => {
        const container = await pane()
        const cards = [...container.querySelectorAll('.tariff-version-card')]
        expect(cards.slice(0, 2).map((card) => card.querySelector('.badge')?.textContent)).toEqual([
            'pages.tariffs.overview.current', 'pages.tariffs.overview.upcoming',
        ])
        const history = container.querySelector<HTMLDetailsElement>('.disclosure')!
        expect(history.querySelector('summary')?.textContent).toBe('pages.tariffs.versions.history (1)')
        expect(history.open).toBe(false)
        expect(cards).toHaveLength(2)
    })

    it('opens the history when a past version is shown, and says it is not the current one', async () => {
        const container = await pane({ shownVersionId: 'past' })
        expect(container.querySelector<HTMLDetailsElement>('.disclosure')!.open).toBe(true)
        expect(container.querySelector('.tariff-version-row.is-shown.is-ended')).not.toBeNull()
        expect(container.querySelector('.disclosure .tariff-version-card .badge')?.textContent).toBe('pages.tariffs.versions.statusEnded')
    })

    it('says what the scheduled version changes against the one before it', async () => {
        const dearer = { ...next, fixed_price_chf: '12.00' } as TariffVersion
        const container = await pane({ series: { ...series, versions: [dearer, current, past] } })
        const cards = container.querySelectorAll('.tariff-version-card')
        expect(cards[0].querySelector('.tariff-change')).toBeNull()
        // Folded, the scheduled version says it in a line; opened, with the amount.
        expect(cards[1].querySelector('.tariff-change')?.textContent).toBe('(+20 %)')
        const toggle = cards[1].querySelector<HTMLButtonElement>('.tariff-version-toggle')!
        await act(async () => { toggle.click() })
        expect(cards[1].querySelector('.tariff-change')?.textContent).toContain('+2.00 (+20 %)')
    })

    it('folds the scheduled version to a line and opens it on request, or when it is the one shown', async () => {
        const container = await pane()
        const [now, later] = [...container.querySelectorAll('.tariff-version-card')]
        expect(now.querySelector('.tariff-version-toggle')).toBeNull()
        const toggle = later.querySelector<HTMLButtonElement>('.tariff-version-toggle')!
        expect(toggle.getAttribute('aria-expanded')).toBe('false')
        expect(later.querySelector('.tariff-version-card-body')).toBeNull()
        await act(async () => { toggle.click() })
        expect(toggle.getAttribute('aria-expanded')).toBe('true')
        expect(later.querySelector(`#${toggle.getAttribute('aria-controls')}`)).not.toBeNull()
        const shown = await pane({ shownVersionId: 'next' })
        expect(shown.querySelectorAll('.tariff-version-toggle')[0].getAttribute('aria-expanded')).toBe('true')
    })

    it('puts no delete button on the cards: deleting is done from the edit form', async () => {
        const container = await pane()
        expect(container.querySelector('.button-danger')).toBeNull()
    })

    it('shows a version\u2019s notes only where the overview row does not already say them', async () => {
        const noted = (id: string, base: TariffVersion, notes: string) => ({ ...base, id, notes }) as TariffVersion
        const container = await pane({ shownVersionId: 'next', series: { ...series, versions: [
            noted('next', next, 'Price rise'), noted('current', current, 'Standard'), past,
        ] } })
        const notes = [...container.querySelectorAll('.tariff-version-card-notes')].map((node) => node.textContent)
        expect(notes).toEqual(['Price rise'])
    })

    it('carries no status pill or version count in its heading', async () => {
        const container = await pane()
        expect(container.querySelector('.tariff-pane-header .badge')).toBeNull()
        expect(container.querySelector('.tariff-pane-meta')?.textContent).not.toMatch(/\d/)
    })

    it('closes on Escape unless something inside already took it', async () => {
        const onClose = vi.fn()
        const container = await pane({ onClose })
        const title = container.querySelector('h2')!
        await act(async () => { title.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })) })
        expect(onClose).toHaveBeenCalledOnce()
        const handled = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
        title.addEventListener('keydown', (event) => event.preventDefault(), { once: true })
        await act(async () => { title.dispatchEvent(handled) })
        expect(onClose).toHaveBeenCalledOnce()
    })

    it('offers a viewer the same facts and warnings with no write controls', async () => {
        const container = await pane({ readOnly: true, shownVersionId: 'past' })
        expect(container.querySelector('.tariff-pane-actions')).toBeNull()
        expect(container.querySelector('.tariff-version-card .button')).toBeNull()
        expect(container.querySelector('.tariff-version-row .button')).toBeNull()
        expect(container.querySelector('.tariff-version-select')).not.toBeNull()
    })

    it('replaces the body with the form being edited and keeps the tariff named', async () => {
        const container = await pane({ editor: { label: 'editing label', content: createElement('form', { className: 'the-form' }) } })
        expect(container.querySelector('h2')?.textContent).toBe('Grid')
        expect(container.querySelector('.tariff-pane-meta')?.textContent).toBe('editing label')
        expect(container.querySelector('.the-form')).not.toBeNull()
        expect(container.querySelector('.tariff-version-card')).toBeNull()
    })
})
