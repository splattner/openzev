import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: { count?: number }) => (options?.count === undefined ? key : `${key}:${options.count}`), i18n: { language: 'en' } }),
}))
vi.mock('../src/lib/appSettings', () => ({
    formatShortDate: (value: string) => value,
    formatDateTime: (value: string) => value,
}))
vi.mock('../src/features/meteringPoints/SupplementarySourceStatus', () => ({ SupplementarySourceStatus: () => null }))

import { BuildingHeader } from '../src/features/meteringPoints/BuildingHeader'
import { MeteringPointsList } from '../src/features/meteringPoints/MeteringPointsList'
import {
    countMeteringPointStatuses,
    getMeteringPointStatus,
    groupMeteringPointsByBuilding,
    isBuildingLevelRedundant,
    meteringPointStatusLabelKey,
    readMeteringPointSort,
    sortMeteringPoints,
    type MeteringPointStatus,
} from '../src/features/meteringPoints/useMeteringPointForms'
import type { Building, MeteringPoint, MeteringPointAssignment } from '../src/types/api'

const building = (id: string, name: string, count: number): Building => ({
    id, zev: 'z', name, address_line1: '', address_line2: '', postal_code: '', city: '', egid: null, notes: '',
    metering_point_count: count, building_footprint: null, current_participants: [], created_at: '', updated_at: '',
})

const point = (id: string, over: Partial<MeteringPoint> = {}): MeteringPoint => ({
    id, zev: 'z', meter_id: id, meter_type: 'consumption', is_active: true, building: 'b1', building_name: 'Haus A',
    has_behind_meter_generation: false, reading_count: 10, assignment_count: 0, first_reading_at: null,
    last_reading_at: '2026-10-01T10:00:00Z', supplementary_source_status: null, ...over,
})

const assignment = (id: string, meteringPoint: string, participant: string, over: Partial<MeteringPointAssignment> = {}): MeteringPointAssignment => ({
    id, metering_point: meteringPoint, participant, valid_from: '2020-01-01', valid_to: null, allocation_mode: 'personal',
    created_at: '', updated_at: '', ...over,
})

describe('getMeteringPointStatus', () => {
    it('sets an inactive meter apart whatever its health', () => {
        expect(getMeteringPointStatus({ is_active: false }, 'red', true)).toBe('inactive')
    })

    it('counts a meter without a holder, or with at-risk data, as the worst case', () => {
        expect(getMeteringPointStatus({ is_active: true }, 'green', true)).toBe('danger')
        expect(getMeteringPointStatus({ is_active: true }, 'red', false)).toBe('danger')
    })

    it('maps the rest of the health states', () => {
        expect(getMeteringPointStatus({ is_active: true }, 'yellow', false)).toBe('warning')
        expect(getMeteringPointStatus({ is_active: true }, 'no_data', false)).toBe('pending')
        expect(getMeteringPointStatus({ is_active: true }, 'green', false)).toBe('ok')
    })

    it('labels the status by what explains it', () => {
        expect(meteringPointStatusLabelKey('danger', 'green', true)).toBe('pages.meteringPoints.holderLessBadge')
        expect(meteringPointStatusLabelKey('danger', 'red', false)).toBe('pages.meteringPoints.health.red')
        expect(meteringPointStatusLabelKey('inactive', 'green', false)).toBe('pages.meteringPoints.inactive')
    })
})

describe('sortMeteringPoints', () => {
    const points = [
        point('m3', { location_description: 'Roof', last_reading_at: '2026-10-03T00:00:00Z' }),
        point('m1', { location_description: '', last_reading_at: null }),
        point('m2', { location_description: 'Apt 2', last_reading_at: '2026-09-01T00:00:00Z' }),
        point('m10', { location_description: 'Apt 10', last_reading_at: '2026-10-05T00:00:00Z' }),
    ]
    const statuses = new Map<string, MeteringPointStatus>([['m1', 'ok'], ['m2', 'danger'], ['m3', 'warning'], ['m10', 'danger']])
    const ids = (sort: Parameters<typeof sortMeteringPoints>[1]) => sortMeteringPoints(points, sort, statuses).map((p) => p.id)

    it('puts the worst status first and orders ties by meter ID, numbers by value', () => {
        expect(ids('attention')).toEqual(['m2', 'm10', 'm3', 'm1'])
    })

    it('orders by meter ID with numbers by value', () => {
        expect(ids('meter_id')).toEqual(['m1', 'm2', 'm3', 'm10'])
    })

    it('puts a meter without a location last', () => {
        expect(ids('location')).toEqual(['m2', 'm10', 'm3', 'm1'])
    })

    it('puts the stalest reading first, a meter that never reported ahead of all', () => {
        expect(ids('last_reading')).toEqual(['m1', 'm2', 'm3', 'm10'])
    })

    it('does not reorder the list it is given', () => {
        const before = points.map((p) => p.id)
        sortMeteringPoints(points, 'meter_id', statuses)
        expect(points.map((p) => p.id)).toEqual(before)
    })

    it('reads an unknown sort from the URL as the default', () => {
        expect(readMeteringPointSort('location')).toBe('location')
        expect(readMeteringPointSort('nonsense')).toBe('attention')
        expect(readMeteringPointSort(null)).toBe('attention')
    })
})

describe('countMeteringPointStatuses', () => {
    it('tallies each status, reading a meter with no status as pending', () => {
        const counts = countMeteringPointStatuses(
            [point('a'), point('b'), point('c')],
            new Map<string, MeteringPointStatus>([['a', 'danger'], ['b', 'danger']]),
        )
        expect(counts).toEqual({ ok: 0, warning: 0, danger: 2, pending: 1, inactive: 0 })
    })
})

describe('isBuildingLevelRedundant', () => {
    it('is true for several buildings with one meter each', () => {
        expect(isBuildingLevelRedundant([building('a', 'A', 1), building('b', 'B', 1)])).toBe(true)
    })

    it('is false when a building holds several meters or none, so it stays reachable', () => {
        expect(isBuildingLevelRedundant([building('a', 'A', 2), building('b', 'B', 1)])).toBe(false)
        expect(isBuildingLevelRedundant([building('a', 'A', 1), building('b', 'B', 0)])).toBe(false)
    })

    it('is false for a single building, which has its own one-line header', () => {
        expect(isBuildingLevelRedundant([building('a', 'A', 1)])).toBe(false)
    })
})

describe('MeteringPointsList', () => {
    let root: ReturnType<typeof createRoot> | null = null
    let container: HTMLDivElement | null = null

    afterEach(() => {
        act(() => root?.unmount())
        container?.remove()
        root = null
        container = null
    })

    const names = new Map([['p1', 'Anna Consumer'], ['p2', 'Ben Consumer']])
    const noop = () => undefined

    function render(props: Partial<Parameters<typeof MeteringPointsList>[0]> & { points: MeteringPoint[] }) {
        const { points, ...rest } = props
        const buildings = [building('b1', 'Haus A', 2), building('b2', 'Haus B', 1)]
        const groups = rest.groups === undefined
            ? groupMeteringPointsByBuilding(buildings, points, { filtersActive: false })
            : rest.groups
        container = document.createElement('div')
        document.body.append(container)
        root = createRoot(container)
        act(() => root!.render(createElement(MemoryRouter, null, createElement(MantineProvider, null, createElement(MeteringPointsList, {
            meteringPoints: points,
            assignmentsByMeteringPoint: new Map([
                ['m1', [assignment('a1', 'm1', 'p1')]],
                ['m3', [assignment('a2', 'm3', 'p1'), assignment('a3', 'm3', 'p2')]],
            ]),
            participantNameById: names,
            healthByMeteringPoint: new Map(),
            statusByMeteringPoint: new Map(),
            holderLessByMeteringPoint: new Map(),
            settings: {} as never,
            isManagedScope: true,
            buildings,
            groups,
            renderGroupHeader: (group, state) => createElement(BuildingHeader, {
                building: group.building, landowners: [], variant: 'group', canManage: true, onEdit: noop,
                statusCounts: state.statusCounts, collapsed: state.collapsed, onToggleCollapsed: state.onToggle, panelId: state.panelId,
            }),
            canDeleteData: false,
            deleteMeteringPointPending: false,
            deleteAssignmentPending: false,
            dialogLoading: false,
            confirm: noop,
            onOpenCreateAssignModal: noop,
            onOpenEditMeteringPoint: noop,
            onOpenDeleteDataModal: noop,
            onOpenEditAssignment: noop,
            onDeleteMeteringPoint: noop,
            onDeleteAssignment: noop,
            ...rest,
        })))))
        return container
    }

    const points = [
        point('m1', { building: 'b1' }),
        point('m2', { building: 'b1' }),
        point('m3', { building: 'b2' }),
    ]

    it('asks to assign only on a meter nobody holds, and names the holder elsewhere', () => {
        const view = render({ points })
        const rows = Array.from(view.querySelectorAll('.metering-point-card'))
        const holder = (index: number) => rows[index].querySelector('.metering-point-holder')!
        expect(holder(0).textContent).toContain('Anna Consumer')
        expect(holder(0).querySelector('button')).toBeNull()
        expect(holder(1).querySelector('.button-primary')).not.toBeNull()
        expect(holder(2).textContent).toContain('Anna Consumer')
        expect(holder(2).textContent).toContain('+1')
    })

    it('keeps the row quiet: no Active badge, and the details are closed', () => {
        const view = render({ points })
        expect(view.querySelector('.badge-success')).toBeNull()
        expect(view.querySelector('.metering-point-detail')).toBeNull()
    })

    it('opens a row in place with its participants, measurement and location, and closes it again', () => {
        const view = render({ points })
        const toggle = view.querySelector<HTMLButtonElement>('.metering-point-expand')!
        expect(toggle.getAttribute('aria-expanded')).toBe('false')
        act(() => toggle.click())
        expect(toggle.getAttribute('aria-expanded')).toBe('true')
        const detail = view.querySelector('.metering-point-detail')!
        expect(detail.textContent).toContain('pages.meteringPoints.detail.participants')
        expect(detail.textContent).toContain('pages.meteringPoints.detail.measurement')
        expect(detail.textContent).toContain('pages.meteringPoints.detail.location')
        expect(detail.textContent).toContain('Anna Consumer')
        act(() => toggle.click())
        expect(view.querySelector('.metering-point-detail')).toBeNull()
    })

    it('opens a row when its blank area is clicked, but not when a control in it is', () => {
        const view = render({ points })
        const row = view.querySelector<HTMLElement>('.metering-point-row')!
        act(() => row.querySelector<HTMLElement>('.metering-point-subtitle')!.click())
        expect(view.querySelector('.metering-point-detail')).not.toBeNull()
        act(() => row.querySelector<HTMLElement>('.metering-point-subtitle')!.click())
        expect(view.querySelector('.metering-point-detail')).toBeNull()
        act(() => row.querySelector<HTMLElement>('a')!.click())
        expect(view.querySelector('.metering-point-detail')).toBeNull()
    })

    it('folds a building away from its header, keeping the header', () => {
        const view = render({ points })
        const toggle = view.querySelector<HTMLButtonElement>('.building-header-toggle')!
        const panel = view.querySelector<HTMLElement>(`#${toggle.getAttribute('aria-controls')}`)!
        expect(toggle.getAttribute('aria-expanded')).toBe('true')
        expect(panel.hidden).toBe(false)
        act(() => toggle.click())
        expect(toggle.getAttribute('aria-expanded')).toBe('false')
        expect(panel.hidden).toBe(true)
        expect(view.querySelectorAll('.building-group').length).toBe(2)
    })

    it('never folds the matches away while a filter is active', () => {
        const view = render({ points, filtersActive: true })
        expect(view.querySelector('button.building-header-toggle')).toBeNull()
        expect(view.querySelector('div.building-header-toggle')).not.toBeNull()
        expect(Array.from(view.querySelectorAll<HTMLElement>('.building-group > div[id]')).every((panel) => !panel.hidden)).toBe(true)
    })

    it('sums a building up in its header: what needs a look, or that all is well', () => {
        const view = render({
            points,
            statusByMeteringPoint: new Map<string, MeteringPointStatus>([['m1', 'danger'], ['m2', 'warning'], ['m3', 'ok']]),
        })
        const [first, second] = Array.from(view.querySelectorAll('.building-rollup'))
        expect(first.textContent).toContain('pages.meteringPoints.buildings.rollup.danger:1')
        expect(first.textContent).toContain('pages.meteringPoints.buildings.rollup.warning:1')
        expect(second.textContent).toBe('pages.meteringPoints.buildings.rollup.allGood')
    })

    it('sums a building up from all its meters, whatever the filters leave in the list', () => {
        // Only the healthy meter of Haus A matches the filter; its red one is filtered out.
        const view = render({
            points: [points[1], points[2]],
            allMeteringPoints: points,
            statusByMeteringPoint: new Map<string, MeteringPointStatus>([['m1', 'danger'], ['m2', 'ok'], ['m3', 'ok']]),
        })
        const [first, second] = Array.from(view.querySelectorAll('.building-rollup'))
        expect(first.textContent).toContain('pages.meteringPoints.buildings.rollup.danger:1')
        expect(second.textContent).toBe('pages.meteringPoints.buildings.rollup.allGood')
    })

    it('shows a holder who has not started yet with an Upcoming badge, and no Assign button', () => {
        const view = render({
            points,
            assignmentsByMeteringPoint: new Map([['m2', [assignment('a4', 'm2', 'p2', { valid_from: '2999-01-01' })]]]),
        })
        const holder = view.querySelectorAll('.metering-point-card')[1].querySelector('.metering-point-holder')!
        expect(holder.textContent).toContain('Ben Consumer')
        expect(holder.textContent).toContain('pages.meteringPoints.assignmentState.upcoming')
        expect(holder.querySelector('button')).toBeNull()
    })

    it('counts the assignments that ended behind the current holder', () => {
        const view = render({
            points,
            assignmentsByMeteringPoint: new Map([['m1', [
                assignment('a1', 'm1', 'p1'),
                assignment('a5', 'm1', 'p2', { valid_from: '2019-01-01', valid_to: '2020-12-31' }),
            ]]]),
        })
        const holder = view.querySelectorAll('.metering-point-card')[0].querySelector('.metering-point-holder')!
        expect(holder.textContent).toContain('Anna Consumer')
        expect(holder.textContent).toContain('pages.meteringPoints.earlierAssignments:1')
    })

    it('asks nothing for an inactive meter nobody holds', () => {
        const view = render({ points: [point('m4', { is_active: false })], groups: null })
        const holder = view.querySelector('.metering-point-holder')!
        expect(holder.querySelector('button')).toBeNull()
        expect(holder.textContent).toBe('—')
    })

    it('offers a viewer neither an Assign button, a menu nor assignment controls', () => {
        const view = render({ points, readOnly: true })
        expect(view.querySelector('.metering-point-holder .button-primary')).toBeNull()
        expect(view.querySelector('.metering-point-actions [aria-haspopup="menu"]')).toBeNull()
        act(() => view.querySelector<HTMLButtonElement>('.metering-point-expand')!.click())
        expect(view.querySelector('.metering-point-detail')).not.toBeNull()
        expect(view.querySelector('.metering-point-detail')!.textContent).not.toContain('pages.meteringPoints.detail.addAssignment')
    })

    it('does not open the row when the click ends a text selection', () => {
        const selection = vi.spyOn(window, 'getSelection').mockReturnValue({ toString: () => 'CH-1' } as Selection)
        try {
            const view = render({ points })
            act(() => view.querySelector<HTMLElement>('.metering-point-subtitle')!.click())
            expect(view.querySelector('.metering-point-detail')).toBeNull()
        } finally {
            selection.mockRestore()
        }
    })

    it('names the building under each meter of an ungrouped list', () => {
        const view = render({ points: [points[0], points[2]], groups: null, showBuilding: true })
        expect(view.querySelector('.building-group')).toBeNull()
        const subtitles = Array.from(view.querySelectorAll('.metering-point-subtitle')).map((node) => node.textContent)
        expect(subtitles).toEqual(['Haus A', 'Haus A'])
    })

    it('leaves out the holder column for a role that has no assignments', () => {
        const view = render({ points, isManagedScope: false, groups: null })
        expect(view.querySelector('.metering-point-holder')).toBeNull()
        expect(view.querySelector('.metering-sheet-holders')).toBeNull()
    })
})
