import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api } from '../src/lib/api/client'
import { fetchFeasibilityCalculatorEnabled } from '../src/lib/api/feasibility'

/**
 * `fetchFeasibilityCalculatorEnabled` backs both the sidebar link's
 * visibility (`Layout.tsx`) and the calculator page's own gate
 * (`FeasibilityCalculatorPage`) — neither of which is a substitute for the
 * server enforcing `FeatureFlag.FEASIBILITY_CALCULATOR_ENABLED` on the
 * calculate/prefill endpoints themselves.
 */
describe('fetchFeasibilityCalculatorEnabled', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('reads the enabled endpoint and unwraps the boolean', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: { enabled: true } } as never)

    const result = await fetchFeasibilityCalculatorEnabled()

    expect(getSpy).toHaveBeenCalledWith('/feasibility/enabled/')
    expect(result).toBe(true)
  })

  it('reflects a disabled flag', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: { enabled: false } } as never)

    expect(await fetchFeasibilityCalculatorEnabled()).toBe(false)
  })
})
