import { useAuth } from './auth'
import { useOptionalManagedZev } from './managedZev'
import { relationOf, type CommunityRelation } from './membership'
import type { User } from '../types/api'

/**
 * What the shell shows for the selected community (#761): the management view
 * (`admin`, `manager`, `viewer`), the participant view (`participant`, or only
 * the invoices for a `former` participant), or nothing (`none`).
 */
export type ShellRole = CommunityRelation | 'none'

/**
 * The account's shell role. An admin is always `admin`; anyone else has the
 * relation to the selected community, or `none` without one.
 */
export function shellRoleFor(user: Pick<User, 'role'> | null | undefined, relation?: CommunityRelation): ShellRole {
    if (!user) return 'none'
    if (user.role === 'admin') return 'admin'
    return relation ?? 'none'
}

export interface CommunityAccess {
    shellRole: ShellRole
    /** Show the selected community's management view (read): admin, manager, viewer. */
    isZevScope: boolean
    /** Offer writes in the selected community: admin or manager. A viewer reads only. */
    canManage: boolean
    /** Show the participant view: participant, or former participant (invoices only). */
    isParticipantScope: boolean
    isAdmin: boolean
}

export function accessFor(shellRole: ShellRole): CommunityAccess {
    return {
        shellRole,
        isZevScope: shellRole === 'admin' || shellRole === 'manager' || shellRole === 'viewer',
        canManage: shellRole === 'admin' || shellRole === 'manager',
        isParticipantScope: shellRole === 'participant' || shellRole === 'former',
        isAdmin: shellRole === 'admin',
    }
}

/**
 * The signed-in account's access to the selected community.
 */
export function useCommunityAccess(): CommunityAccess {
    const auth = useAuth()
    // The outer authentication route runs before ManagedZevProvider mounts.
    const managed = useOptionalManagedZev()
    return accessFor(shellRoleFor(auth.user, managed?.relation))
}

/**
 * The account's relation to a given community — for pages about one record
 * (an invoice) that may belong to a community other than the selected one.
 * `undefined` when the account holds nothing there.
 */
export function relationToZev(user: User | null | undefined, zevId: string | null | undefined): CommunityRelation | undefined {
    if (!user) return undefined
    if (user.role === 'admin') return 'admin'
    const membership = zevId ? user.memberships?.find((entry) => entry.zev === zevId) : undefined
    return membership ? relationOf(membership) : undefined
}

/** The account's shell role for a given community. */
export function shellRoleForZev(user: User | null | undefined, zevId: string | null | undefined): ShellRole {
    return shellRoleFor(user, relationToZev(user, zevId))
}
