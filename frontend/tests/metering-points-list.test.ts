import { waitForCondition } from './helpers/waitForCondition'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (key.endsWith('removeAssignMessage') || key.endsWith('issueFor') ? `${key}:${JSON.stringify(options)}` : options?.count === undefined ? key : `${key}:${options.count}`), i18n: { language: 'en' } }),
}))
vi.mock('../src/lib/appSettings', () => ({
    formatShortDate: (value: string) => value,
    formatDateTime: (value: string) => value,
}))
vi.mock('../src/features/meteringPoints/SupplementarySourceStatus', () => ({ SupplementarySourceStatus: () => null }))

import { BuildingHeader } from '../src/features/meteringPoints/BuildingHeader'
import { MeteringPointsList } from '../src/features/meteringPoints/MeteringPointsList'
import {
    groupMeteringPointsByBuilding,
    readMeteringPointSort,
    sortMeteringPoints,
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

describe('sortMeteringPoints', () => {
    const points = [
        point('m3', { location_description: 'Roof', last_reading_at: '2026-10-03T00:00:00Z' }),
        point('m1', { location_description: '', last_reading_at: null }),
        point('m2', { location_description: 'Apt 2', last_reading_at: '2026-09-01T00:00:00Z' }),
        point('m10', { location_description: 'Apt 10', last_reading_at: '2026-10-05T00:00:00Z' }),
    ]
    const ids = (sort: Parameters<typeof sortMeteringPoints>[1]) => sortMeteringPoints(points, sort).map((p) => p.id)

    it('orders by meter ID, numbers by value', () => {
        expect(ids('meter_id')).toEqual(['m1', 'm2', 'm3', 'm10'])
    })

    it('puts a meter without a location last, ordering the rest by location with numbers by value', () => {
        expect(ids('location')).toEqual(['m2', 'm10', 'm3', 'm1'])
    })

    it('puts the stalest reading first, a meter that never reported ahead of all', () => {
        expect(ids('last_reading')).toEqual(['m1', 'm2', 'm3', 'm10'])
    })

    it('does not reorder the list it is given', () => {
        const before = points.map((p) => p.id)
        sortMeteringPoints(points, 'location')
        expect(points.map((p) => p.id)).toEqual(before)
    })

    it('reads an unknown or removed sort from the URL as the default, meter ID', () => {
        expect(readMeteringPointSort('location')).toBe('location')
        expect(readMeteringPointSort('attention')).toBe('meter_id')
        expect(readMeteringPointSort('nonsense')).toBe('meter_id')
        expect(readMeteringPointSort(null)).toBe('meter_id')
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
            holderLessByMeteringPoint: new Map(),
            settings: {} as never,
            assignmentsAvailable: true,
            isManagedScope: true,
            groups,
            renderGroupHeader: (group) => createElement(BuildingHeader, {
                building: group.building, landowners: [], canManage: true, onEdit: noop,
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
        point('m1', { building: 'b1', location_description: 'Roof' }),
        point('m2', { building: 'b1' }),
        point('m3', { building: 'b2' }),
    ]

    it('shows the location under the meter ID only when there is one', () => {
        const view = render({ points })
        const subtitles = Array.from(view.querySelectorAll('.metering-point-subtitle')).map((node) => node.textContent)
        expect(subtitles).toEqual(['Roof'])
        expect(view.textContent).not.toContain('pages.meteringPoints.noLocation')
    })

    it('asks to assign only on a meter nobody holds, and names the holder elsewhere', () => {
        const view = render({ points })
        const rows = Array.from(view.querySelectorAll('.metering-point-card'))
        const holder = (index: number) => rows[index].querySelector('.metering-point-holder')!
        expect(holder(0).textContent).toContain('Anna Consumer')
        expect(holder(0).querySelector('.button-primary')).toBeNull()
        expect(holder(1).querySelector('.button-primary')).not.toBeNull()
        expect(holder(2).textContent).toContain('Anna Consumer')
        expect(holder(2).textContent).toContain('+1')
    })

    it('names building tables and exposes all column headers and detail spans', () => {
        const view = render({ points })
        const table = view.querySelector('table')!
        const heading = view.querySelector('h2')!
        expect(table.getAttribute('aria-labelledby')).toBe(heading.id)
        expect(Array.from(table.querySelectorAll('th')).map((cell) => cell.getAttribute('scope'))).toEqual(['col', 'col', 'col', 'col'])
        expect(table.querySelector('thead')!.getAttribute('aria-hidden')).toBeNull()
        expect(table.querySelector('.metering-point-row')!.children).toHaveLength(4)
        act(() => table.querySelector<HTMLButtonElement>('.metering-point-expand')!.click())
        expect(table.querySelector('.metering-point-detail')!.getAttribute('colspan')).toBe('4')
    })

    it('keeps IDs and holders as text and offers a labelled building-edit button with a pencil', () => {
        const editBuilding = vi.fn()
        const view = render({ points,
            renderGroupHeader: (group) => createElement(BuildingHeader, { building: group.building, landowners: [], canManage: true, onEdit: editBuilding }),
        })
        expect(view.querySelector('.metering-point-id-main button')).toBeNull()
        expect(view.querySelector('.metering-holder-name button')).toBeNull()
        const edit = view.querySelector<HTMLButtonElement>('.building-header-actions button')!
        expect(edit.querySelector('svg[data-icon="pen"]')).not.toBeNull()
        act(() => edit.click())
        expect(editBuilding).toHaveBeenCalledWith(expect.objectContaining({ id: 'b1' }))
        expect(view.querySelector('.metering-point-detail')).toBeNull()
    })

    it('keeps the row quiet: no Active badge, and the details are closed', () => {
        const view = render({ points })
        expect(view.querySelector('.badge-success')).toBeNull()
        expect(view.querySelector('.metering-point-detail')).toBeNull()
    })

    it('opens a row in place with its participants and measurement, and closes it again', () => {
        const view = render({ points })
        const toggle = view.querySelector<HTMLButtonElement>('.metering-point-expand')!
        expect(toggle.getAttribute('aria-expanded')).toBe('false')
        act(() => toggle.click())
        expect(toggle.getAttribute('aria-expanded')).toBe('true')
        const detail = view.querySelector('.metering-point-detail')!
        expect(detail.textContent).toContain('pages.meteringPoints.detail.participants')
        expect(detail.textContent).toContain('pages.meteringPoints.detail.measurement')
        expect(detail.textContent).not.toContain('pages.meteringPoints.detail.location')
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

    it('removes the selected assignment through a direct button and confirmation', () => {
        const confirm = vi.fn()
        const remove = vi.fn()
        const view = render({ points: [point('m3')], groups: null, confirm, onDeleteAssignment: remove })
        act(() => view.querySelector<HTMLButtonElement>('.metering-point-expand')!.click())
        const detail = view.querySelector('.metering-point-detail')!
        expect(detail.querySelector('[aria-haspopup="menu"]')).toBeNull()
        const removeButtons = detail.querySelectorAll<HTMLButtonElement>('.metering-assignment-actions .button-danger')
        expect(removeButtons).toHaveLength(2)
        act(() => removeButtons[1].click())
        expect(remove).not.toHaveBeenCalled()
        expect(confirm).toHaveBeenCalledWith(expect.objectContaining({ isDangerous: true }))
        confirm.mock.calls[0][0].onConfirm()
        expect(remove).toHaveBeenCalledExactlyOnceWith('a3')
    })

    it('identifies the point and selected historical period when a participant has repeated assignments', () => {
        const confirm = vi.fn()
        const remove = vi.fn()
        const view = render({ points: [point('m1')], groups: null, confirm, onDeleteAssignment: remove,
            assignmentsByMeteringPoint: new Map([['m1', [
                assignment('recent', 'm1', 'p1', { valid_from: '2022-01-01', valid_to: '2022-12-31' }),
                assignment('older', 'm1', 'p1', { valid_from: '2021-01-01', valid_to: '2021-12-31' }),
            ]]]),
        })
        act(() => view.querySelector<HTMLButtonElement>('.metering-point-expand')!.click())
        act(() => view.querySelectorAll<HTMLButtonElement>('.metering-assignment-actions .button-danger')[1].click())
        const options = confirm.mock.calls[0][0]
        expect(options.message).toContain(JSON.stringify({ name: 'Anna Consumer', meterId: 'm1', from: '2021-01-01', to: '2021-12-31' }))
        expect(remove).not.toHaveBeenCalled()
        options.onConfirm()
        expect(remove).toHaveBeenCalledExactlyOnceWith('older')
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

    it('labels participant tables with three columns', () => {
        const participant = render({ points, isManagedScope: false, groups: null })
        expect(participant.querySelector('table')!.getAttribute('aria-label')).toBe('pages.meteringPoints.title')
        expect(participant.querySelectorAll('th')).toHaveLength(3)
        act(() => participant.querySelector<HTMLButtonElement>('.metering-point-expand')!.click())
        expect(participant.querySelector('.metering-point-detail')!.getAttribute('colspan')).toBe('3')
    })

    it('shows no status dot or building health summary', () => {
        const view = render({ points })
        expect(view.querySelector('.dot')).toBeNull()
        expect(view.querySelector('.building-rollup')).toBeNull()
    })

    it.each([
        { health: 'green', holderLess: false, active: true, expected: false },
        { health: 'unknown', holderLess: false, active: true, expected: false },
        { health: 'yellow', holderLess: false, active: true, expected: true },
        { health: 'red', holderLess: false, active: true, expected: true },
        { health: 'no_data', holderLess: false, active: true, expected: true },
        { health: 'green', holderLess: true, active: true, expected: true },
        { health: 'unknown', holderLess: true, active: true, expected: true },
        { health: 'red', holderLess: true, active: false, expected: false },
        { health: 'yellow', holderLess: true, active: true, expected: true },
    ] as const)('marks only attention points: $health, missing assignment=$holderLess, active=$active', ({ health, holderLess, active, expected }) => {
        const view = render({ points: [point('m1', { is_active: active, reading_count: health === 'no_data' ? 0 : 10 })], groups: null,
            healthByMeteringPoint: new Map([['m1', health]]), holderLessByMeteringPoint: new Map([['m1', holderLess]]),
        })
        expect(!!view.querySelector('.issue-text')).toBe(expected)
        expect(view.querySelector('.metering-point-id-main .dot')).toBeNull()
        if (expected) {
            if (health !== 'green' && health !== 'unknown') {
                const issue = view.querySelector<HTMLAnchorElement>('.metering-point-last .issue-text')!
                expect(issue.textContent).toContain(`pages.meteringPoints.health.${health === 'no_data' ? 'noReadings' : health}`)
                expect(issue.getAttribute('href')).toBe('/metering-data?metering_point=m1&tab=quality')
                expect(issue.getAttribute('aria-label')).toContain('m1')
                expect(issue.classList.contains(health === 'red' ? 'issue-text--error' : 'issue-text--warning')).toBe(true)
            }
            if (holderLess) expect(view.querySelector('.metering-point-holder .issue-text')!.textContent).toContain('pages.meteringPoints.holderLessBadge')
        }
    })

    it('gives every building the same header, one or several', () => {
        const single = render({ points: [points[0]], groups: groupMeteringPointsByBuilding([building('b1', 'Haus A', 1)], [points[0]], { filtersActive: false }) })
        expect(single.querySelectorAll('.building-header').length).toBe(1)
        expect(single.querySelector('.building-header-name')!.textContent).toBe('Haus A')
    })

    it('has nothing to fold: a building header is not a button', () => {
        const view = render({ points })
        expect(view.querySelector('.building-header-toggle, .building-header-chevron')).toBeNull()
        const headerName = view.querySelector('.building-header-name')!
        expect(headerName.closest('button')).toBeNull()
    })

    it('names no building under the meters: the group header already does', () => {
        const view = render({ points })
        const subtitles = Array.from(view.querySelectorAll('.metering-point-subtitle')).map((node) => node.textContent)
        expect(subtitles.some((text) => text?.includes('Haus'))).toBe(false)
    })

    it('leaves out the holder column for a role that has no assignments', () => {
        const view = render({ points, isManagedScope: false, groups: null })
        expect(view.querySelector('.metering-point-holder')).toBeNull()
        expect(view.querySelector('.metering-sheet-holders')).toBeNull()
    })

    it('explains the type icons once below the sheets, naming only the types on the page', () => {
        const view = render({ points: [...points, point('m4', { building: 'b2', meter_type: 'production' })] })
        const legend = view.querySelectorAll('.metering-type-legend')
        expect(legend).toHaveLength(1)
        expect(Array.from(legend[0].querySelectorAll('li')).map((item) => item.textContent)).toEqual([
            'pages.meteringPoints.meterTypes.consumption',
            'pages.meteringPoints.meterTypes.production',
        ])
        expect(legend[0].previousElementSibling?.classList.contains('building-group')).toBe(true)
        expect(legend[0].nextElementSibling).toBeNull()
    })

    it('has no legend without meters, and keeps it on the plain list of a role without buildings', () => {
        expect(render({ points: [] }).querySelector('.metering-type-legend')).toBeNull()
        act(() => root?.unmount())
        container?.remove()
        expect(render({ points, isManagedScope: false, groups: null }).querySelector('.metering-type-legend')).not.toBeNull()
    })
    it('does not offer generic edit/remove actions for multiple current assignments', async () => {
        const view = render({ points: [point('m3')], groups: null })
        act(() => view.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')!.click())
        await waitForCondition(() => !!document.querySelector('[role="menuitem"]'), 'point menu')
        const menu = document.querySelector('[role="menu"]')!
        expect(menu.textContent).not.toContain('pages.meteringPoints.editAssignTitle')
        expect(menu.textContent).not.toContain('pages.meteringPoints.removeAssignTitle')
        expect(menu.textContent).toContain('common.edit')
    })

    it('keeps assignment creation hidden until assignment history is available', () => {
        const view = render({ points, assignmentsAvailable: false })
        expect(view.querySelector('.metering-point-holder .button-primary')).toBeNull()
        expect(view.querySelector('.metering-holder-name button')).toBeNull()
        expect(view.textContent).toContain('pages.meteringPoints.assignmentsUnavailable')
        act(() => view.querySelector<HTMLButtonElement>('.metering-point-expand')!.click())
        expect(view.querySelector('.metering-point-detail')!.textContent).not.toContain('pages.meteringPoints.detail.addAssignment')
    })

    it('targets the single current assignment from the point menu', async () => {
        const edit = vi.fn()
        const confirm = vi.fn()
        const remove = vi.fn()
        const view = render({ points: [point('m1')], groups: null, onOpenEditAssignment: edit, confirm, onDeleteAssignment: remove })
        const openMenu = async () => {
            act(() => view.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')!.click())
            await waitForCondition(() => !!document.querySelector('[role="menuitem"]'), 'point menu')
        }
        await openMenu()
        const editItem = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'))
            .find(button => button.textContent?.includes('pages.meteringPoints.editAssignTitle'))!
        expect(editItem.querySelector('svg[data-icon="pen"]')).not.toBeNull()
        act(() => editItem.click())
        expect(edit).toHaveBeenCalledWith(expect.objectContaining({ id: 'a1' }))
        await waitForCondition(() => !document.querySelector('[role="menuitem"]'), 'closed menu')
        await openMenu()
        act(() => Array.from(document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'))
            .find(button => button.textContent?.includes('pages.meteringPoints.removeAssignTitle'))!.click())
        expect(remove).not.toHaveBeenCalled()
        confirm.mock.calls[0][0].onConfirm()
        expect(remove).toHaveBeenCalledExactlyOnceWith('a1')
    })

})
