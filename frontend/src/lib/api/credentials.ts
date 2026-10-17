import type {
  AccessCredential,
  AdminAccessCredential,
  AnalyticsTokenInput,
  AnalyticsTokenWithSecret,
  CredentialKind,
  MyCredentialsResponse,
} from '../../types/api'
import { api } from './client'
import { revokeAnyApiKey, revokeApiKey } from './auth'
import { revokeSupplementaryPushToken } from './supplementary'

/** The account's own API keys, analytics tokens and energy data push tokens. */
export async function fetchMyCredentials(): Promise<MyCredentialsResponse> {
  const { data } = await api.get<MyCredentialsResponse>('/auth/me/credentials/')
  return data
}

interface AdminCredentialFilters {
  user?: number | ''
  kind?: CredentialKind | ''
  status?: 'active' | 'expired' | 'revoked' | ''
}

/** Every account's credentials. Admin only. */
export async function fetchAllCredentials(filters: AdminCredentialFilters = {}): Promise<AdminAccessCredential[]> {
  const params: Record<string, string> = {}
  if (filters.user) params.user = String(filters.user)
  if (filters.kind) params.kind = filters.kind
  if (filters.status) params.status = filters.status
  const { data } = await api.get<{ credentials: AdminAccessCredential[] }>('/auth/credentials/', { params })
  return data.credentials
}

/**
 * Creates an analytics token and returns it *with* its secret. The backend
 * stores a hash: this is the only time the secret can be read.
 */
export async function createAnalyticsToken(payload: AnalyticsTokenInput): Promise<AnalyticsTokenWithSecret> {
  const { data } = await api.post<AnalyticsTokenWithSecret>('/analytics/tokens/', payload)
  return data
}

export async function revokeAnalyticsToken(id: string): Promise<void> {
  await api.delete(`/analytics/tokens/${id}/`)
}

/** Revokes a credential through the endpoint of its kind; ``asAdmin`` uses the admin endpoint for API keys. */
export async function revokeCredential(
  credential: Pick<AccessCredential, 'kind' | 'id'>,
  options: { asAdmin?: boolean } = {},
): Promise<void> {
  switch (credential.kind) {
    case 'api_key':
      return options.asAdmin ? revokeAnyApiKey(credential.id) : revokeApiKey(credential.id)
    case 'analytics':
      return revokeAnalyticsToken(credential.id)
    case 'energy_push':
      return revokeSupplementaryPushToken(credential.id)
  }
}
