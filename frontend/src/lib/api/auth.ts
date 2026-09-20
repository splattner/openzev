import type {
  AdminApiKey,
  ApiKey,
  ApiKeyInput,
  ApiKeyWithSecret,
  AppSettings,
  AppSettingsInput,
  FeatureFlag,
  FeatureFlagInput,
  ImpersonationResult,
  MfaStatus,
  OAuthLoginInitiateResponse,
  OAuthProvider,
  OAuthProviderConfig,
  OAuthProviderConfigInput,
  RegisterInput,
  SocialAccount,
  SystemHealth,
  TotpEnrolment,
  User,
  UserInput,
  VatRate,
  VatRateInput,
} from '../../types/api'
import { api } from './client'
import { fetchAllPages } from './pagination'

/** Either a completed login (cookies already set by the backend) or a
 * second-factor challenge to complete with submitMfaChallenge(). */
export type LoginResult =
  | { mfaRequired: false }
  | { mfaRequired: true; mfaToken: string; methods: ('totp' | 'recovery_code')[] }

export async function login(email: string, password: string): Promise<LoginResult> {
  const { data } = await api.post('/auth/token/', { email, password })
  if (data?.mfa_required) {
    return { mfaRequired: true, mfaToken: data.mfa_token, methods: data.methods }
  }
  return { mfaRequired: false }
}

/** Second step of a two-factor login: exchanges the challenge token from
 * login() plus a TOTP or recovery code for a session. */
export async function submitMfaChallenge(mfaToken: string, code: string): Promise<void> {
  await api.post('/auth/token/mfa/', { mfa_token: mfaToken, code })
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout/')
}

export async function fetchMe(): Promise<User> {
  const { data } = await api.get<User>('/auth/me/')
  return data
}

// ── Two-factor authentication (TOTP) ──────────────────────────────────────
// Passkey functions join these once WebAuthnCredential ships (spec
// 2026-09-two-factor-authentication.md §5.2, PR 3).

export async function fetchMfaStatus(): Promise<MfaStatus> {
  const { data } = await api.get<MfaStatus>('/auth/me/mfa/')
  return data
}

/** Begins TOTP enrolment. Returns the secret in plain text — the only time
 * it ever is — so it can be typed into an authenticator that cannot scan a
 * QR code. Replaces any previous unconfirmed attempt. */
export async function beginTotpEnrolment(): Promise<TotpEnrolment> {
  const { data } = await api.post<TotpEnrolment>('/auth/me/mfa/totp/')
  return data
}

/** Activates the pending device and returns ten recovery codes, shown once. */
export async function confirmTotpEnrolment(code: string): Promise<{ recovery_codes: string[] }> {
  const { data } = await api.post<{ recovery_codes: string[] }>('/auth/me/mfa/totp/confirm/', { code })
  return data
}

export async function removeTotp(): Promise<void> {
  await api.delete('/auth/me/mfa/totp/')
}

/** Regenerates all ten recovery codes, returned once. Invalidates the old set. */
export async function regenerateRecoveryCodes(): Promise<{ recovery_codes: string[] }> {
  const { data } = await api.post<{ recovery_codes: string[] }>('/auth/me/mfa/recovery-codes/')
  return data
}

export async function fetchAppSettings(): Promise<AppSettings> {
  const { data } = await api.get<AppSettings>('/auth/app-settings/')
  return data
}

/** Admin-only platform health snapshot for the admin Overview hub's
 * System-health tab (phase 3). */
export async function fetchSystemHealth(): Promise<SystemHealth> {
  const { data } = await api.get<SystemHealth>('/auth/system-health/')
  return data
}

export async function updateAppSettings(payload: AppSettingsInput): Promise<AppSettings> {
  const { data } = await api.patch<AppSettings>('/auth/app-settings/', payload)
  return data
}

export async function fetchVatRates(): Promise<VatRate[]> {
  return fetchAllPages<VatRate>('/auth/vat-rates/')
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

export async function fetchUsers(): Promise<User[]> {
  return fetchAllPages<User>('/auth/users/')
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

export async function updateProfile(
  payload: Partial<Pick<User, 'email' | 'first_name' | 'last_name' | 'preferred_zev'>>,
): Promise<User> {
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
  return fetchAllPages<OAuthProviderConfig>('/auth/oauth/providers/config/')
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
  return fetchAllPages<ApiKey>('/auth/me/api-keys/')
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

interface AdminApiKeyFilters {
  user?: number | ''
  status?: 'active' | 'revoked' | ''
}

export async function fetchAllApiKeys(filters: AdminApiKeyFilters = {}): Promise<AdminApiKey[]> {
  const params: Record<string, string> = {}
  if (filters.user) params.user = String(filters.user)
  if (filters.status) params.status = filters.status
  return fetchAllPages<AdminApiKey>('/auth/api-keys/', params)
}

/** Revoke any user's key. Admin only; takes effect on the key's next request. */
export async function revokeAnyApiKey(id: string): Promise<void> {
  await api.delete(`/auth/api-keys/${id}/`)
}
