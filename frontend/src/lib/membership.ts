import type { Membership, User } from '../types/api'

/**
 * How the signed-in account relates to one community (#761): an admin to
 * every community; otherwise through its grant there (`manager`, `viewer`) or
 * its participant rows (`participant` while one is current, else `former`).
 */
export type CommunityRelation = 'admin' | 'manager' | 'viewer' | 'participant' | 'former'

/** The relation an account has to a community, from its /auth/me membership. */
export function relationOf(membership: Membership): CommunityRelation {
    if (membership.access) return membership.access
    return membership.participants.some((row) => row.live) ? 'participant' : 'former'
}

/**
 * The account's community when it relates to exactly one — the label for
 * pages that list across every membership, where one name would otherwise
 * mislabel the scope.
 */
export function soleCommunityName(user: Pick<User, 'memberships'> | null | undefined): string | undefined {
    const memberships = user?.memberships ?? []
    return memberships.length === 1 ? memberships[0].zev_name : undefined
}
