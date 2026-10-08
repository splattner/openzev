import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faBan, faCheck, faCirclePlus, faClockRotateLeft, faEllipsis, faPen, faPlay, faRightFromBracket, faShieldHalved, faTrash, faUser, faXmark,
} from '@fortawesome/free-solid-svg-icons'
import { useMemo, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ActionMenu } from '../components/ActionMenu'
import { ConfirmDialog, consumeReportedError, useConfirmDialog } from '../components/ConfirmDialog'
import { StatCard } from '../components/StatCard'
import { FormModal } from '../components/FormModal'
import { AccountCreatedNotice, type AccountCreatedNoticeData } from '../features/accounts/AccountCreatedNotice'
import { AccountMemberships } from '../features/accounts/AccountMemberships'
import { AccountMfaComplianceBadge } from '../features/accounts/AccountMfaComplianceBadge'
import {
    DEFAULT_ACCOUNT_FILTERS,
    accountDisplayName,
    accountStats,
    canDeleteAccount,
    canImpersonateAccount,
    filterAccounts,
    hasActiveFilters,
    type AccountFilters,
} from '../features/accounts/accountList'
import { fetchZevs } from '../lib/api/zev'
import { createUser, deleteUser, fetchUsers, resetUserMfa, revokeUserSessions, updateUser } from '../lib/api/auth'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { formatDateTime, useAppSettings } from '../lib/appSettings'
import { useToast } from '../lib/toast'
import type { AdminUser, CreateUserInput, UserInput, UserRole } from '../types/api'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '../components/PageSkeleton'
import { Notice } from '../components/Notice'

const defaultEditUserForm: UserInput = {
    username: '',
    email: '',
    first_name: '',
    last_name: '',
    role: 'user',
    must_change_password: false,
}

const defaultCreateUserForm: CreateUserInput = {
    username: '',
    email: '',
    first_name: '',
    last_name: '',
    role: 'user',
}

const ROLES: UserRole[] = ['admin', 'user']

/**
 * Every account on the platform, one row each, with the communities it belongs
 * to. Account-level concerns live here — platform role, sign-in security,
 * impersonation, deletion. Which participant an account is tied to is managed
 * on that community's Participants page; the membership chips lead there.
 *
 * `embedded` drops the page header (mounted inside the admin Accounts hub;
 * /admin/accounts stays as a deep-link alias).
 */
export function AdminAccountsPage({ embedded = false }: { embedded?: boolean }) {
    const queryClient = useQueryClient()
    const { user: currentUser, startImpersonation, logout } = useAuth()
    const { pushToast } = useToast()
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const navigate = useNavigate()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const usersQuery = useQuery({ queryKey: queryKeys.auth.users(), queryFn: fetchUsers })
    const zevsQuery = useQuery({ queryKey: queryKeys.zev.list(), queryFn: fetchZevs })

    const [filters, setFilters] = useState<AccountFilters>(DEFAULT_ACCOUNT_FILTERS)

    const [showEditUserModal, setShowEditUserModal] = useState(false)
    const [editingUserId, setEditingUserId] = useState<number | null>(null)
    const [editUserForm, setEditUserForm] = useState<UserInput>(defaultEditUserForm)
    const [editUserError, setEditUserError] = useState<string | null>(null)

    const [showCreateUserModal, setShowCreateUserModal] = useState(false)
    const [createUserForm, setCreateUserForm] = useState<CreateUserInput>(defaultCreateUserForm)
    const [createUserError, setCreateUserError] = useState<string | null>(null)
    const [createdNotice, setCreatedNotice] = useState<AccountCreatedNoticeData | null>(null)

    const createUserMutation = useMutation({
        mutationFn: (payload: CreateUserInput) => createUser(payload),
        onSuccess: (created) => {
            setShowCreateUserModal(false)
            setCreateUserForm(defaultCreateUserForm)
            setCreateUserError(null)
            setCreatedNotice({ username: created.username, password: created.generated_password })
            pushToast(t('pages.accounts.feedback.createSuccess'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.users() })
        },
        onError: (error) => setCreateUserError(formatApiError(error, t('pages.accounts.feedback.createFailed'))),
    })

    const updateUserMutation = useMutation({
        mutationFn: ({ userId, payload }: { userId: number; payload: Partial<UserInput> }) => updateUser(userId, payload),
        onSuccess: () => {
            setShowEditUserModal(false)
            setEditingUserId(null)
            setEditUserForm(defaultEditUserForm)
            setEditUserError(null)
            pushToast(t('pages.accounts.feedback.updateSuccess'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.users() })
        },
        onError: (error) => setEditUserError(formatApiError(error, t('pages.accounts.feedback.updateFailed'))),
    })

    const activationMutation = useMutation({
        mutationFn: ({ userId, active }: { userId: number; active: boolean }) => updateUser(userId, { is_active: active }),
        onSuccess: () => {
            pushToast(t('pages.accounts.feedback.updateSuccess'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.users() })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.accounts.feedback.updateFailed')), 'error'),
    })

    const deleteUserMutation = useMutation({
        mutationFn: (userId: number) => deleteUser(userId),
        onSuccess: (_data, deletedUserId) => {
            pushToast(t('pages.accounts.feedback.deleteSuccess'), 'success')
            if (deletedUserId === currentUser?.id) {
                logout()
                return
            }
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.users() })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.accounts.feedback.deleteFailed')), 'error'),
    })

    // Removing a user's second factors is the way out for someone locked out
    // (spec 2026-09-two-factor-authentication.md, D3). Audited server-side.
    const resetMfaMutation = useMutation({
        mutationFn: (userId: number) => resetUserMfa(userId),
        onSuccess: () => {
            pushToast(t('pages.accounts.feedback.resetMfaSuccess'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.users() })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.accounts.feedback.resetMfaFailed')), 'error'),
    })

    // Ends every session the account holds — for a suspected compromise. Audited server-side.
    const revokeSessionsMutation = useMutation({
        mutationFn: (userId: number) => revokeUserSessions(userId),
        onSuccess: () => pushToast(t('pages.accounts.feedback.signOutSuccess'), 'success'),
        onError: (error) => pushToast(formatApiError(error, t('pages.accounts.feedback.signOutFailed')), 'error'),
    })

    const impersonationMutation = useMutation({
        mutationFn: async (userId: number) => {
            await startImpersonation(userId)
        },
        onSuccess: () => pushToast(t('pages.accounts.feedback.impersonationSuccess'), 'success'),
        onError: (error) => pushToast(formatApiError(error, t('pages.accounts.feedback.impersonationFailed')), 'error'),
    })

    const accounts = usersQuery.data
    const visibleAccounts = useMemo(() => filterAccounts(accounts ?? [], filters), [accounts, filters])
    const stats = useMemo(() => accountStats(accounts ?? []), [accounts])

    function roleLabel(role: UserRole) {
        return t(`pages.accounts.roles.${role}` as Parameters<typeof t>[0], { defaultValue: role })
    }

    function confirmResetMfa(account: AdminUser) {
        confirm({
            title: t('pages.accounts.resetMfaTitle'),
            message: t('pages.accounts.resetMfaMessage', { username: account.username }),
            confirmText: t('pages.accounts.resetMfaConfirm'),
            cancelText: t('common.cancel'),
            isDangerous: true,
            onConfirm: () => consumeReportedError(resetMfaMutation.mutateAsync(account.id)),
        })
    }

    function confirmSignOut(account: AdminUser) {
        confirm({
            title: t('pages.accounts.signOutTitle'),
            message: t('pages.accounts.signOutMessage', { username: account.username }),
            confirmText: t('pages.accounts.signOutConfirm'),
            cancelText: t('common.cancel'),
            isDangerous: true,
            onConfirm: () => consumeReportedError(revokeSessionsMutation.mutateAsync(account.id)),
        })
    }

    function confirmImpersonate(account: AdminUser) {
        confirm({
            title: t('pages.accounts.impersonateTitle'),
            message: t('pages.accounts.impersonateMessage', { name: accountDisplayName(account) }),
            confirmText: t('pages.accounts.impersonateConfirm'),
            cancelText: t('common.cancel'),
            onConfirm: () => consumeReportedError(impersonationMutation.mutateAsync(account.id)),
        })
    }

    function confirmSetActive(account: AdminUser, active: boolean) {
        if (active) {
            // Reactivating is reversible and expected — no confirmation needed.
            activationMutation.mutate({ userId: account.id, active: true })
            return
        }
        confirm({
            title: t('pages.accounts.deactivateTitle'),
            message: t('pages.accounts.deactivateMessage', { username: account.username }),
            confirmText: t('pages.accounts.deactivateConfirm'),
            cancelText: t('common.cancel'),
            isDangerous: true,
            onConfirm: () => consumeReportedError(activationMutation.mutateAsync({ userId: account.id, active: false })),
        })
    }

    function viewActivity(account: AdminUser) {
        // The platform audit log (admin-only, same as this page), pre-filtered
        // to this account's own actions as actor. actorUsername only fills the
        // filter dropdown's label for an account with no prior audit history —
        // AuditLogsPage reads and then drops both params.
        navigate(`/admin/audit?actor=${account.id}&actorUsername=${encodeURIComponent(account.username)}`)
    }

    function confirmDelete(account: AdminUser) {
        confirm({
            title: t('pages.accounts.deleteTitle'),
            message: t('pages.accounts.deleteMessage', { username: account.username }),
            confirmText: t('pages.accounts.deleteConfirm'),
            cancelText: t('common.cancel'),
            isDangerous: true,
            onConfirm: () => consumeReportedError(deleteUserMutation.mutateAsync(account.id)),
        })
    }

    function openEditUserModal(account: AdminUser) {
        setEditingUserId(account.id)
        setEditUserForm({
            username: account.username,
            email: account.email || '',
            first_name: account.first_name || '',
            last_name: account.last_name || '',
            role: account.role,
            must_change_password: account.must_change_password,
        })
        setEditUserError(null)
        setShowEditUserModal(true)
    }

    function submitCreateUser(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        createUserMutation.mutate(createUserForm)
    }

    function submitEditUser(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!editingUserId) {
            return
        }
        updateUserMutation.mutate({ userId: editingUserId, payload: editUserForm })
    }

    const header = !embedded && (
        <PageHeader
            eyebrow={t('nav.platformScope')}
            title={t('pages.accounts.title')}
            description={t('pages.accounts.description')}
        />
    )

    if (usersQuery.isLoading || zevsQuery.isLoading) {
        return <div className="page-stack">{header}<PageSkeleton variant="table" /></div>
    }

    if (usersQuery.isError || zevsQuery.isError) {
        return (
            <div className="page-stack">
                {header}
                <Notice tone="error" onRetry={() => {
                    if (usersQuery.isError) void usersQuery.refetch()
                    if (zevsQuery.isError) void zevsQuery.refetch()
                }} isRetrying={usersQuery.isFetching || zevsQuery.isFetching}>{t('pages.accounts.loadFailed')}</Notice>
            </div>
        )
    }

    const zevs = [...(zevsQuery.data ?? [])].sort((left, right) => left.name.localeCompare(right.name))
    const editingSelf = editingUserId === currentUser?.id && currentUser?.role === 'admin'
    const filtersActive = hasActiveFilters(filters)

    return (
        <div className="page-stack">
            {header}

            <div className="actions-row actions-row-end">
                <button className="button button-primary" type="button" onClick={() => setShowCreateUserModal(true)}>
                    <FontAwesomeIcon icon={faCirclePlus} fixedWidth />
                    {t('pages.accounts.createModal.openButton')}
                </button>
            </div>

            {createdNotice && (
                <AccountCreatedNotice notice={createdNotice} onDismiss={() => setCreatedNotice(null)} />
            )}

            <section className="stat-grid">
                <StatCard label={t('pages.accounts.stats.total')} value={stats.total} />
                <StatCard label={t('pages.accounts.stats.withTwoFactor')} value={stats.withTwoFactor} />
                <StatCard label={t('pages.accounts.stats.guests')} value={stats.guests} />
                <StatCard label={t('pages.accounts.stats.needsTwoFactor')} value={stats.needsTwoFactor} />
                <StatCard label={t('pages.accounts.stats.neverSignedIn')} value={stats.neverSignedIn} />
            </section>

            <section>
                <div className="participant-filter-grid">
                    <label>
                        <span>{t('pages.accounts.filters.search')}</span>
                        <input
                            value={filters.search}
                            placeholder={t('pages.accounts.filters.searchPlaceholder')}
                            onChange={(event) => setFilters((previous) => ({ ...previous, search: event.target.value }))}
                        />
                    </label>
                    <label>
                        <span>{t('pages.accounts.filters.role')}</span>
                        <select
                            value={filters.role}
                            onChange={(event) => setFilters((previous) => ({ ...previous, role: event.target.value as AccountFilters['role'] }))}
                        >
                            <option value="all">{t('pages.accounts.filters.allRoles')}</option>
                            {ROLES.map((role) => (
                                <option key={role} value={role}>{roleLabel(role)}</option>
                            ))}
                        </select>
                    </label>
                    <label>
                        <span>{t('pages.accounts.filters.community')}</span>
                        <select
                            value={filters.zevId}
                            onChange={(event) => setFilters((previous) => ({ ...previous, zevId: event.target.value }))}
                        >
                            <option value="all">{t('pages.accounts.filters.allCommunities')}</option>
                            {zevs.map((zev) => (
                                <option key={zev.id} value={zev.id}>{zev.name}</option>
                            ))}
                        </select>
                    </label>
                    <label>
                        <span>{t('pages.accounts.filters.twoFactor')}</span>
                        <select
                            value={filters.mfaCompliance}
                            onChange={(event) => setFilters((previous) => ({ ...previous, mfaCompliance: event.target.value as AccountFilters['mfaCompliance'] }))}
                        >
                            <option value="all">{t('pages.accounts.filters.twoFactorAll')}</option>
                            <option value="needsTwoFactor">{t('pages.accounts.filters.twoFactorNeeded')}</option>
                        </select>
                    </label>
                </div>
            </section>

            <div className="table-card">
                <table>
                    <thead>
                        <tr>
                            <th>{t('pages.accounts.col.account')}</th>
                            <th>{t('pages.accounts.col.communities')}</th>
                            <th>{t('pages.accounts.col.security')}</th>
                            <th>{t('pages.accounts.col.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {visibleAccounts.map((account) => {
                            const isSelf = account.id === currentUser?.id
                            const menuItems = [
                                ...(canImpersonateAccount(account)
                                    ? [{
                                        key: 'impersonate',
                                        label: t('pages.accounts.impersonate'),
                                        icon: <FontAwesomeIcon icon={faUser} fixedWidth />,
                                        disabled: impersonationMutation.isPending || dialogLoading,
                                        onClick: () => confirmImpersonate(account),
                                    }]
                                    : []),
                                {
                                    key: 'reset-mfa',
                                    label: t('pages.accounts.resetMfa'),
                                    icon: <FontAwesomeIcon icon={faShieldHalved} fixedWidth />,
                                    disabled: resetMfaMutation.isPending || dialogLoading,
                                    onClick: () => confirmResetMfa(account),
                                },
                                {
                                    key: 'view-activity',
                                    label: t('pages.accounts.viewActivity'),
                                    icon: <FontAwesomeIcon icon={faClockRotateLeft} fixedWidth />,
                                    onClick: () => viewActivity(account),
                                },
                                // Not for the admin's own row: it would sign them out too, and the
                                // account page has "Sign out other devices" for that.
                                ...(isSelf
                                    ? []
                                    : [{
                                        key: 'sign-out',
                                        label: t('pages.accounts.signOutEverywhere'),
                                        icon: <FontAwesomeIcon icon={faRightFromBracket} fixedWidth />,
                                        disabled: revokeSessionsMutation.isPending || dialogLoading,
                                        onClick: () => confirmSignOut(account),
                                    }]),
                                // Deactivating yourself would sign you out mid-edit (the
                                // server refuses it too); the account page's own logout covers that case.
                                ...(isSelf
                                    ? []
                                    : [{
                                        key: 'toggle-active',
                                        label: t(account.is_active ? 'pages.accounts.deactivate' : 'pages.accounts.activate'),
                                        icon: <FontAwesomeIcon icon={account.is_active ? faBan : faPlay} fixedWidth />,
                                        disabled: activationMutation.isPending || dialogLoading,
                                        onClick: () => confirmSetActive(account, !account.is_active),
                                    }]),
                                {
                                    key: 'delete',
                                    label: t('common.delete'),
                                    icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
                                    // A member account has to be detached from its
                                    // communities first; the server refuses otherwise.
                                    disabled: !canDeleteAccount(account) || deleteUserMutation.isPending || dialogLoading,
                                    danger: true,
                                    onClick: () => confirmDelete(account),
                                },
                            ]

                            return (
                                <tr key={account.id}>
                                    <td>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                                            <strong>{accountDisplayName(account)}</strong>
                                            <span className="badge badge-tag">{roleLabel(account.role)}</span>
                                            {!account.is_active && <span className="badge badge-warning">{t('pages.accounts.inactive')}</span>}
                                        </div>
                                        <div className="muted">{account.username} · {account.email || '-'}</div>
                                    </td>
                                    <td>
                                        <AccountMemberships memberships={account.memberships} />
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                                            {account.mfa_methods.length === 0 && (
                                                <span className="badge badge-neutral">{t('pages.accounts.mfa.none')}</span>
                                            )}
                                            {account.mfa_methods.map((method) => (
                                                <span key={method} className="badge badge-success">{t(`pages.accounts.mfa.${method}`)}</span>
                                            ))}
                                            <AccountMfaComplianceBadge compliance={account.mfa_compliance} />
                                        </div>
                                        <div className="muted">
                                            {account.last_login
                                                ? t('pages.accounts.lastSignIn', { date: formatDateTime(account.last_login, settings) })
                                                : t('pages.accounts.neverSignedIn')}
                                        </div>
                                    </td>
                                    <td className="actions-cell">
                                        <div className="actions-cell-content">
                                            <button
                                                className="button button-primary button-compact"
                                                type="button"
                                                onClick={() => openEditUserModal(account)}
                                            >
                                                <FontAwesomeIcon icon={faPen} fixedWidth />
                                                {t('common.edit')}
                                            </button>
                                            <ActionMenu
                                                label={t('pages.accounts.moreActions')}
                                                icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                                                items={isSelf ? menuItems.filter((item) => item.key !== 'delete') : menuItems}
                                            />
                                        </div>
                                    </td>
                                </tr>
                            )
                        })}

                        {visibleAccounts.length === 0 && (
                            <tr>
                                <td colSpan={4}>
                                    {t(filtersActive ? 'pages.accounts.noMatches' : 'pages.accounts.noAccounts')}
                                    {filtersActive && (
                                        <>
                                            {' '}
                                            <button className="button button-secondary button-compact" type="button" onClick={() => setFilters(DEFAULT_ACCOUNT_FILTERS)}>
                                                {t('pages.accounts.filters.clear')}
                                            </button>
                                        </>
                                    )}
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            <FormModal isOpen={showCreateUserModal} title={t('pages.accounts.createModal.title')} onClose={() => setShowCreateUserModal(false)} maxWidth="600px">
                <form onSubmit={submitCreateUser} className="form-grid">
                    <label>
                        <span>{t('pages.accounts.editModal.username')}</span>
                        <input value={createUserForm.username} onChange={(event) => setCreateUserForm((previous) => ({ ...previous, username: event.target.value }))} required />
                    </label>
                    <label>
                        <span>{t('pages.accounts.editModal.email')}</span>
                        <input type="email" value={createUserForm.email} onChange={(event) => setCreateUserForm((previous) => ({ ...previous, email: event.target.value }))} required />
                    </label>
                    <label>
                        <span>{t('pages.accounts.editModal.firstName')}</span>
                        <input value={createUserForm.first_name} onChange={(event) => setCreateUserForm((previous) => ({ ...previous, first_name: event.target.value }))} required />
                    </label>
                    <label>
                        <span>{t('pages.accounts.editModal.lastName')}</span>
                        <input value={createUserForm.last_name} onChange={(event) => setCreateUserForm((previous) => ({ ...previous, last_name: event.target.value }))} required />
                    </label>
                    <label>
                        <span>{t('pages.accounts.editModal.role')}</span>
                        <select
                            value={createUserForm.role}
                            onChange={(event) => setCreateUserForm((previous) => ({ ...previous, role: event.target.value as UserRole }))}
                        >
                            {ROLES.map((role) => (
                                <option key={role} value={role}>{roleLabel(role)}</option>
                            ))}
                        </select>
                    </label>

                    <div className="muted" style={{ gridColumn: '1 / -1' }}>
                        {t('pages.accounts.createModal.passwordHint')}
                    </div>
                    {createUserError && <div className="error-banner" style={{ gridColumn: '1 / -1' }}>{createUserError}</div>}

                    <div className="actions-row actions-row-end actions-row-wrap" style={{ gridColumn: '1 / -1' }}>
                        <button className="button button-secondary" type="button" onClick={() => setShowCreateUserModal(false)}>
                            <FontAwesomeIcon icon={faXmark} fixedWidth />
                            {t('common.cancel')}
                        </button>
                        <button className="button button-primary" type="submit" disabled={createUserMutation.isPending}>
                            <FontAwesomeIcon icon={faCirclePlus} fixedWidth />
                            {t('pages.accounts.createModal.submit')}
                        </button>
                    </div>
                </form>
            </FormModal>

            <FormModal isOpen={showEditUserModal} title={t('pages.accounts.editModal.title')} onClose={() => setShowEditUserModal(false)} maxWidth="760px">
                <form onSubmit={submitEditUser} className="form-grid">
                    <label>
                        <span>{t('pages.accounts.editModal.username')}</span>
                        <input value={editUserForm.username} onChange={(event) => setEditUserForm((previous) => ({ ...previous, username: event.target.value }))} required />
                    </label>
                    <label>
                        <span>{t('pages.accounts.editModal.email')}</span>
                        <input type="email" value={editUserForm.email} onChange={(event) => setEditUserForm((previous) => ({ ...previous, email: event.target.value }))} required />
                    </label>
                    <label>
                        <span>{t('pages.accounts.editModal.firstName')}</span>
                        <input value={editUserForm.first_name} onChange={(event) => setEditUserForm((previous) => ({ ...previous, first_name: event.target.value }))} required />
                    </label>
                    <label>
                        <span>{t('pages.accounts.editModal.lastName')}</span>
                        <input value={editUserForm.last_name} onChange={(event) => setEditUserForm((previous) => ({ ...previous, last_name: event.target.value }))} required />
                    </label>
                    <label>
                        <span>{t('pages.accounts.editModal.role')}</span>
                        <select
                            value={editUserForm.role}
                            onChange={(event) => setEditUserForm((previous) => ({ ...previous, role: event.target.value as UserInput['role'] }))}
                            disabled={editingSelf}
                        >
                            {ROLES.map((role) => (
                                <option key={role} value={role}>{roleLabel(role)}</option>
                            ))}
                        </select>
                    </label>

                    <div className="muted" style={{ gridColumn: '1 / -1' }}>
                        {editingSelf ? t('pages.accounts.editModal.selfRoleNotice') : t('pages.accounts.editModal.roleHint')}
                    </div>
                    {editUserError && <div className="error-banner" style={{ gridColumn: '1 / -1' }}>{editUserError}</div>}

                    <div className="actions-row actions-row-end actions-row-wrap" style={{ gridColumn: '1 / -1' }}>
                        <button className="button button-secondary" type="button" onClick={() => setShowEditUserModal(false)}>
                            <FontAwesomeIcon icon={faXmark} fixedWidth />
                            {t('common.cancel')}
                        </button>
                        <button className="button button-primary" type="submit" disabled={updateUserMutation.isPending}>
                            <FontAwesomeIcon icon={faCheck} fixedWidth />
                            {t('pages.accounts.editModal.saveButton')}
                        </button>
                    </div>
                </form>
            </FormModal>

            {dialog && (
                <ConfirmDialog
                    {...dialog}
                    isLoading={dialogLoading}
                    onConfirm={handleConfirm}
                    onCancel={handleCancel}
                />
            )}
        </div>
    )
}
