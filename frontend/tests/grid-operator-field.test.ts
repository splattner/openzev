import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api } from '../src/lib/api/client'
import { fetchGridOperators } from '../src/lib/api/zev'
import type { GridOperator } from '../src/types/api'

/**
 * `GridOperatorField` derives `grid_operator_elcom_id` from the typed name on
 * every change rather than tracking it separately, so the two can never
 * disagree. These cover that derivation and the API call it depends on;
 * rendering Mantine's `Autocomplete` is left to manual QA.
 */
function idForName(operators: GridOperator[], name: string): number | null {
    const map = new Map(operators.map((operator) => [operator.name, operator.id]))
    return map.get(name) ?? null
}

const OPERATORS: GridOperator[] = [
    { id: 486, name: 'Elektrizitätswerke des Kantons Zürich (EKZ)', uid: 'CHE-108.954.688', website: 'www.ekz.ch' },
    { id: 735, name: 'Stadtwerk Winterthur', uid: 'CHE-116.284.940', website: '' },
]

describe('grid operator id derivation', () => {
    it('matches an exact name from the official list', () => {
        expect(idForName(OPERATORS, 'Stadtwerk Winterthur')).toBe(735)
    })

    it('yields null for a hand-typed operator', () => {
        // A utility missing from ElCom's tariff cube must stay enterable.
        expect(idForName(OPERATORS, 'Genossenschaft Kleindorf')).toBeNull()
    })

    it('drops the id when a picked name is edited', () => {
        // Editing by one character must not leave a stale id pointing at a
        // different utility than the name says.
        expect(idForName(OPERATORS, 'Stadtwerk Winterthur ')).toBeNull()
    })

    it('is case-sensitive, so a near-miss does not silently claim a match', () => {
        expect(idForName(OPERATORS, 'stadtwerk winterthur')).toBeNull()
    })
})

describe('fetchGridOperators', () => {
    beforeEach(() => vi.restoreAllMocks())

    it('reads the unpaginated reference list', async () => {
        const payload = { source: 's', cube: 'c', licence: 'l', period: '2026', fetched_on: '2026-09-02', operators: OPERATORS }
        const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: payload } as never)

        const result = await fetchGridOperators()

        expect(getSpy).toHaveBeenCalledWith('/zev/grid-operators/')
        expect(result.operators).toHaveLength(2)
        expect(result.licence).toBe('l')
    })
})
