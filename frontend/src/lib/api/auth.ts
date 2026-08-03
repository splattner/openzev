import type {
  ApiKey,
  ApiKeyInput,
  ApiKeyWithSecret,
  AppSettings,
  AppSettingsInput,
  FeatureFlag,
  FeatureFlagInput,
  ImpersonationResult,
  OAuthLoginInitiateResponse,
  OAuthProvider,
  OAuthProviderConfig,
  OAuthProviderConfigInput,
  PaginatedResponse,
  RegisterInput,
  SocialAccount,
  User,
  UserInput,
  VatRate,
  VatRateInput,
} from '../../types/api'
import { api } from './client'

export async function login(email: string, password: string): Promise<void> {
  await api.post('/auth/token/', { email, password })
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout/')
}

export async function fetchMe(): Promise<User> {
  const { data } = await api.get<User>('/auth/me/')
  return data
}

export async function fetchAppSettings(): Promise<AppSettings> {
  const { data } = await api.get<AppSettings>('/auth/app-settings/')
  return data
}

export async function updateAppSettings(payload: AppSettingsInput): Promise<AppSettings> {
  const { data } = await api.patch<AppSettings>('/auth/app-settings/', payload)
  return data
}

export async function fetchVatRates(): Promise<PaginatedResponse<VatRate>> {
  const { data } = await api.get<PaginatedResponse<VatRate>>('/auth/vat-rates/')
  return data
}

export async function createVatRate(payload: VatRateInput): Promise<VatRate> {
  const { data } = await api.post<VatRate>('/auth/vat-rates/', payload)
  return data
}

export async function updateVatRate(id: number, payload: Partial<VatRateInput>): Promise<VatRate> {
  const { data } = await api.patch<VatRate>(`/auth/vat-rates/${id}/`, payload)
  return data
}

export async function deleteVatRate(id: number): Promise<void> {
  await api.delete(`/auth/vat-rates/${id}/`)
}

export async function fetchFeatureFlags(): Promise<FeatureFlag[]> {
  const { data } = await api.get<FeatureFlag[]>('/auth/feature-flags/')
  return data
}

export async function fetchRegistrationEnabled(): Promise<boolean> {
  const { data } = await api.get<{ enabled: boolean }>('/auth/registration-enabled/')
  return data.enabled
}

export async function updateFeatureFlag(id: number, payload: FeatureFlagInput): Promise<FeatureFlag> {
  const { data } = await api.patch<FeatureFlag>(`/auth/feature-flags/${id}/`, payload)
  return data
}

export async function fetchUsers(): Promise<PaginatedResponse<User>> {
  const { data } = await api.get<PaginatedResponse<User>>('/auth/users/')
  return data
}

export async function impersonateParticipant(userId: number): Promise<ImpersonationResult> {
  const { data } = await api.post<ImpersonationResult>(`/auth/users/${userId}/impersonate/`)
  return data
}

export async function stopImpersonation(): Promise<void> {
  await api.post('/auth/users/stop-impersonation/')
}

export async function updateUser(userId: number, payload: Partial<UserInput>): Promise<User> {
  const { data } = await api.patch<User>(`/auth/users/${userId}/`, payload)
  return data
}

export async function deleteUser(userId: number): Promise<void> {
  await api.delete(`/auth/users/${userId}/`)
}

export async function updateProfile(payload: Partial<Pick<User, 'email' | 'first_name' | 'last_name'>>): Promise<User> {
  const { data } = await api.patch<User>('/auth/me/', payload)
  return data
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<{ detail: string }> {
  const { data } = await api.post<{ detail: string }>('/auth/me/change-password/', {
    old_password: oldPassword,
    new_password: newPassword,
  })
  return data
}

export async function register(payload: RegisterInput): Promise<{ detail: string }> {
  const { data } = await api.post<{ detail: string }>('/auth/register/', payload)
  return data
}

export async function verifyEmail(token: string): Promise<void> {
  await api.post('/auth/verify-email/', { token })
}

export async function setInitialPassword(newPassword: string): Promise<void> {
  await api.post('/auth/me/set-initial-password/', { new_password: newPassword })
}

export async function fetchOAuthProviders(): Promise<OAuthProvider[]> {
  const { data } = await api.get<OAuthProvider[]>('/auth/oauth/providers/')
  return data
}

export async function oauthLoginInitiate(providerSlug: string): Promise<OAuthLoginInitiateResponse> {
  const { data } = await api.post<OAuthLoginInitiateResponse>(`/auth/oauth/login/${providerSlug}/`)
  return data
}

export async function oauthLinkInitiate(providerSlug: string): Promise<OAuthLoginInitiateResponse> {
  const { data } = await api.post<OAuthLoginInitiateResponse>(`/auth/oauth/link/${providerSlug}/`)
  return data
}

export async function oauthTokenExchange(code: string): Promise<void> {
  await api.post('/auth/oauth/token-exchange/', { code })
}

export async function fetchSocialAccounts(): Promise<SocialAccount[]> {
  const { data } = await api.get<SocialAccount[]>('/auth/me/social-accounts/')
  return data
}

export async function deleteSocialAccount(id: number): Promise<void> {
  await api.delete(`/auth/me/social-accounts/${id}/`)
}

export async function fetchOAuthProviderConfigs(): Promise<OAuthProviderConfig[]> {
  const { data } = await api.get<OAuthProviderConfig[] | PaginatedResponse<OAuthProviderConfig>>('/auth/oauth/providers/config/')
  return Array.isArray(data) ? data : data.results
}

export async function createOAuthProviderConfig(payload: OAuthProviderConfigInput): Promise<OAuthProviderConfig> {
  const { data } = await api.post<OAuthProviderConfig>('/auth/oauth/providers/config/', payload)
  return data
}

export async function updateOAuthProviderConfig(id: number, payload: Partial<OAuthProviderConfigInput>): Promise<OAuthProviderConfig> {
  const { data } = await api.patch<OAuthProviderConfig>(`/auth/oauth/providers/config/${id}/`, payload)
  return data
}

export async function deleteOAuthProviderConfig(id: number): Promise<void> {
  await api.delete(`/auth/oauth/providers/config/${id}/`)
}

export async function fetchApiKeys(): Promise<ApiKey[]> {
  const { data } = await api.get<ApiKey[] | PaginatedResponse<ApiKey>>('/auth/me/api-keys/')
  return Array.isArray(data) ? data : data.results
}

/**
 * Creates a key and returns it *with* its secret.
 *
 * This is the only time the secret exists outside the caller's machine — the
 * backend stores a hash. Show it once; do not cache it.
 */
export async function createApiKey(payload: ApiKeyInput): Promise<ApiKeyWithSecret> {
  const { data } = await api.post<ApiKeyWithSecret>('/auth/me/api-keys/', payload)
  return data
}

export async function revokeApiKey(id: string): Promise<void> {
  await api.delete(`/auth/me/api-keys/${id}/`)
}
