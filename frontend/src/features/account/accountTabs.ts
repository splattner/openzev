export type AccountTab = 'profile' | 'security' | 'tokens'

export const ACCOUNT_TABS: AccountTab[] = ['profile', 'security', 'tokens']

/**
 * Which tab the account page shows for a URL.
 *
 * An explicit, valid `?tab=` wins. Otherwise the page lands where the visit is
 * about: a forced password change opens Security (the password form lives
 * there), and returning from an OAuth link attempt opens Security too (that is
 * where linked accounts are). Everything else opens Profile. An unknown value
 * falls back the same way rather than showing an empty page.
 */
export function resolveAccountTab(
    params: URLSearchParams,
    context: { mustChangePassword: boolean },
): AccountTab {
    // `api-keys` was this tab's name before it also held analytics and energy data tokens.
    const requested = params.get('tab') === 'api-keys' ? 'tokens' : params.get('tab')
    if (ACCOUNT_TABS.includes(requested as AccountTab)) return requested as AccountTab
    if (context.mustChangePassword || params.has('oauth_linked') || params.has('oauth_error')) return 'security'
    return 'profile'
}
