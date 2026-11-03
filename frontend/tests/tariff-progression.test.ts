import { act, createElement, type ReactElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProgressionComposition } from '../src/features/tariffs/progression/ProgressionComposition'
import {
    buildChartData,
    clampDay,
    compositionOn,
    feeVersionOn,
    groupFees,
    hasGross,
    intervalOn,
    lineLabel,
    lineOn,
    progressionIssues,
    valueOf,
} from '../src/features/tariffs/progression/progression'
import { DEFAULT_APP_SETTINGS } from '../src/lib/appSettings'
import type {
    TariffProgression,
    TariffProgressionFixedFee,
    TariffProgressionInterval,
    TariffProgressionRule,
    TariffProgressionSlot,
} from '../src/types/api'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options ? `${key} ${JSON.stringify(options)}` : key) }),
}))

const ALL_MONTHS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
const t = (key: string) => key
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const allHours: TariffProgressionRule = {
    months: ALL_MONTHS, weekdays: ALL_DAYS, windows: [{ from: '00:00', to: '24:00' }],
}
const weekdayDay: TariffProgressionRule = {
    months: ALL_MONTHS, weekdays: [0, 1, 2, 3, 4], windows: [{ from: '07:00', to: '20:00' }],
}

function slot(line: string, net: string, gross: string | null = null): TariffProgressionSlot {
    return {
        line, net, gross,
        categories: [{
            category: 'energy', net, gross,
            components: [{
                tariff_id: `t-${line}`, name: 'Energie', billing_mode: 'energy', band_period_id: 'p',
                net, gross, dynamic: false, coverage: null, percentage: null, base_net: null,
            }],
        }],
    }
}

function interval(from: string, to: string, slots: TariffProgressionSlot[], extra: Partial<TariffProgressionInterval> = {}): TariffProgressionInterval {
    return { from, to, vat_rate: null, missing_categories: [], incomplete: [], slots, ...extra }
}

function progression(overrides: Partial<TariffProgression> = {}): TariffProgression {
    return {
        zev: 'z', energy_type: 'grid', vat_mode: 'registered',
        from: '2025-01-01', to: '2025-12-31', expected_categories: ['energy'],
        lines: [{ key: 'line-1', rules: [allHours] }, { key: 'line-2', rules: [weekdayDay] }],
        intervals: [
            interval('2025-01-01', '2025-06-30', [slot('line-1', '0.25000', '0.27000')]),
            interval('2025-07-01', '2025-12-31', [slot('line-1', '0.20000', '0.21620'), slot('line-2', '0.30000', '0.32430')]),
        ],
        fixed_fees: [],
        ...overrides,
    }
}

const ms = (day: string) => Date.parse(`${day}T00:00:00Z`)

describe('buildChartData', () => {
    it('puts a point at every interval boundary and one at the very end', () => {
        const { points } = buildChartData(progression(), 'net')

        expect(points.map((point) => point.t)).toEqual([ms('2025-01-01'), ms('2025-07-01'), ms('2025-12-31')])
    })

    it('holds a line at null where it does not exist, so it breaks', () => {
        const { points } = buildChartData(progression(), 'net')

        expect(points.map((point) => point['line-2'])).toEqual([null, 0.3, 0.3])
        expect(points.map((point) => point['line-1'])).toEqual([0.25, 0.2, 0.2])
    })

    it('reads gross on the gross basis and net otherwise', () => {
        expect(buildChartData(progression(), 'gross').points[0]['line-1']).toBe(0.27)
        expect(buildChartData(progression(), 'net').points[0]['line-1']).toBe(0.25)
    })

    it('falls back to net where a value has no gross', () => {
        const data = buildChartData(progression({
            intervals: [interval('2025-01-01', '2025-12-31', [slot('line-1', '0.25000')])],
        }), 'gross')

        expect(data.points[0]['line-1']).toBe(0.25)
    })

    it('keys lines without a dot, which Recharts would read as a property path', () => {
        expect(progression().lines.every((line) => !line.key.includes('.'))).toBe(true)
    })

    it('flags stretches that are understated or empty, end exclusive', () => {
        const { flagged } = buildChartData(progression({
            intervals: [
                interval('2025-01-01', '2025-03-31', [slot('line-1', '0.25000')], { missing_categories: ['grid_fees'] }),
                interval('2025-04-01', '2025-05-31', []),
                interval('2025-06-01', '2025-12-31', [slot('line-1', '0.25000')]),
            ],
        }), 'net')

        expect(flagged).toEqual([
            { from: ms('2025-01-01'), to: ms('2025-04-01') },
            { from: ms('2025-04-01'), to: ms('2025-06-01') },
        ])
    })

    it('has no points for an empty progression', () => {
        expect(buildChartData(progression({ intervals: [], lines: [] }), 'net').points).toEqual([])
    })
})

describe('lookups', () => {
    it('finds the interval a day falls in, ends included', () => {
        expect(intervalOn(progression(), '2025-06-30')?.from).toBe('2025-01-01')
        expect(intervalOn(progression(), '2025-07-01')?.from).toBe('2025-07-01')
        expect(intervalOn(progression(), '2026-01-01')).toBeUndefined()
    })

    it('clamps a day into the range', () => {
        expect(clampDay('2024-01-01', '2025-01-01', '2025-12-31')).toBe('2025-01-01')
        expect(clampDay('2027-01-01', '2025-01-01', '2025-12-31')).toBe('2025-12-31')
        expect(clampDay('2025-05-05', '2025-01-01', '2025-12-31')).toBe('2025-05-05')
    })

    it('composes the slot of a line on a day', () => {
        expect(compositionOn(progression(), '2025-08-01', 'line-2')?.slot.net).toBe('0.30000')
        expect(compositionOn(progression(), '2025-02-01', 'line-2')).toBeNull()
    })

    it('keeps the chosen line where it exists and otherwise takes the first', () => {
        expect(lineOn(progression(), '2025-08-01', 'line-2')).toBe('line-2')
        expect(lineOn(progression(), '2025-02-01', 'line-2')).toBe('line-1')
        expect(lineOn(progression(), '2025-02-01', null)).toBe('line-1')
    })

    it('has gross only for a VAT-registered or inclusive community', () => {
        expect(hasGross('not_registered')).toBe(false)
        expect(hasGross('registered')).toBe(true)
        expect(hasGross('inclusive')).toBe(true)
    })

    it('chooses the value by basis', () => {
        expect(valueOf({ net: '1', gross: '2' }, 'gross')).toBe('2')
        expect(valueOf({ net: '1', gross: '2' }, 'net')).toBe('1')
        expect(valueOf({ net: '1', gross: null }, 'gross')).toBe('1')
    })
})

describe('lineLabel', () => {
    it('calls a line that always applies "all hours"', () => {
        expect(lineLabel([allHours], t, DAYS, MONTHS)).toBe('pages.tariffs.progression.allHours')
    })

    it('names weekdays and the window', () => {
        expect(lineLabel([weekdayDay], t, DAYS, MONTHS)).toBe('Mon–Fri 07:00–20:00')
    })

    it('names a season and a wrapping window', () => {
        const winterNights: TariffProgressionRule = {
            months: [1, 2, 3, 10, 11, 12], weekdays: ALL_DAYS, windows: [{ from: '20:00', to: '07:00' }],
        }
        expect(lineLabel([winterNights], t, DAYS, MONTHS)).toBe('Oct–Mar 20:00–07:00')
    })

    it('joins several rules', () => {
        const weekend: TariffProgressionRule = { months: ALL_MONTHS, weekdays: [5, 6], windows: [{ from: '00:00', to: '24:00' }] }
        const night: TariffProgressionRule = { months: ALL_MONTHS, weekdays: [0, 1, 2, 3, 4], windows: [{ from: '20:00', to: '07:00' }] }
        expect(lineLabel([weekend, night], t, DAYS, MONTHS)).toBe('Sat–Sun; Mon–Fri 20:00–07:00')
    })
})

describe('progressionIssues', () => {
    it('merges the same problem across consecutive intervals', () => {
        const issues = progressionIssues(progression({
            intervals: [
                interval('2025-01-01', '2025-03-31', [slot('line-1', '0.1')], { missing_categories: ['grid_fees'] }),
                interval('2025-04-01', '2025-06-30', [slot('line-1', '0.1')], { missing_categories: ['grid_fees'] }),
                interval('2025-07-01', '2025-12-31', [slot('line-1', '0.1')]),
            ],
        }))

        expect(issues).toEqual([{ kind: 'missing', subject: 'grid_fees', from: '2025-01-01', to: '2025-06-30' }])
    })

    it('keeps separate stretches apart and reports incomplete tariffs by name', () => {
        const spot = { tariff_id: 'x', name: 'Spot', reason: 'dynamic_no_data' as const }
        const issues = progressionIssues(progression({
            intervals: [
                interval('2025-01-01', '2025-03-31', [slot('line-1', '0.1')], { incomplete: [spot] }),
                interval('2025-04-01', '2025-04-30', [slot('line-1', '0.1')]),
                interval('2025-05-01', '2025-12-31', [slot('line-1', '0.1')], { incomplete: [spot] }),
            ],
        }))

        expect(issues).toEqual([
            { kind: 'dynamic_no_data', subject: 'Spot', from: '2025-01-01', to: '2025-03-31' },
            { kind: 'dynamic_no_data', subject: 'Spot', from: '2025-05-01', to: '2025-12-31' },
        ])
    })

    it('reports nothing for a complete progression', () => {
        expect(progressionIssues(progression())).toEqual([])
    })
})

describe('fixed fees', () => {
    const fee = (name: string, unit: 'month' | 'year'): TariffProgressionFixedFee => ({
        name, category: 'metering', billing_mode: unit === 'month' ? 'monthly_fee' : 'yearly_fee', unit,
        scope: 'participant', split_key: null,
        versions: [
            { tariff_id: 'a', valid_from: '2024-01-01', valid_to: '2024-12-31', amount_net: '5.00', amount_gross: null, vat_rate: null },
            { tariff_id: 'b', valid_from: '2025-01-01', valid_to: null, amount_net: '6.00', amount_gross: null, vat_rate: null },
        ],
    })

    it('keeps monthly and yearly fees apart', () => {
        const groups = groupFees([fee('A', 'month'), fee('B', 'year'), fee('C', 'month')])

        expect(groups.month.map((entry) => entry.name)).toEqual(['A', 'C'])
        expect(groups.year.map((entry) => entry.name)).toEqual(['B'])
    })

    it('picks the version in force, else the latest before the day, else the first', () => {
        expect(feeVersionOn(fee('A', 'month'), '2024-06-01').amount_net).toBe('5.00')
        expect(feeVersionOn(fee('A', 'month'), '2026-06-01').amount_net).toBe('6.00')
        expect(feeVersionOn(fee('A', 'month'), '2020-01-01').amount_net).toBe('5.00')
    })
})

describe('ProgressionComposition', () => {
    const cleanups: (() => void)[] = []
    afterEach(() => {
        cleanups.splice(0).forEach((cleanup) => cleanup())
        document.body.innerHTML = ''
    })

    async function render(element: ReactElement) {
        const container = document.createElement('div')
        document.body.append(container)
        const root = createRoot(container)
        cleanups.push(() => { act(() => root.unmount()); container.remove() })
        await act(async () => root.render(element))
        return container
    }

    const props = {
        lineNames: { 'line-1': 'All hours', 'line-2': 'Mon–Fri 07:00–20:00' },
        settings: DEFAULT_APP_SETTINGS,
        onPickLine: vi.fn(),
    }

    it('shows the components of a category under its subtotal and a total', async () => {
        const container = await render(createElement(ProgressionComposition, {
            ...props, progression: progression(), day: '2025-08-01', lineKey: 'line-2', basis: 'net',
        }))

        const text = container.textContent ?? ''
        expect(text).toContain('Energie')
        expect(text).toContain('0.300')
        expect(container.querySelector('tfoot')?.textContent).toContain('0.300')
        expect(container.querySelector('.tariff-progression-subtotal')?.textContent).toContain('pages.tariffs.categories.energy')
    })

    it('switches to gross values', async () => {
        const container = await render(createElement(ProgressionComposition, {
            ...props, progression: progression(), day: '2025-08-01', lineKey: 'line-2', basis: 'gross',
        }))

        expect(container.querySelector('tfoot')?.textContent).toContain('0.324')
    })

    it('says so when the line has no price on that day', async () => {
        const container = await render(createElement(ProgressionComposition, {
            ...props, progression: progression(), day: '2025-02-01', lineKey: 'line-2', basis: 'net',
        }))

        expect(container.querySelector('table')).toBeNull()
        expect(container.textContent).toContain('pages.tariffs.progression.composition.none')
    })

    it('offers the lines of the day, and only when there is a choice', async () => {
        const many = await render(createElement(ProgressionComposition, {
            ...props, progression: progression(), day: '2025-08-01', lineKey: 'line-1', basis: 'net',
        }))
        const one = await render(createElement(ProgressionComposition, {
            ...props, progression: progression(), day: '2025-02-01', lineKey: 'line-1', basis: 'net',
        }))

        expect(many.querySelectorAll('select option')).toHaveLength(2)
        expect(one.querySelector('select')).toBeNull()
    })

    it('labels a dynamic component as an average of fetched prices with its coverage', async () => {
        const dynamicSlot: TariffProgressionSlot = {
            line: 'line-1', net: '0.05940', gross: null,
            categories: [{
                category: 'grid_fees', net: '0.05940', gross: null,
                components: [{
                    tariff_id: 'd', name: 'Netznutzung dynamisch', billing_mode: 'energy', band_period_id: null,
                    net: '0.05940', gross: null, dynamic: true, coverage: '0.6055', percentage: null, base_net: null,
                }],
            }],
        }
        const container = await render(createElement(ProgressionComposition, {
            ...props,
            progression: progression({ intervals: [interval('2025-01-01', '2025-12-31', [dynamicSlot])], lines: [{ key: 'line-1', rules: [allHours] }] }),
            day: '2025-03-01', lineKey: 'line-1', basis: 'net',
        }))

        expect(container.textContent).toContain('Netznutzung dynamisch')
        expect(container.textContent).toContain('"coverage":"61"')
    })

    it('explains a percentage component by its share and base', async () => {
        const base = progression()
        const percentage = progression({
            intervals: [interval('2025-01-01', '2025-12-31', [{
                line: 'line-1', net: '0.19500', gross: null,
                categories: [{
                    category: 'energy', net: '0.19500', gross: null,
                    components: [{
                        tariff_id: 'p', name: 'Lokalanteil', billing_mode: 'percentage_of_energy', band_period_id: 'b',
                        net: '0.19500', gross: null, dynamic: false, coverage: null, percentage: '65.00', base_net: '0.30000',
                    }],
                }],
            }])],
            lines: base.lines.slice(0, 1),
        })

        const container = await render(createElement(ProgressionComposition, {
            ...props, progression: percentage, day: '2025-03-01', lineKey: 'line-1', basis: 'net',
        }))

        expect(container.textContent).toContain('"percentage":"65"')
        expect(container.textContent).toContain('"base":"0.300"')
    })
})
