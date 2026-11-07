import { useRef, useState, type FormEvent, type ReactNode } from 'react'
import type { TFunction } from 'i18next'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faEnvelope, faUserMinus } from '@fortawesome/free-solid-svg-icons'
import { CivilDateInput } from '../../components/CivilDateInput'
import { IssueText } from '../../components/IssueText'
import type { ActionMenuItem } from '../../components/ActionMenu'
import { ConfirmDialog, consumeReportedError, useConfirmDialog } from '../../components/ConfirmDialog'
import { createZevAccess, resendZevInvitation, revokeZevAccess, updateZevAccess } from '../../lib/api/zev'
import { formatApiError } from '../../lib/api/errors'
import { formatShortDate } from '../../lib/appSettings'
import { useAuth } from '../../lib/auth'
import { todayBusinessIso } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import type { Party, ZevAccessGrant, ZevAccessGrantInput, ZevAccessRole } from '../../types/api'

const ROLES: ZevAccessRole[] = ['manager', 'viewer']

function accountName(entry: ZevAccessGrant): string {
    return `${entry.user.first_name} ${entry.user.last_name}`.trim() || entry.user.email
}

/**
 * Give, change and take away access to a ZEV (#761) — the mutations every row
 * of the People & access tab shares, with their toasts and confirmations.
 * ``dialog`` must be rendered once by the caller.
 */
export function useAccessActions(zevId: string) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const { user, refreshUser } = useAuth()
    const queryClient = useQueryClient()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading } = useConfirmDialog()
    const failed = (error: unknown) => pushToast(formatApiError(error, t('pages.zevSettings.access.saveFailed')), 'error')

    /** After a change: reload access and parties, and the account itself when it was about us. */
    function afterChange(entry?: Pick<ZevAccessGrant, 'user'>) {
        void queryClient.invalidateQueries({ queryKey: ['zev', 'access', zevId] })
        void queryClient.invalidateQueries({ queryKey: ['zev', 'parties', zevId] })
        if (entry && entry.user.id === user?.id) void refreshUser()
    }

    const give = useMutation({
        mutationFn: (input: ZevAccessGrantInput) => createZevAccess(zevId, input),
        onSuccess: (created) => {
            afterChange(created)
            if (!created.email_sent) pushToast(t('pages.zevSettings.access.emailFailed'), 'error')
            else pushToast(t(created.user.pending_invitation ? 'pages.zevSettings.access.invited' : 'pages.zevSettings.access.granted'), 'success')
        },
        onError: failed,
    })
    const changeRole = useMutation({
        mutationFn: ({ grant, next }: { grant: ZevAccessGrant; next: ZevAccessRole }) => updateZevAccess(zevId, grant.id, { role: next }),
        onSuccess: (updated) => {
            afterChange(updated)
            pushToast(t('pages.zevSettings.access.roleChanged'), 'success')
        },
        onError: failed,
    })
    const resend = useMutation({
        mutationFn: (grant: ZevAccessGrant) => resendZevInvitation(zevId, grant.id),
        onSuccess: (result) => pushToast(
            t(result.email_sent ? 'pages.zevSettings.access.resent' : 'pages.zevSettings.access.emailFailed'),
            result.email_sent ? 'success' : 'error',
        ),
        onError: failed,
    })
    const revoke = useMutation({
        mutationFn: (grant: ZevAccessGrant) => revokeZevAccess(zevId, grant.id),
        onSuccess: (_, grant) => {
            afterChange(grant)
            pushToast(t('pages.zevSettings.access.revoked'), 'success')
        },
        onError: failed,
    })

    function toggleRole(grant: ZevAccessGrant) {
        const next: ZevAccessRole = grant.role === 'manager' ? 'viewer' : 'manager'
        if (next === 'manager') {
            changeRole.mutate({ grant, next })
            return
        }
        confirm({
            title: t('pages.zevSettings.access.downgradeTitle'),
            message: t('pages.zevSettings.access.downgradeMessage', { name: accountName(grant) }),
            confirmText: t('pages.zevSettings.access.makeViewer'),
            onConfirm: () => consumeReportedError(changeRole.mutateAsync({ grant, next })),
        })
    }

    function confirmRevoke(grant: ZevAccessGrant) {
        confirm({
            title: t('pages.zevSettings.access.revokeTitle'),
            message: t('pages.zevSettings.access.revokeMessage', { name: accountName(grant) }),
            confirmText: t('pages.zevSettings.access.revoke'),
            isDangerous: true,
            onConfirm: () => consumeReportedError(revoke.mutateAsync(grant)),
        })
    }

    const dialogElement: ReactNode = dialog
        ? <ConfirmDialog {...dialog} isLoading={isLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
        : null

    return {
        give,
        toggleRole,
        resend,
        confirmRevoke,
        dialog: dialogElement,
        busy: give.isPending || changeRole.isPending || resend.isPending || revoke.isPending,
    }
}

export type AccessActions = ReturnType<typeof useAccessActions>

export interface AccessDescription {
    /** What the person may do in OpenZEV, as quiet text: no controls. */
    status: ReactNode
    /** The one visible action, when there is access to give or an invitation to send. */
    primary: ReactNode
    /** Everything else, for the row's "…" menu. */
    menuItems: ActionMenuItem[]
}

interface DescribeAccessParams {
    t: TFunction
    settings: Parameters<typeof formatShortDate>[1]
    /** The access list rows of this person's logins (grants and role-derived entries). */
    entries: ZevAccessGrant[]
    /** The party the row shows, so access can be given to it; absent for a bare login. */
    party?: Party | null
    canManage: boolean
    actions: AccessActions
    /** The row is the holder of the issuer or representative role, which makes its login a manager. */
    managingRole?: boolean
    /** An address the row already shows (the contact's email, or a login used as the name), so a login with the same address is not repeated. */
    shownEmail?: string
    /** Open the give-access form for this party (the form decides the level). */
    onGive: (partyId: string) => void
}

/**
 * What a person on the People & access tab may do in OpenZEV, split for the
 * row it belongs to: the status as text, the one action that matters (give
 * access / invite) and the rest for the "…" menu — manager access a role
 * gives, a grant with its actions, or no access.
 */
export function describeAccess({
    t, settings, entries, party = null, canManage, actions, managingRole = false, shownEmail, onGive,
}: DescribeAccessParams): AccessDescription {
    const active = entries.filter((entry) => entry.is_active || entry.valid_from > todayBusinessIso())
    const byRole = active.filter((entry) => entry.source === 'role')
    const grants = active.filter((entry) => entry.source !== 'role')
    const login = active[0]?.user.email ?? party?.accounts[0]?.email
    const canInvite = Boolean(party && (party.accounts.length > 0 || party.email))

    const status = (
        <div className="party-access">
            {byRole.length > 0 && (
                <span className="party-access-line">
                    {/* On the issuer's and representative's own rows the heading already says the login manages. */}
                    {!managingRole && <span className="badge badge-tag">{t('pages.zevSettings.access.managesByRole')}</span>}
                    {login && login !== shownEmail && <span className="muted">{login}</span>}
                </span>
            )}
            {grants.map((grant) => (
                <span key={grant.id} className="party-access-line">
                    <span className="badge badge-tag">{t(`pages.zevSettings.access.level.${grant.role}`)}</span>
                    {grant.user.pending_invitation && <IssueText tone="warning">{t('pages.zevSettings.access.pending')}</IssueText>}
                    <span className="muted">
                        {grant.user.email !== shownEmail && grant.user.email}
                        {grant.valid_to && `${grant.user.email !== shownEmail ? ' · ' : ''}${t('pages.zevSettings.access.until', { date: formatShortDate(grant.valid_to, settings) })}`}
                    </span>
                </span>
            ))}
            {active.length === 0 && (
                <span className="party-access-line">
                    <span className="muted">
                        {party && party.accounts.length === 0 && !party.email
                            ? t('pages.zevSettings.access.noLoginNoEmail')
                            : managingRole
                                ? t('pages.zevSettings.access.noLoginRole')
                                : t('pages.zevSettings.access.none')}
                    </span>
                </span>
            )}
        </div>
    )

    const menuItems: ActionMenuItem[] = []
    if (canManage) {
        for (const grant of grants) {
            // With several logins on one person, the menu says which one an item is about.
            const section = grants.length > 1 ? grant.user.email : undefined
            menuItems.push({
                key: `level-${grant.id}`,
                label: t(grant.role === 'manager' ? 'pages.zevSettings.access.makeViewer' : 'pages.zevSettings.access.makeManager'),
                disabled: actions.busy,
                onClick: () => actions.toggleRole(grant),
                section,
            })
            if (grant.user.pending_invitation) {
                menuItems.push({
                    key: `resend-${grant.id}`,
                    label: t('pages.zevSettings.access.resend'),
                    icon: <FontAwesomeIcon icon={faEnvelope} fixedWidth />,
                    disabled: actions.busy,
                    onClick: () => actions.resend.mutate(grant),
                    section,
                })
            }
            menuItems.push({
                key: `revoke-${grant.id}`,
                label: t('pages.zevSettings.access.revoke'),
                icon: <FontAwesomeIcon icon={faUserMinus} fixedWidth />,
                danger: true,
                disabled: actions.busy,
                onClick: () => actions.confirmRevoke(grant),
                section,
            })
        }
    }

    let primary: ReactNode = null
    if (canManage && active.length === 0 && canInvite && party) {
        primary = (
            <button
                type="button"
                className="button button-secondary button-compact"
                disabled={actions.busy}
                onClick={() => (managingRole ? actions.give.mutate({ party: party.id, role: 'manager' }) : onGive(party.id))}
            >
                {t(managingRole || party.accounts.length === 0 ? 'pages.zevSettings.access.invite' : 'pages.zevSettings.access.add')}
            </button>
        )
    }

    return { status, primary, menuItems }
}

interface GiveAccessFormProps {
    parties: Party[]
    actions: AccessActions
    onDone: () => void
    /** A person whose row opened the form: access goes to them, only the level is left to choose. */
    initialPartyId?: string
}

/** Access for someone not on the page yet: a party of the ZEV or any email address. */
export function GiveAccessForm({ parties, actions, onDone, initialPartyId }: GiveAccessFormProps) {
    const { t } = useTranslation()
    const [target, setTarget] = useState<'party' | 'email'>(initialPartyId ? 'party' : 'email')
    const [partyId, setPartyId] = useState(initialPartyId ?? '')
    const [email, setEmail] = useState('')
    const [role, setRole] = useState<ZevAccessRole>('viewer')
    const [validTo, setValidTo] = useState('')
    const [errors, setErrors] = useState<{ email?: string; party?: string }>({})
    const emailRef = useRef<HTMLInputElement>(null)
    const partyRef = useRef<HTMLSelectElement>(null)

    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (target === 'email' && !email.trim()) {
            setErrors({ email: t('pages.zevSettings.access.emailRequired') })
            emailRef.current?.focus()
            return
        }
        if (target === 'party' && !partyId) {
            setErrors({ party: t('pages.zevSettings.access.partyRequired') })
            partyRef.current?.focus()
            return
        }
        setErrors({})
        actions.give.mutate(
            { ...(target === 'party' ? { party: partyId } : { email: email.trim() }), role, valid_to: validTo || null },
            { onSuccess: onDone },
        )
    }

    return (
        <form className="form-grid zev-access-form" noValidate onSubmit={submit}>
            <h4 className="zev-access-form-title grid-span-full">{t('pages.zevSettings.access.formTitle')}</h4>
            <label>
                <span>{t('pages.zevSettings.access.targetLabel')}</span>
                <select value={target} onChange={(event) => { setTarget(event.target.value as 'party' | 'email'); setErrors({}) }}>
                    <option value="email">{t('pages.zevSettings.access.targetEmail')}</option>
                    <option value="party">{t('pages.zevSettings.access.targetParty')}</option>
                </select>
            </label>
            {target === 'party' ? (
                <label>
                    <span>{t('pages.zevSettings.access.partyLabel')}</span>
                    <select
                        ref={partyRef}
                        value={partyId}
                        onChange={(event) => { setPartyId(event.target.value); setErrors({}) }}
                        aria-invalid={Boolean(errors.party)}
                        aria-describedby={errors.party ? 'zev-access-party-error' : undefined}
                    >
                        <option value="">{t('pages.zevSettings.parties.selectParty')}</option>
                        {parties.map((party) => (
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
                    {errors.party && <small className="field-error" id="zev-access-party-error" role="alert">{errors.party}</small>}
                </label>
            ) : (
                <label>
                    <span>{t('pages.zevSettings.access.emailLabel')}</span>
                    <input
                        ref={emailRef}
                        type="email"
                        value={email}
                        onChange={(event) => { setEmail(event.target.value); setErrors({}) }}
                        autoComplete="off"
                        aria-invalid={Boolean(errors.email)}
                        aria-describedby={errors.email ? 'zev-access-email-error' : undefined}
                    />
                    {errors.email && <small className="field-error" id="zev-access-email-error" role="alert">{errors.email}</small>}
                </label>
            )}
            <label>
                <span>{t('pages.zevSettings.access.roleLabel')}</span>
                <select value={role} onChange={(event) => setRole(event.target.value as ZevAccessRole)}>
                    {ROLES.map((value) => (
                        <option key={value} value={value}>{t(`pages.zevSettings.access.level.${value}`)}</option>
                    ))}
                </select>
            </label>
            <label>
                <span>{t('pages.zevSettings.access.validToLabel')}</span>
                <CivilDateInput value={validTo || null} onChange={(iso) => setValidTo(iso ?? '')} minDate={todayBusinessIso()} />
                <small className="muted">{t('pages.zevSettings.access.validToHint')}</small>
            </label>
            <p className="muted zev-access-form-hint grid-span-full">{t('pages.zevSettings.access.inviteHint')}</p>
            <div className="actions-row actions-row-wrap grid-span-full">
                <button type="submit" className="button button-primary" disabled={actions.give.isPending}>
                    {actions.give.isPending ? t('common.saving') : t('pages.zevSettings.access.give')}
                </button>
                <button type="button" className="button button-secondary" onClick={onDone}>{t('common.cancel')}</button>
            </div>
        </form>
    )
}
