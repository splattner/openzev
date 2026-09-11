import type { FeasibilityInput, FeasibilityPrefill, FeasibilityResult } from '../../types/api'
import { api } from './client'

/**
 * Whether the feasibility calculator is on — checked by any authenticated
 * role (not just admins), so this is the minimal boolean endpoint, mirroring
 * `fetchRegistrationEnabled`. Off by default; disabled in the sidebar and
 * the calculator page when this is false, and enforced again server-side on
 * the calculate/prefill endpoints regardless of what the client renders.
 */
export async function fetchFeasibilityCalculatorEnabled(): Promise<boolean> {
  const { data } = await api.get<{ enabled: boolean }>('/feasibility/enabled/')
  return data.enabled
}

export async function calculateFeasibility(payload: FeasibilityInput): Promise<FeasibilityResult> {
  const { data } = await api.post<FeasibilityResult>('/feasibility/calculate/', payload)
  return data
}

export async function fetchFeasibilityPrefill(zevId: string): Promise<FeasibilityPrefill> {
  const { data } = await api.get<FeasibilityPrefill>(`/feasibility/prefill/${zevId}/`)
  return data
}
