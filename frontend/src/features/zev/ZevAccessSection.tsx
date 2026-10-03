import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faEnvelope, faPlus, faUserMinus } from '@fortawesome/free-solid-svg-icons'
import { CivilDateInput } from '../../components/CivilDateInput'
import { ConfirmDialog, useConfirmDialog } from '../../components/ConfirmDialog'
import { createZevAccess, fetchParties, fetchZevAccess, resendZevInvitation, revokeZevAccess, updateZevAccess } from '../../lib/api/zev'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { useAuth } from '../../lib/auth'
import { todayBusinessIso } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import type { ZevAccessGrant, ZevAccessRole } from '../../types/api'

interface Props {
    zevId: string
    /** Give, change and take away access. A viewer (or a disabled ZEV) only sees the list. */
    canManage: boolean
    /** Open the form for this party ("Give access" on a contact); a new object each time it is asked for. */
    request?: { partyId: string } | null
}

const ROLES: ZevAccessRole[] = ['manager', 'viewer']

function displayName(grant: ZevAccessGrant): string {
    const name = `${grant.user.first_name} ${grant.user.last_name}`.trim()
    return name || grant.user.email
}

/**
 * Who may manage or view this ZEV (#761, SPEC-2026-10-zev-access-grants §9.6).
 * Managers and admins give access to a party of the ZEV or to an email address
 * — a party or address without an account gets an invitation — change a
 * manager into a viewer or back, resend an invitation nobody has accepted yet,
 * and take access away. The last manager cannot be removed; the server says so
 * and the message is shown as is. Accounts that manage the ZEV because their
 * party is issuer or representative are listed too, read-only: that access
 * changes with the role in the Parties tab (ADR 0028, amended).
 */
export function ZevAccessSection({ zevId, canManage, request = null }: Props) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { pushToast } = useToast()
    const { user, refreshUser } = useAuth()
    const queryClient = useQueryClient()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const [includeEnded, setIncludeEnded] = useState(false)
    const [isAdding, setIsAdding] = useState(false)
    const [target, setTarget] = useState<'party' | 'email'>('party')
    const [partyId, setPartyId] = useState('')
    const [email, setEmail] = useState('')
    const [role, setRole] = useState<ZevAccessRole>('viewer')
    const [validTo, setValidTo] = useState('')
    // A contact's "Give access" opens the form with that party chosen.
    const [seenRequest, setSeenRequest] = useState(request)
    if (request !== seenRequest) {
        setSeenRequest(request)
        if (request) {
            setIsAdding(true)
            setTarget('party')
            setPartyId(request.partyId)
        }
    }

    const partiesQuery = useQuery({
        queryKey: queryKeys.zev.parties(zevId),
        queryFn: () => fetchParties(zevId),
        enabled: Boolean(zevId) && canManage && isAdding,
    })

    const accessQuery = useQuery({
        queryKey: queryKeys.zev.access(zevId, includeEnded),
        queryFn: () => fetchZevAccess(zevId, { includeEnded }),
        enabled: Boolean(zevId),
    })

    /** After a change: reload the list, and the account itself when it was about us. */
    function afterChange(grant?: Pick<ZevAccessGrant, 'user'>) {
        void queryClient.invalidateQueries({ queryKey: ['zev', 'access', zevId] })
        if (grant && grant.user.id === user?.id) void refreshUser()
    }

    const createMutation = useMutation({
        mutationFn: () => createZevAccess(zevId, {
            ...(target === 'party' ? { party: partyId } : { email: email.trim() }),
            role,
            valid_to: validTo || null,
        }),
        onSuccess: (created) => {
            setIsAdding(false)
            setEmail('')
            setPartyId('')
            void queryClient.invalidateQueries({ queryKey: ['zev', 'parties', zevId] })
            setRole('viewer')
            setValidTo('')
            afterChange(created)
            if (!created.email_sent) {
                pushToast(t('pages.zevSettings.access.emailFailed'), 'error')
            } else {
                pushToast(
                    t(created.user.pending_invitation ? 'pages.zevSettings.access.invited' : 'pages.zevSettings.access.granted'),
                    'success',
                )
            }
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.zevSettings.access.saveFailed')), 'error'),
    })

    const roleMutation = useMutation({
        mutationFn: ({ grant, next }: { grant: ZevAccessGrant; next: ZevAccessRole }) =>
            updateZevAccess(zevId, grant.id, { role: next }),
        onSuccess: (updated) => {
            afterChange(updated)
            pushToast(t('pages.zevSettings.access.roleChanged'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.zevSettings.access.saveFailed')), 'error'),
    })

    const resendMutation = useMutation({
        mutationFn: (grant: ZevAccessGrant) => resendZevInvitation(zevId, grant.id),
        onSuccess: (result) =>
            pushToast(
                t(result.email_sent ? 'pages.zevSettings.access.resent' : 'pages.zevSettings.access.emailFailed'),
                result.email_sent ? 'success' : 'error',
            ),
        onError: (error) => pushToast(formatApiError(error, t('pages.zevSettings.access.saveFailed')), 'error'),
    })

    const revokeMutation = useMutation({
        mutationFn: (grant: ZevAccessGrant) => revokeZevAccess(zevId, grant.id),
        onSuccess: (_, grant) => {
            afterChange(grant)
            pushToast(t('pages.zevSettings.access.revoked'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.zevSettings.access.saveFailed')), 'error'),
    })

    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (target === 'email' && !email.trim()) {
            pushToast(t('pages.zevSettings.access.emailRequired'), 'error')
            return
        }
        if (target === 'party' && !partyId) {
            pushToast(t('pages.zevSettings.access.partyRequired'), 'error')
            return
        }
        createMutation.mutate()
    }

    function confirmRoleChange(grant: ZevAccessGrant) {
        const next: ZevAccessRole = grant.role === 'manager' ? 'viewer' : 'manager'
        if (next === 'manager') {
            roleMutation.mutate({ grant, next })
            return
        }
        confirm({
            title: t('pages.zevSettings.access.downgradeTitle'),
            message: t('pages.zevSettings.access.downgradeMessage', { name: displayName(grant) }),
            confirmText: t('pages.zevSettings.access.makeViewer'),
            onConfirm: () => roleMutation.mutateAsync({ grant, next }).then(() => undefined),
        })
    }

    function confirmRevoke(grant: ZevAccessGrant) {
        confirm({
            title: t('pages.zevSettings.access.revokeTitle'),
            message: t('pages.zevSettings.access.revokeMessage', { name: displayName(grant) }),
            confirmText: t('pages.zevSettings.access.revoke'),
            isDangerous: true,
            onConfirm: () => revokeMutation.mutateAsync(grant).then(() => undefined),
        })
    }

    // One row per login: access through the issuer or representative role is
    // shown on the same login's grant row when it has one, else as its own row.
    const entries = accessQuery.data ?? []
    const grantRows = entries.filter((entry) => entry.source !== 'role')
    const rolesByRow = new Map<string, ZevAccessGrant[]>()
    const grants: ZevAccessGrant[] = [...grantRows]
    for (const entry of entries.filter((item) => item.source === 'role')) {
        const host = grantRows.find((row) => row.user.id === entry.user.id && row.is_active)
        if (host) {
            rolesByRow.set(host.id, [...(rolesByRow.get(host.id) ?? []), entry])
        } else {
            grants.push(entry)
            rolesByRow.set(entry.id, [entry])
        }
    }
    const today = todayBusinessIso()
    const busy = createMutation.isPending || roleMutation.isPending || resendMutation.isPending || revokeMutation.isPending

    return (
        <section className="card page-stack" id="zev-access-section">
            <div>
                <h3 style={{ marginTop: 0 }}>{t('pages.zevSettings.access.title')}</h3>
                <p className="muted" style={{ margin: 0 }}>{t('pages.zevSettings.access.description')}</p>
            </div>

            {canManage && (isAdding ? (
                <form className="form-grid zev-access-form" onSubmit={submit}>
                    <label>
                        <span>{t('pages.zevSettings.access.targetLabel')}</span>
                        <select value={target} onChange={(event) => setTarget(event.target.value as 'party' | 'email')}>
                            <option value="party">{t('pages.zevSettings.access.targetParty')}</option>
                            <option value="email">{t('pages.zevSettings.access.targetEmail')}</option>
                        </select>
                    </label>
                    {target === 'party' ? (
                        <label>
                            <span>{t('pages.zevSettings.access.partyLabel')}</span>
                            <select value={partyId} onChange={(event) => setPartyId(event.target.value)}>
                                <option value="">{t('pages.zevSettings.parties.selectParty')}</option>
                                {(partiesQuery.data ?? []).map((party) => (
                                    <option key={party.id} value={party.id} disabled={party.accounts.length === 0 && !party.email}>
                                        {party.display_name}
                                        {' — '}
                                        {party.accounts[0]?.email
                                            ?? (party.email
                                                ? t('pages.zevSettings.access.partyInvite', { email: party.email })
                                                : t('pages.zevSettings.access.partyNoEmail'))}
                                    </option>
                                ))}
                            </select>
                        </label>
                    ) : (
                        <label>
                            <span>{t('pages.zevSettings.access.emailLabel')}</span>
                            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="off" />
                        </label>
                    )}
                    <label>
                        <span>{t('pages.zevSettings.access.roleLabel')}</span>
                        <select value={role} onChange={(event) => setRole(event.target.value as ZevAccessRole)}>
                            {ROLES.map((value) => (
                                <option key={value} value={value}>{t(`nav.relation.${value}`)}</option>
                            ))}
                        </select>
                    </label>
                    <label>
                        <span>{t('pages.zevSettings.access.validToLabel')}</span>
                        <CivilDateInput value={validTo || null} onChange={(iso) => setValidTo(iso ?? '')} minDate={todayBusinessIso()} />
                        <small className="muted">{t('pages.zevSettings.access.validToHint')}</small>
                    </label>
                    <p className="muted zev-access-form-hint">{t('pages.zevSettings.access.inviteHint')}</p>
                    <div className="actions-row actions-row-wrap">
                        <button type="submit" className="button button-primary" disabled={createMutation.isPending}>
                            {createMutation.isPending ? t('common.saving') : t('pages.zevSettings.access.give')}
                        </button>
                        <button type="button" className="button button-secondary" onClick={() => setIsAdding(false)}>
                            {t('common.cancel')}
                        </button>
                    </div>
                </form>
            ) : (
                <div className="actions-row">
                    <button type="button" className="button button-primary" onClick={() => setIsAdding(true)}>
                        <FontAwesomeIcon icon={faPlus} fixedWidth />
                        {t('pages.zevSettings.access.add')}
                    </button>
                </div>
            ))}

            <label className="zev-access-toggle">
                <input type="checkbox" checked={includeEnded} onChange={(event) => setIncludeEnded(event.target.checked)} />
                <span>{t('pages.zevSettings.access.showEnded')}</span>
            </label>

            {accessQuery.isLoading && <p className="muted">{t('common.loading')}</p>}
            {accessQuery.isError && <p className="error-banner">{t('common.error')}</p>}

            {grants.length > 0 && (
                <ul className="zev-access-list" aria-label={t('pages.zevSettings.access.title')}>
                    {grants.map((grant) => {
                        const ended = grant.valid_to !== null && grant.valid_to < today
                        const byRole = grant.source === 'role'
                        const viaRoles = (rolesByRow.get(grant.id) ?? []).filter((entry) => entry.party_role)
                        const actionable = canManage && !ended && !byRole
                        return (
                            <li key={grant.id} className="zev-access-row">
                                <div className="zev-access-who">
                                    <strong>{displayName(grant)}</strong>
                                    <span className="muted">{grant.user.email}</span>
                                    <span className="zev-access-badges">
                                        <span className={`badge ${grant.role === 'manager' ? 'badge-info' : 'badge-neutral'}`}>
                                            {t(`nav.relation.${grant.role}`)}
                                        </span>
                                        {viaRoles.map((entry) => (
                                            <span key={entry.id} className="badge badge-neutral">
                                                {t('pages.zevSettings.access.byRole', { role: t(`pages.participants.roles.${entry.party_role!.role}`) })}
                                            </span>
                                        ))}
                                        {grant.user.pending_invitation && (
                                            <span className="badge badge-warning">{t('pages.zevSettings.access.pending')}</span>
                                        )}
                                        {ended && <span className="badge badge-neutral">{t('pages.zevSettings.access.ended')}</span>}
                                    </span>
                                </div>
                                <div className="zev-access-meta muted">
                                    <span>
                                        {t('pages.zevSettings.access.since', { date: formatShortDate(grant.valid_from, settings) })}
                                        {grant.valid_to && ` · ${t('pages.zevSettings.access.until', { date: formatShortDate(grant.valid_to, settings) })}`}
                                    </span>
                                    {grant.granted_by && (
                                        <span>{t('pages.zevSettings.access.grantedBy', { name: grant.granted_by.full_name })}</span>
                                    )}
                                    {viaRoles.map((entry) => (
                                        <span key={entry.id}>{t('pages.zevSettings.access.byRoleHint', { name: entry.party_role!.party_display_name })}</span>
                                    ))}
                                </div>
                                {actionable && (
                                    <div className="zev-access-actions actions-row actions-row-wrap">
                                        <button
                                            type="button"
                                            className="button button-secondary button-compact"
                                            disabled={busy}
                                            onClick={() => confirmRoleChange(grant)}
                                        >
                                            {t(grant.role === 'manager' ? 'pages.zevSettings.access.makeViewer' : 'pages.zevSettings.access.makeManager')}
                                        </button>
                                        {grant.user.pending_invitation && (
                                            <button
                                                type="button"
                                                className="button button-secondary button-compact"
                                                disabled={busy}
                                                onClick={() => resendMutation.mutate(grant)}
                                            >
                                                <FontAwesomeIcon icon={faEnvelope} fixedWidth />
                                                {t('pages.zevSettings.access.resend')}
                                            </button>
                                        )}
                                        <button
                                            type="button"
                                            className="button button-danger button-compact"
                                            disabled={busy}
                                            onClick={() => confirmRevoke(grant)}
                                        >
                                            <FontAwesomeIcon icon={faUserMinus} fixedWidth />
                                            {t('pages.zevSettings.access.revoke')}
                                        </button>
                                    </div>
                                )}
                            </li>
                        )
                    })}
                </ul>
            )}

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
        </section>
    )
}
