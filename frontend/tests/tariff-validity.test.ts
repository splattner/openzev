import { describe, expect, it } from 'vitest'
import { hasUpcomingVersion, listedVersion, tariffOverview } from '../src/features/tariffs/validity'
import { emphasizedDate } from '../src/features/tariffs/datePresentation'
import type { Tariff, TariffSeries } from '../src/types/api'

const TODAY = '2026-10-12'
const version = (id: string, valid_from: string, valid_to: string | null) => ({ id, valid_from, valid_to }) as Tariff
const ended = version('ended', '2025-01-01', '2025-12-31')
const current = version('current', '2026-01-01', '2026-12-31')
const next = version('next', '2027-01-01', null)

describe('the version a tariff row stands for', () => {
    it('is the one in force, even when a later one is scheduled', () => {
        expect(listedVersion([next, current, ended], TODAY).id).toBe('current')
    })

    it('is the next to start in the Upcoming view', () => {
        expect(listedVersion([next, current, ended], TODAY, true).id).toBe('next')
    })

    it('picks the nearest upcoming version from the API newest-first order', () => {
        const later = version('later', '2028-01-01', null)
        expect(listedVersion([later, next, current, ended], TODAY, true).id).toBe('next')
        expect(listedVersion([later, next, ended], TODAY).id).toBe('next')
    })

    it('falls back to what comes next, then to the newest retired version', () => {
        expect(listedVersion([next, ended], TODAY).id).toBe('next')
        expect(listedVersion([ended, version('older', '2024-01-01', '2024-12-31')], TODAY).id).toBe('ended')
    })

    it('counts a series as upcoming only when a version is still to start', () => {
        expect(hasUpcomingVersion([next, current, ended], TODAY)).toBe(true)
        expect(hasUpcomingVersion([current, ended], TODAY)).toBe(false)
    })
})

describe('the emphasis on an upcoming start date', () => {
    const bold = (parts: { text: string, strong: boolean }[]) => parts.map((part) => (part.strong ? `*${part.text}*` : part.text)).join('')

    it('sets the year bold for a start in a later year', () => {
        expect(bold(emphasizedDate('01.01.2027', 'dd.MM.yyyy', false))).toBe('01.01.*2027*')
        expect(bold(emphasizedDate('2027-01-01', 'yyyy-MM-dd', false))).toBe('*2027*-01-01')
    })

    it('adds the month for a start within this year, with the separator between', () => {
        expect(bold(emphasizedDate('01.11.2026', 'dd.MM.yyyy', true))).toBe('01.*11.2026*')
        expect(bold(emphasizedDate('2026-11-01', 'yyyy-MM-dd', true))).toBe('*2026-11*-01')
    })

    it('keeps month and year apart when the day sits between them', () => {
        expect(bold(emphasizedDate('11/01/2026', 'MM/dd/yyyy', true))).toBe('*11*/01/*2026*')
    })

    it('leaves a date it cannot match to the pattern as it is', () => {
        expect(bold(emphasizedDate('—', 'dd.MM.yyyy', true))).toBe('—')
    })
})

describe('the overview groups', () => {
    const series = (name: string, ...versions: Tariff[]) => ({ name, versions }) as unknown as TariffSeries
    const ids = (rows: { series: TariffSeries, version: { id: string } }[]) => rows.map((row) => `${row.series.name}:${row.version.id}`)

    it('lists a series under each group it has a version for, with that group\'s version', () => {
        const groups = tariffOverview([series('Energy', next, current, ended)], TODAY)
        expect(ids(groups.current)).toEqual(['Energy:current'])
        expect(ids(groups.upcoming)).toEqual(['Energy:next'])
        expect(ids(groups.history)).toEqual(['Energy:ended'])
    })

    it('shows the nearest upcoming version and the most recently ended one', () => {
        const later = version('later', '2028-01-01', null)
        const older = version('older', '2024-01-01', '2024-12-31')
        const groups = tariffOverview([series('Energy', later, next, current, ended, older)], TODAY)
        expect(ids(groups.upcoming)).toEqual(['Energy:next'])
        expect(ids(groups.history)).toEqual(['Energy:ended'])
    })

    it('keeps a series with only past versions reachable, in History alone', () => {
        const groups = tariffOverview([series('Old', ended)], TODAY)
        expect(groups.current).toEqual([])
        expect(groups.upcoming).toEqual([])
        expect(ids(groups.history)).toEqual(['Old:ended'])
    })

    it('treats a window that opens or closes today as current', () => {
        const opens = version('opens', TODAY, null)
        const closes = version('closes', '2026-01-01', TODAY)
        expect(ids(tariffOverview([series('A', opens), series('B', closes)], TODAY).current)).toEqual(['A:opens', 'B:closes'])
    })
})
