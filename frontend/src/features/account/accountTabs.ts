export type AccountTab = 'profile' | 'security' | 'api-keys' | 'energy-data'

export const ACCOUNT_TABS: AccountTab[] = ['profile', 'security', 'api-keys', 'energy-data']

/**
 * Which tab the account page shows for a URL.
 *
 * An explicit, valid `?tab=` wins. Otherwise the page lands where the visit is
 * about: a forced password change opens Security (the password form lives
 * there), and returning from an OAuth link attempt opens Security too (that is
 * where linked accounts are). Everything else opens Profile. An unknown value
 * falls back the same way rather than showing an empty page. The Energy data
 * tab exists only for someone who can use it (`energyDataAvailable`), so a link
 * to it lands on Profile for everyone else.
 */
export function resolveAccountTab(
    params: URLSearchParams,
    context: { mustChangePassword: boolean; energyDataAvailable?: boolean },
): AccountTab {
    const requested = params.get('tab')
    if (requested === 'energy-data') {
        if (context.energyDataAvailable) return 'energy-data'
    } else if (ACCOUNT_TABS.includes(requested as AccountTab)) {
        return requested as AccountTab
    }
    if (context.mustChangePassword || params.has('oauth_linked') || params.has('oauth_error')) return 'security'
    return 'profile'
}
