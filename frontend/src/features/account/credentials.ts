import type { AccessCredential, CredentialKind, Membership, Zev } from '../../types/api'

export type CredentialFilter = 'all' | CredentialKind

/** Counts per filter chip, in the order the chips are shown. */
export function credentialCounts(credentials: AccessCredential[]): Record<CredentialFilter, number> {
    return {
        all: credentials.length,
        api_key: credentials.filter((c) => c.kind === 'api_key').length,
        analytics: credentials.filter((c) => c.kind === 'analytics').length,
        energy_push: credentials.filter((c) => c.kind === 'energy_push').length,
    }
}

export function filterCredentials(credentials: AccessCredential[], filter: CredentialFilter): AccessCredential[] {
    return filter === 'all' ? credentials : credentials.filter((c) => c.kind === filter)
}

/** What an analytics token can be limited to: a whole community, or only one's own data in it. */
export interface AnalyticsScopeOption {
    /** `zev:<zev id>` or `participant:<zev id>:<participant id>` */
    value: string
    kind: 'zev' | 'participant'
    zev: string
    zevName: string
    participant?: string
}

/**
 * The scopes the signed-in account may create an analytics token for: the whole
 * community where it holds a grant or role (view or more), and its own data for
 * every participant record that is still current. A disabled community offers none.
 */
export function analyticsScopeOptions(
    memberships: Membership[] | undefined,
    /** An administrator may read any community: every enabled one is offered, not only those they belong to. */
    allZevs?: Array<Pick<Zev, 'id' | 'name' | 'disabled_at'>>,
): AnalyticsScopeOption[] {
    const options: AnalyticsScopeOption[] = []
    for (const membership of memberships ?? []) {
        if (membership.zev_disabled) continue
        if (membership.access || (membership.roles?.length ?? 0) > 0) {
            options.push({ value: `zev:${membership.zev}`, kind: 'zev', zev: membership.zev, zevName: membership.zev_name })
        }
        for (const participant of membership.participants) {
            if (!participant.live) continue
            options.push({
                value: `participant:${membership.zev}:${participant.id}`,
                kind: 'participant',
                zev: membership.zev,
                zevName: membership.zev_name,
                participant: participant.id,
            })
        }
    }
    const offered = new Set(options.map((option) => option.value))
    const rest = [...(allZevs ?? [])]
        .filter((zev) => !zev.disabled_at && !offered.has(`zev:${zev.id}`))
        .sort((a, b) => a.name.localeCompare(b.name))
    for (const zev of rest) {
        options.push({ value: `zev:${zev.id}`, kind: 'zev', zev: zev.id, zevName: zev.name })
    }
    return options
}
