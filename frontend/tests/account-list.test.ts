import { describe, expect, it } from 'vitest'
import {
    DEFAULT_ACCOUNT_FILTERS,
    accountStats,
    canDeleteAccount,
    canImpersonateAccount,
    filterAccounts,
    hasActiveFilters,
    linkableAccounts,
    needsTwoFactor,
} from '../src/features/accounts/accountList'
import type { AccountMembership, AdminUser, MfaCompliance } from '../src/types/api'

const member = (zev: string, over: Partial<AccountMembership> = {}): AccountMembership => ({
    zev,
    zev_name: zev.toUpperCase(),
    is_owner: false,
    participant: `p-${zev}`,
    ...over,
})

let nextId = 1
const account = (over: Partial<AdminUser> = {}): AdminUser => ({
    id: nextId++,
    username: `user${nextId}`,
    email: `user${nextId}@example.com`,
    first_name: 'Ada',
    last_name: 'Lovelace',
    role: 'participant',
    must_change_password: false,
    preferred_zev: null,
    is_active: true,
    memberships: [],
    mfa_methods: [],
    mfa_compliance: null,
    ...over,
})

describe('filterAccounts', () => {
    const tenantInA = account({ username: 'tina', first_name: 'Tina', last_name: 'Tenant', memberships: [member('a')] })
    const ownerOfB = account({
        username: 'olga', first_name: 'Olga', last_name: 'Owner', role: 'zev_owner',
        memberships: [member('b', { is_owner: true })],
    })
    const both = account({
        username: 'ben', first_name: 'Ben', last_name: 'Both', role: 'zev_owner',
        memberships: [member('a', { is_owner: true }), member('b', { participant: null, is_owner: true })],
    })
    const all = [tenantInA, ownerOfB, both]

    it('returns everyone, ordered by name, with no filters', () => {
        expect(filterAccounts(all, DEFAULT_ACCOUNT_FILTERS).map((a) => a.username)).toEqual(['ben', 'olga', 'tina'])
    })

    it('matches a community through any membership, owner or participant', () => {
        const inA = filterAccounts(all, { ...DEFAULT_ACCOUNT_FILTERS, zevId: 'a' }).map((a) => a.username)
        expect(inA).toEqual(['ben', 'tina'])
        const inB = filterAccounts(all, { ...DEFAULT_ACCOUNT_FILTERS, zevId: 'b' }).map((a) => a.username)
        expect(inB).toEqual(['ben', 'olga'])
    })

    it('filters by platform role', () => {
        const owners = filterAccounts(all, { ...DEFAULT_ACCOUNT_FILTERS, role: 'zev_owner' })
        expect(owners.map((a) => a.username)).toEqual(['ben', 'olga'])
    })

    it('searches name, username and email case-insensitively', () => {
        expect(filterAccounts(all, { ...DEFAULT_ACCOUNT_FILTERS, search: ' OLG ' }).map((a) => a.username)).toEqual(['olga'])
        expect(filterAccounts(all, { ...DEFAULT_ACCOUNT_FILTERS, search: tenantInA.email.toUpperCase() })).toEqual([tenantInA])
    })

    it('combines filters conjunctively', () => {
        expect(filterAccounts(all, { search: 'o', role: 'zev_owner', zevId: 'a', mfaCompliance: 'all' }).map((a) => a.username)).toEqual(['ben'])
    })

    it('falls back to the username when an account has no name', () => {
        const nameless = account({ username: 'zed', first_name: '', last_name: '' })
        expect(filterAccounts([nameless], { ...DEFAULT_ACCOUNT_FILTERS, search: 'zed' })).toEqual([nameless])
    })
})

describe('hasActiveFilters', () => {
    it('is false for the defaults and for a whitespace-only search', () => {
        expect(hasActiveFilters(DEFAULT_ACCOUNT_FILTERS)).toBe(false)
        expect(hasActiveFilters({ ...DEFAULT_ACCOUNT_FILTERS, search: '   ' })).toBe(false)
    })

    it('is true once any filter narrows the list', () => {
        expect(hasActiveFilters({ ...DEFAULT_ACCOUNT_FILTERS, search: 'x' })).toBe(true)
        expect(hasActiveFilters({ ...DEFAULT_ACCOUNT_FILTERS, role: 'guest' })).toBe(true)
        expect(hasActiveFilters({ ...DEFAULT_ACCOUNT_FILTERS, zevId: 'a' })).toBe(true)
    })
})

describe('linkableAccounts', () => {
    it('offers participant and guest accounts that hold no participant record', () => {
        const free = account({ username: 'free' })
        const guest = account({ username: 'guest', role: 'guest' })
        const taken = account({ username: 'taken', memberships: [member('a')] })
        const owner = account({ username: 'owner', role: 'zev_owner' })
        const admin = account({ username: 'admin', role: 'admin' })

        expect(linkableAccounts([taken, owner, admin, guest, free]).map((a) => a.username)).toEqual(['free', 'guest'])
    })

    it('does not treat an owner-only membership as a participant link', () => {
        // Cannot occur for participant/guest roles today, but the rule is
        // "holds a participant record", not "has any membership".
        const odd = account({ username: 'odd', role: 'guest', memberships: [member('a', { participant: null, is_owner: true })] })
        expect(linkableAccounts([odd])).toEqual([odd])
    })
})

describe('account action guards', () => {
    it('blocks deleting an account that belongs to a community', () => {
        expect(canDeleteAccount(account())).toBe(true)
        expect(canDeleteAccount(account({ memberships: [member('a')] }))).toBe(false)
    })

    it('impersonates participants and owners, never admins or guests', () => {
        expect(canImpersonateAccount({ role: 'participant' })).toBe(true)
        expect(canImpersonateAccount({ role: 'zev_owner' })).toBe(true)
        expect(canImpersonateAccount({ role: 'admin' })).toBe(false)
        expect(canImpersonateAccount({ role: 'guest' })).toBe(false)
    })
})

describe('accountStats', () => {
    it('counts accounts, two-factor accounts, guests and accounts needing two-factor', () => {
        const stats = accountStats([
            account({ mfa_methods: ['totp'] }),
            account({ mfa_methods: ['passkey', 'totp'], role: 'guest' }),
            account({ role: 'guest' }),
            account({ mfa_compliance: grace() }),
            account({ mfa_compliance: overdue() }),
        ])
        expect(stats).toEqual({ total: 5, withTwoFactor: 2, guests: 2, needsTwoFactor: 2 })
    })
})

const grace = (): MfaCompliance => ({ status: 'grace', deadline: '2026-12-01T00:00:00Z' })
const overdue = (): MfaCompliance => ({ status: 'overdue', deadline: '2026-01-01T00:00:00Z' })

describe('needsTwoFactor', () => {
    it('is true only for an account the policy names that has not enrolled', () => {
        expect(needsTwoFactor(account({ mfa_compliance: null }))).toBe(false)
        expect(needsTwoFactor(account({ mfa_compliance: { status: 'compliant', deadline: '2026-01-01T00:00:00Z' } }))).toBe(false)
        expect(needsTwoFactor(account({ mfa_compliance: grace() }))).toBe(true)
        expect(needsTwoFactor(account({ mfa_compliance: overdue() }))).toBe(true)
    })
})

describe('filterAccounts (two-factor compliance)', () => {
    it('the needsTwoFactor filter keeps only grace and overdue accounts', () => {
        const ok = account({ username: 'ok', mfa_compliance: null })
        const late = account({ username: 'late', mfa_compliance: overdue() })
        const soon = account({ username: 'soon', mfa_compliance: grace() })
        const result = filterAccounts([ok, late, soon], { ...DEFAULT_ACCOUNT_FILTERS, mfaCompliance: 'needsTwoFactor' })
        expect(result.map((a) => a.username).sort()).toEqual(['late', 'soon'])
    })
})
