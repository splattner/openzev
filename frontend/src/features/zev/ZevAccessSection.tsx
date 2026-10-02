import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faEnvelope, faPlus, faUserMinus } from '@fortawesome/free-solid-svg-icons'
import { ConfirmDialog, useConfirmDialog } from '../../components/ConfirmDialog'
import { createZevAccess, fetchZevAccess, resendZevInvitation, revokeZevAccess, updateZevAccess } from '../../lib/api/zev'
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
}

const ROLES: ZevAccessRole[] = ['manager', 'viewer']

function displayName(grant: ZevAccessGrant): string {
    const name = `${grant.user.first_name} ${grant.user.last_name}`.trim()
    return name || grant.user.email
}

/**
 * Who may manage or view this ZEV (#761, SPEC-2026-10-zev-access-grants §9.6).
 * Managers and admins give access by email — an address without an account
 * gets an invitation — change a manager into a viewer or back, resend an
 * invitation nobody has accepted yet, and take access away. The last manager
 * cannot be removed; the server says so and the message is shown as is.
 */
export function ZevAccessSection({ zevId, canManage }: Props) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { pushToast } = useToast()
    const { user, refreshUser } = useAuth()
    const queryClient = useQueryClient()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const [includeEnded, setIncludeEnded] = useState(false)
    const [isAdding, setIsAdding] = useState(false)
    const [email, setEmail] = useState('')
    const [role, setRole] = useState<ZevAccessRole>('viewer')
    const [validTo, setValidTo] = useState('')

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
        mutationFn: () => createZevAccess(zevId, { email: email.trim(), role, valid_to: validTo || null }),
        onSuccess: (created) => {
            setIsAdding(false)
            setEmail('')
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
        if (!email.trim()) {
            pushToast(t('pages.zevSettings.access.emailRequired'), 'error')
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

    const grants = accessQuery.data ?? []
    const today = todayBusinessIso()
    const busy = createMutation.isPending || roleMutation.isPending || resendMutation.isPending || revokeMutation.isPending

    return (
        <section className="card page-stack">
            <div>
                <h3 style={{ marginTop: 0 }}>{t('pages.zevSettings.access.title')}</h3>
                <p className="muted" style={{ margin: 0 }}>{t('pages.zevSettings.access.description')}</p>
            </div>

            {canManage && (isAdding ? (
                <form className="form-grid zev-access-form" onSubmit={submit}>
                    <label>
                        <span>{t('pages.zevSettings.access.emailLabel')}</span>
                        <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="off" />
                    </label>
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
                        <input type="date" value={validTo} onChange={(event) => setValidTo(event.target.value)} />
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
                        const actionable = canManage && !ended
                        return (
                            <li key={grant.id} className="zev-access-row">
                                <div className="zev-access-who">
                                    <strong>{displayName(grant)}</strong>
                                    <span className="muted">{grant.user.email}</span>
                                    <span className="zev-access-badges">
                                        <span className={`badge ${grant.role === 'manager' ? 'badge-info' : 'badge-neutral'}`}>
                                            {t(`nav.relation.${grant.role}`)}
                                        </span>
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
