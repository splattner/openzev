import { useTranslation } from 'react-i18next'
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
    /** Role capability: admin or manager. Does not consider whether the selected community permits writes. */
    canManage: boolean
    /** Effective write availability in the selected community: role capability plus community state. */
    canWriteSelectedCommunity: boolean
    /** Show the participant view: participant, or former participant (invoices only). */
    isParticipantScope: boolean
    isAdmin: boolean
}

export function accessFor(shellRole: ShellRole): CommunityAccess {
    const canManage = shellRole === 'admin' || shellRole === 'manager'
    const isAdmin = shellRole === 'admin'
    return {
        shellRole,
        isZevScope: shellRole === 'admin' || shellRole === 'manager' || shellRole === 'viewer',
        canManage,
        // Without a ZEV record there is nothing to disable; callers with a
        // record use canWriteInSelectedCommunity() instead.
        canWriteSelectedCommunity: canManage,
        isParticipantScope: shellRole === 'participant' || shellRole === 'former',
        isAdmin,
    }
}

/**
 * Effective write availability for a selected community: role capability,
 * plus the community permitting writes. A manager keeps read access to a
 * disabled ZEV but loses write access; an admin can still write. A missing
 * record is not writable for a manager: callers must have a resolved
 * community before offering writes.
 */
export function canWriteInSelectedCommunity(
    access: Pick<CommunityAccess, 'canManage' | 'isAdmin'>,
    selectedZev: { disabled_at?: string | null } | null | undefined,
): boolean {
    return access.canManage && (access.isAdmin || (!!selectedZev && !selectedZev.disabled_at))
}

/**
 * The signed-in account's access to the selected community.
 */
export function useCommunityAccess(): CommunityAccess {
    const auth = useAuth()
    // The outer authentication route runs before ManagedZevProvider mounts.
    const managed = useOptionalManagedZev()
    const base = accessFor(shellRoleFor(auth.user, managed?.relation))
    return {
        ...base,
        canWriteSelectedCommunity: canWriteInSelectedCommunity(base, managed?.selectedZev ?? null),
    }
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

/**
 * Whether the account manages or views at least one community (or is an admin): the accounts that
 * can read live invoices. A participant reads what was delivered to them instead (#862).
 */
export function hasCommunityWideAccess(user: User | null | undefined): boolean {
    if (!user) return false
    return user.role === 'admin'
        || (user.memberships ?? []).some((membership) => !!membership.access || (membership.roles?.length ?? 0) > 0)
}

/** The account's shell role for a given community. */
export function shellRoleForZev(user: User | null | undefined, zevId: string | null | undefined): ShellRole {
    return shellRoleFor(user, relationToZev(user, zevId))
}

/**
 * The note beside a page's community name: read-only access for a viewer
 * (the switcher's own label), nothing for anyone who can act there.
 */
export function scopeNoteKey(shellRole: ShellRole): string | undefined {
    return shellRole === 'viewer' ? 'nav.relation.viewer' : undefined
}

/** The selected community's scope note, translated. */
export function useScopeNote(): string | undefined {
    const { t } = useTranslation()
    const key = scopeNoteKey(useCommunityAccess().shellRole)
    return key ? t(key) : undefined
}
