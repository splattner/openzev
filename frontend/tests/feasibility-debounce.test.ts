import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { FeasibilityCalculatorPage } from '../src/pages/FeasibilityCalculatorPage'

const t = (key: string) => key
const { calculateFeasibility, fetchFeasibilityCalculatorEnabled } = vi.hoisted(() => ({
  calculateFeasibility: vi.fn(),
  // The page renders the calculator only once this resolves true (see
  // FeasibilityCalculatorPage's gate) — this suite is about the debounce
  // effect inside the calculator itself, so the flag is on throughout.
  fetchFeasibilityCalculatorEnabled: vi.fn().mockResolvedValue(true),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t }),
}))

vi.mock('../src/lib/api/zev', () => ({
  fetchZevs: vi.fn().mockResolvedValue([]),
}))

vi.mock('../src/lib/api/feasibility', () => ({
  calculateFeasibility,
  fetchFeasibilityCalculatorEnabled,
}))

vi.mock('../src/features/feasibility/PrefillFromZevCard', () => ({
  PrefillFromZevCard: () => null,
}))

vi.mock('../src/features/feasibility/ParticipantRowsEditor', () => ({
  ParticipantRowsEditor: () => null,
}))

vi.mock('../src/features/feasibility/ParticipantResultsTable', () => ({
  ParticipantResultsTable: () => null,
}))

vi.mock('../src/components/EnergyFlowChart', () => ({
  EnergyFlowChart: () => null,
}))

vi.mock('../src/features/feasibility/FeasibilityCashflowChart', () => ({
  FeasibilityCashflowChart: () => null,
}))

vi.mock('../src/features/feasibility/FeasibilityPriceSensitivityChart', () => ({
  FeasibilityPriceSensitivityChart: () => null,
}))

vi.mock('../src/features/feasibility/FeasibilitySensitivityChart', () => ({
  FeasibilitySensitivityChart: () => null,
}))

const DEBOUNCE_MS = 400

const cannedResult = {
  self_consumed_kwh: '8000',
  grid_import_kwh: '2000',
  grid_export_kwh: '1000',
  autarky_rate: '0.8',
  baseline_consumer_cost_chf: '1000',
  baseline_producer_revenue_chf: '500',
  vzev_consumer_cost_chf: '800',
  vzev_producer_revenue_chf: '600',
  consumer_savings_chf: '200',
  producer_gain_chf: '100',
  annual_gross_benefit_chf: '300',
  annual_net_benefit_chf: '250',
  payback_years: '5.5',
  roi: '0.18',
  npv_chf: '1200',
  cashflow_by_year: [],
  sensitivity: [],
  break_even_self_consumption_rate: '0.6',
  price_sensitivity: [],
  equal_split_price_chf_per_kwh: null,
  fair_price_range: null,
  participants: [],
}

let container: HTMLDivElement
let root: ReturnType<typeof createRoot> | null = null

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })
  root = createRoot(container)
  act(() => {
    root!.render(
      createElement(QueryClientProvider, { client: queryClient }, createElement(FeasibilityCalculatorPage)),
    )
  })
  return root
}

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
})

afterEach(() => {
  if (root) {
    act(() => root!.unmount())
  }
  root = null
  document.body.removeChild(container)
  vi.clearAllMocks()
  vi.useRealTimers()
})

describe('FeasibilityCalculatorPage debounce effect', () => {
  it('does not resubmit when the mutation object identity changes after each render', async () => {
    calculateFeasibility.mockResolvedValue(cannedResult)
    vi.useFakeTimers()

    renderPage()

    // Let the enabled-flag query resolve before the gate mounts the
    // calculator. Under fake timers React's own scheduler (which falls back
    // to setTimeout in jsdom) needs a timer tick to flush queued work, not
    // just a microtask flush, so advance by 0 alongside each `act`.
    for (let i = 0; i < 5; i++) {
      await act(async () => {
        vi.advanceTimersByTime(0)
      })
    }

    // First debounce cycle fires one submission...
    await act(async () => {
      vi.advanceTimersByTime(DEBOUNCE_MS)
    })
    expect(calculateFeasibility).toHaveBeenCalledTimes(1)

    // ...and mutation-state re-renders (pending/success) must NOT re-arm the
    // timer: interleaved debounce cycles with a React flush between each must
    // keep the call count at one (a dependency on the `mutation` result object
    // would resubmit on every re-render, growing the count each cycle).
    for (let i = 0; i < 10; i++) {
        await act(async () => {
            vi.advanceTimersByTime(DEBOUNCE_MS)
        })
        await act(async () => {})
    }
    expect(calculateFeasibility).toHaveBeenCalledTimes(1)

    // A real form-value change does schedule another submission.
    const productionInput = container.querySelector(
      'input[name="annual_production_kwh"]',
    ) as HTMLInputElement
    act(() => {
      // Directly assigning .value bypasses React's value tracking (React 19),
      // so the change is never seen by the onChange handler; use the native setter.
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
      setter.call(productionInput, '12000')
      productionInput.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => {
      vi.advanceTimersByTime(DEBOUNCE_MS)
    })
    expect(calculateFeasibility).toHaveBeenCalledTimes(2)
  })
})
