import type { AdminUser, UserRole } from '../../types/api'

export type AccountFilters = {
    search: string
    role: UserRole | 'all'
    /** Community id, or 'all'. */
    zevId: string
    /** 'all', or accounts the MFA policy names that have not enrolled yet (grace or overdue). */
    mfaCompliance: 'all' | 'needsTwoFactor'
}

export const DEFAULT_ACCOUNT_FILTERS: AccountFilters = { search: '', role: 'all', zevId: 'all', mfaCompliance: 'all' }

/** Whether the policy names this account and it has not enrolled yet. */
export function needsTwoFactor(account: Pick<AdminUser, 'mfa_compliance'>): boolean {
    return account.mfa_compliance?.status === 'grace' || account.mfa_compliance?.status === 'overdue'
}

export function hasActiveFilters(filters: AccountFilters): boolean {
    return filters.search.trim() !== '' || filters.role !== 'all' || filters.zevId !== 'all' || filters.mfaCompliance !== 'all'
}

export function accountDisplayName(account: Pick<AdminUser, 'first_name' | 'last_name' | 'username'>): string {
    return `${account.first_name} ${account.last_name}`.trim() || account.username
}

/**
 * Accounts matching the filters, ordered by name.
 *
 * The community filter matches *any* membership, owner or participant: "who
 * is in this community" is the question it answers, and an owner is in it.
 * Search is a case-insensitive substring over the name, username and email.
 */
export function filterAccounts(accounts: AdminUser[], filters: AccountFilters): AdminUser[] {
    const needle = filters.search.trim().toLowerCase()
    return accounts
        .filter((account) => filters.role === 'all' || account.role === filters.role)
        .filter((account) => filters.zevId === 'all' || account.memberships.some((m) => m.zev === filters.zevId))
        .filter((account) => filters.mfaCompliance === 'all' || needsTwoFactor(account))
        .filter((account) => {
            if (!needle) return true
            return [accountDisplayName(account), account.username, account.email].some((value) =>
                value.toLowerCase().includes(needle),
            )
        })
        .sort((left, right) => accountDisplayName(left).localeCompare(accountDisplayName(right)))
}

/**
 * Accounts an admin may attach to a participant. Mirrors the server's link
 * rule: only participant or guest roles, and only while not already tied to a
 * participant (an account holds at most one participant record).
 */
export function linkableAccounts(accounts: AdminUser[]): AdminUser[] {
    return accounts
        .filter((account) => account.role === 'participant' || account.role === 'guest')
        .filter((account) => account.memberships.every((m) => m.participant === null))
        .sort((left, right) => left.username.localeCompare(right.username))
}

/** The server refuses to delete an account that belongs to a community. */
export function canDeleteAccount(account: Pick<AdminUser, 'memberships'>): boolean {
    return account.memberships.length === 0
}

/** Only participant and owner accounts may be impersonated (never admins). */
export function canImpersonateAccount(account: Pick<AdminUser, 'role'>): boolean {
    return account.role === 'participant' || account.role === 'zev_owner'
}

export function accountStats(accounts: AdminUser[]) {
    return {
        total: accounts.length,
        withTwoFactor: accounts.filter((account) => account.mfa_methods.length > 0).length,
        // Guests are accounts not yet tied to a participant: the ones waiting to be linked.
        guests: accounts.filter((account) => account.role === 'guest').length,
        needsTwoFactor: accounts.filter(needsTwoFactor).length,
        neverSignedIn: accounts.filter((account) => account.last_login === null).length,
    }
}
