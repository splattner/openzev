import type { Membership } from '../types/api'

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
