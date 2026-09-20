import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faEllipsis, faPen, faRightFromBracket, faShieldHalved, faTrash, faUser, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useMemo, useState, type FormEvent } from 'react'
import { ActionMenu } from '../components/ActionMenu'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { StatCard } from '../components/StatCard'
import { FormModal } from '../components/FormModal'
import { AccountMemberships } from '../features/accounts/AccountMemberships'
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
import { deleteUser, fetchUsers, resetUserMfa, revokeUserSessions, updateUser } from '../lib/api/auth'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import type { AdminUser, UserInput, UserRole } from '../types/api'

const defaultEditUserForm: UserInput = {
    username: '',
    email: '',
    first_name: '',
    last_name: '',
    role: 'participant',
    must_change_password: false,
}

const ROLES: UserRole[] = ['admin', 'zev_owner', 'participant', 'guest']

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
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const usersQuery = useQuery({ queryKey: queryKeys.auth.users(), queryFn: fetchUsers })
    const zevsQuery = useQuery({ queryKey: queryKeys.zev.list(), queryFn: fetchZevs })

    const [filters, setFilters] = useState<AccountFilters>(DEFAULT_ACCOUNT_FILTERS)

    const [showEditUserModal, setShowEditUserModal] = useState(false)
    const [editingUserId, setEditingUserId] = useState<number | null>(null)
    const [editUserForm, setEditUserForm] = useState<UserInput>(defaultEditUserForm)
    const [editUserError, setEditUserError] = useState<string | null>(null)

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
            onConfirm: async () => {
                await resetMfaMutation.mutateAsync(account.id)
            },
        })
    }

    function confirmSignOut(account: AdminUser) {
        confirm({
            title: t('pages.accounts.signOutTitle'),
            message: t('pages.accounts.signOutMessage', { username: account.username }),
            confirmText: t('pages.accounts.signOutConfirm'),
            cancelText: t('common.cancel'),
            isDangerous: true,
            onConfirm: async () => {
                await revokeSessionsMutation.mutateAsync(account.id)
            },
        })
    }

    function confirmImpersonate(account: AdminUser) {
        confirm({
            title: t('pages.accounts.impersonateTitle'),
            message: t('pages.accounts.impersonateMessage', { name: accountDisplayName(account) }),
            confirmText: t('pages.accounts.impersonateConfirm'),
            cancelText: t('common.cancel'),
            onConfirm: async () => {
                await impersonationMutation.mutateAsync(account.id)
            },
        })
    }

    function confirmDelete(account: AdminUser) {
        confirm({
            title: t('pages.accounts.deleteTitle'),
            message: t('pages.accounts.deleteMessage', { username: account.username }),
            confirmText: t('pages.accounts.deleteConfirm'),
            cancelText: t('common.cancel'),
            isDangerous: true,
            onConfirm: async () => {
                await deleteUserMutation.mutateAsync(account.id)
            },
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

    function submitEditUser(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!editingUserId) {
            return
        }
        updateUserMutation.mutate({ userId: editingUserId, payload: editUserForm })
    }

    if (usersQuery.isLoading || zevsQuery.isLoading) {
        return <div className="card">{t('pages.accounts.loading')}</div>
    }

    if (usersQuery.isError || zevsQuery.isError) {
        return <div className="card error-banner">{t('pages.accounts.loadFailed')}</div>
    }

    const zevs = [...(zevsQuery.data ?? [])].sort((left, right) => left.name.localeCompare(right.name))
    const editingSelf = editingUserId === currentUser?.id && currentUser?.role === 'admin'
    const filtersActive = hasActiveFilters(filters)

    return (
        <div className="page-stack">
            {!embedded && (
            <header>
                <p className="eyebrow">{t('nav.platformScope')}</p>
                <h2>{t('pages.accounts.title')}</h2>
                <p className="muted">{t('pages.accounts.description')}</p>
            </header>
            )}

            <section style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                <StatCard label={t('pages.accounts.stats.total')} value={stats.total} />
                <StatCard label={t('pages.accounts.stats.withTwoFactor')} value={stats.withTwoFactor} />
                <StatCard label={t('pages.accounts.stats.guests')} value={stats.guests} />
            </section>

            <section className="card">
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
                                            <span className="badge badge-neutral">{roleLabel(account.role)}</span>
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
                            <option value="participant">{t('pages.accounts.roles.participant')}</option>
                            <option value="guest">{t('pages.accounts.roles.guest')}</option>
                            <option value="zev_owner">{t('pages.accounts.roles.zev_owner')}</option>
                            <option value="admin">{t('pages.accounts.roles.admin')}</option>
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
