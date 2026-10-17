import { describe, expect, it } from 'vitest'
import { analyticsScopeOptions, credentialCounts, filterCredentials } from '../src/features/account/credentials'
import type { AccessCredential, Membership } from '../src/types/api'

const noScope = { zev: null, zev_name: null, participant: null, participant_name: null, metering_point: null, meter_id: null }
const credential = (kind: AccessCredential['kind'], id: string): AccessCredential => ({
    kind, id, name: id, prefix: 'x', access: 'read', scope: noScope, created_at: null, expires_at: null,
    last_used_at: null, status: 'active', actions: ['revoke'], manage_url: null,
})

const membership = (overrides: Partial<Membership>): Membership => ({
    zev: 'z1', zev_name: 'Sonnenhof', zev_disabled: false, zev_billing_interval: 'monthly',
    access: null, participants: [], ...overrides,
})

describe('credentialCounts / filterCredentials', () => {
    const all = [credential('api_key', 'a'), credential('api_key', 'b'), credential('analytics', 'c'), credential('energy_push', 'd')]

    it('counts per kind and in total', () => {
        expect(credentialCounts(all)).toEqual({ all: 4, api_key: 2, analytics: 1, energy_push: 1 })
    })

    it('filters by kind, and "all" keeps everything', () => {
        expect(filterCredentials(all, 'all')).toHaveLength(4)
        expect(filterCredentials(all, 'api_key').map((c) => c.id)).toEqual(['a', 'b'])
        expect(filterCredentials(all, 'energy_push').map((c) => c.id)).toEqual(['d'])
    })
})

describe('analyticsScopeOptions', () => {
    it('offers the whole community for a grant or a managing role, and own data per live participant', () => {
        const options = analyticsScopeOptions([
            membership({ zev: 'z1', access: 'viewer', participants: [{ id: 'p1', valid_from: '2025-01-01', valid_to: null, live: true }] }),
            membership({ zev: 'z2', zev_name: 'Dorf', roles: ['issuer'] }),
            membership({ zev: 'z3', zev_name: 'Nur Mieter', participants: [{ id: 'p3', valid_from: '2025-01-01', valid_to: null, live: true }] }),
        ])

        expect(options.map((o) => o.value)).toEqual(['zev:z1', 'participant:z1:p1', 'zev:z2', 'participant:z3:p3'])
        expect(options.find((o) => o.value === 'participant:z1:p1')).toMatchObject({ kind: 'participant', zev: 'z1', participant: 'p1' })
    })

    it('leaves out ended participant rows, disabled communities and a plain absence of access', () => {
        const options = analyticsScopeOptions([
            membership({ zev: 'z1', participants: [{ id: 'p1', valid_from: '2020-01-01', valid_to: '2021-01-01', live: false }] }),
            membership({ zev: 'z2', access: 'manager', zev_disabled: true }),
        ])

        expect(options).toEqual([])
    })

    it('offers an administrator every enabled community, once, whether or not they belong to it', () => {
        const options = analyticsScopeOptions(
            [membership({ zev: 'z1', zev_name: 'Sonnenhof', access: 'viewer' })],
            [
                { id: 'z9', name: 'Zeta', disabled_at: null },
                { id: 'z1', name: 'Sonnenhof', disabled_at: null },
                { id: 'z2', name: 'Alpha', disabled_at: null },
                { id: 'z3', name: 'Stillgelegt', disabled_at: '2026-01-01T00:00:00Z' },
            ],
        )

        expect(options.map((o) => o.value)).toEqual(['zev:z1', 'zev:z2', 'zev:z9'])
    })

    it('copes with no memberships', () => {
        expect(analyticsScopeOptions(undefined)).toEqual([])
    })
})
