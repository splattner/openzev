import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { FeasibilityCalculatorPage } from '../src/pages/FeasibilityCalculatorPage'

// jsdom does not enable the React act() environment by default; without this
// flag every act() call warns and deferred work is not flushed reliably.
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const t = (key: string) => key
const { calculateFeasibility } = vi.hoisted(() => ({ calculateFeasibility: vi.fn() }))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t }),
}))

vi.mock('../src/lib/api/zev', () => ({
  fetchZevs: vi.fn().mockResolvedValue([]),
}))

vi.mock('../src/lib/api/feasibility', () => ({
  calculateFeasibility,
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
