import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api } from '../src/lib/api/client'
import { fetchGridOperatorSuggestions } from '../src/lib/api/zev'
import { unacceptedOperators, urlSuggestionCandidate } from '../src/features/zev/GridOperatorSuggestion'
import type { GridOperator } from '../src/types/api'

/**
 * `GridOperatorSuggestion` derives which operators to offer and which one's
 * `tariff_url` to offer from the postal-code lookup result and the form's
 * current `grid_operator_elcom_id`. These cover that derivation and the API
 * call it depends on; rendering is left to manual QA, matching
 * `grid-operator-field.test.ts`.
 */

const IWM: GridOperator = {
  id: 625, name: 'InfraWerkeMünsingen (IWM)', uid: 'CHE-109.834.319', website: 'www.inframuensingen.ch',
  tariff_url: 'https://www.inframuensingen.ch', tariff_url_is_direct: false,
}
const OTHER: GridOperator = {
  id: 1, name: 'Other Utility', uid: '', website: '',
  tariff_url: 'https://other.example/tarife.json', tariff_url_is_direct: true,
}
const NO_URL: GridOperator = {
  id: 2, name: 'No URL Utility', uid: '', website: '', tariff_url: '', tariff_url_is_direct: false,
}

describe('unacceptedOperators', () => {
  it('returns every suggestion when none is accepted yet', () => {
    expect(unacceptedOperators([IWM], null)).toEqual([IWM])
  })

  it('drops the operator matching the form\'s current elcom id', () => {
    expect(unacceptedOperators([IWM, OTHER], IWM.id)).toEqual([OTHER])
  })

  it('is unaffected when the current id matches nothing suggested', () => {
    // e.g. the owner picked a different operator by hand from the full list.
    expect(unacceptedOperators([IWM], 999)).toEqual([IWM])
  })
})

describe('urlSuggestionCandidate', () => {
  it('is the sole suggestion when the postal code resolves to exactly one operator', () => {
    expect(urlSuggestionCandidate([IWM], null)).toBe(IWM)
  })

  it('is undefined for several operators until one has been accepted', () => {
    // Suggesting one operator's URL at random would be worse than suggesting
    // none — the owner has to say which of them applies first.
    expect(urlSuggestionCandidate([IWM, OTHER], null)).toBeUndefined()
  })

  it('is the accepted operator once the form matches one of several suggestions', () => {
    expect(urlSuggestionCandidate([IWM, OTHER], OTHER.id)).toBe(OTHER)
  })

  it('is undefined when there are no suggestions at all', () => {
    expect(urlSuggestionCandidate([], null)).toBeUndefined()
  })
})

describe('fetchGridOperatorSuggestions', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('passes the postal code as a query param and returns the operator list', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: { operators: [IWM] } } as never)

    const result = await fetchGridOperatorSuggestions('3110')

    expect(getSpy).toHaveBeenCalledWith('/zev/grid-operators/suggest/', { params: { postal_code: '3110' } })
    expect(result.operators).toEqual([IWM])
  })

  it('a postal code the register does not cover resolves to an empty list, not an error', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: { operators: [] } } as never)

    const result = await fetchGridOperatorSuggestions('0000')

    expect(result.operators).toEqual([])
  })
})

describe('an operator with no tariff_url', () => {
  it('is still a valid url suggestion candidate — the component, not this helper, decides whether to render it', () => {
    // Every operator with tariff_url === '' still comes through as the
    // candidate; the component withholds the URL block on the empty string,
    // not this selection logic, so a future caller cannot accidentally
    // bypass that check by calling the helper directly.
    expect(urlSuggestionCandidate([NO_URL], null)).toBe(NO_URL)
  })
})
