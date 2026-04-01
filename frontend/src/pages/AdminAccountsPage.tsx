import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { FormModal } from '../components/FormModal'
import {
    createParticipantAccount,
    deleteUser,
    fetchParticipants,
    fetchUsers,
    fetchZevs,
    formatApiError,
    linkParticipantAccount,
    unlinkParticipantAccount,
    updateUser,
} from '../lib/api'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import type { Participant, User, UserInput } from '../types/api'

const defaultEditUserForm: UserInput = {
    username: '',
    email: '',
    first_name: '',
    last_name: '',
    role: 'participant',
    must_change_password: false,
}

export function AdminAccountsPage() {
    const queryClient = useQueryClient()
    const { user: currentUser, startImpersonation } = useAuth()
    const { pushToast } = useToast()
    const { t } = useTranslation()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const usersQuery = useQuery({ queryKey: ['users'], queryFn: fetchUsers })
    const participantsQuery = useQuery({ queryKey: ['participants'], queryFn: fetchParticipants })
    const zevsQuery = useQuery({ queryKey: ['zevs'], queryFn: fetchZevs })

    const [showLinkModal, setShowLinkModal] = useState(false)
    const [linkParticipant, setLinkParticipant] = useState<Participant | null>(null)
    const [selectedUserToLink, setSelectedUserToLink] = useState<string>('')
    const [linkError, setLinkError] = useState<string | null>(null)

    const [showCreateAccountModal, setShowCreateAccountModal] = useState(false)
    const [createAccountParticipant, setCreateAccountParticipant] = useState<Participant | null>(null)
    const [newAccountUsername, setNewAccountUsername] = useState('')
    const [newAccountEmail, setNewAccountEmail] = useState('')
    const [createAccountError, setCreateAccountError] = useState<string | null>(null)

    const [showEditUserModal, setShowEditUserModal] = useState(false)
    const [editingUserId, setEditingUserId] = useState<number | null>(null)
    const [editUserForm, setEditUserForm] = useState<UserInput>(defaultEditUserForm)
    const [editUserError, setEditUserError] = useState<string | null>(null)

    const [credentialsNotice, setCredentialsNotice] = useState<{ username: string; password: string; participantName: string } | null>(null)

    const linkMutation = useMutation({
        mutationFn: ({ participantId, userId }: { participantId: string; userId: number }) => linkParticipantAccount(participantId, userId),
        onSuccess: () => {
            setShowLinkModal(false)
            setLinkParticipant(null)
            setSelectedUserToLink('')
            setLinkError(null)
            pushToast('Account linked to participant.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
            void queryClient.invalidateQueries({ queryKey: ['users'] })
        },
        onError: (error) => setLinkError(formatApiError(error, 'Failed to link account.')),
    })

    const unlinkMutation = useMutation({
        mutationFn: (participantId: string) => unlinkParticipantAccount(participantId),
        onSuccess: () => {
            pushToast('Account unlinked from participant.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
            void queryClient.invalidateQueries({ queryKey: ['users'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to unlink account.'), 'error'),
    })

    const createAccountMutation = useMutation({
        mutationFn: ({ participantId, username, email }: { participantId: string; username?: string; email?: string }) => createParticipantAccount(participantId, { username, email }),
        onSuccess: (result) => {
            setShowCreateAccountModal(false)
            setCreateAccountParticipant(null)
            setNewAccountUsername('')
            setNewAccountEmail('')
            setCreateAccountError(null)
            setCredentialsNotice({
                username: result.account.username,
                password: result.temporary_password,
                participantName: `${result.participant.first_name} ${result.participant.last_name}`,
            })
            pushToast('Participant account created and linked.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
            void queryClient.invalidateQueries({ queryKey: ['users'] })
        },
        onError: (error) => setCreateAccountError(formatApiError(error, 'Failed to create account.')),
    })

    const updateUserMutation = useMutation({
        mutationFn: ({ userId, payload }: { userId: number; payload: Partial<UserInput> }) => updateUser(userId, payload),
        onSuccess: () => {
            setShowEditUserModal(false)
            setEditingUserId(null)
            setEditUserForm(defaultEditUserForm)
            setEditUserError(null)
            pushToast('Account updated.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['users'] })
        },
        onError: (error) => setEditUserError(formatApiError(error, 'Failed to update account.')),
    })

    const deleteUserMutation = useMutation({
        mutationFn: (userId: number) => deleteUser(userId),
        onSuccess: () => {
            pushToast('Account deleted.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['users'] })
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to delete account.'), 'error'),
    })

    const impersonationMutation = useMutation({
        mutationFn: async (participantUserId: number) => {
            await startImpersonation(participantUserId)
        },
        onSuccess: () => {
            pushToast('Impersonation started.', 'success')
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to start impersonation.'), 'error'),
    })

    function roleLabel(role: User['role']) {
        return t(`pages.accounts.roles.${role}` as Parameters<typeof t>[0], { defaultValue: role })
    }

    function participantName(participant: Participant) {
        return [participant.first_name, participant.last_name].filter(Boolean).join(' ')
    }

    function openLinkModal(participant: Participant) {
        setLinkParticipant(participant)
        setSelectedUserToLink('')
        setLinkError(null)
        setShowLinkModal(true)
    }

    function openCreateAccountModal(participant: Participant) {
        setCreateAccountParticipant(participant)
        setNewAccountUsername('')
        setNewAccountEmail(participant.email || '')
        setCreateAccountError(null)
        setShowCreateAccountModal(true)
    }

    function openEditUserModal(user: User) {
        setEditingUserId(user.id)
        setEditUserForm({
            username: user.username,
            email: user.email || '',
            first_name: user.first_name || '',
            last_name: user.last_name || '',
            role: user.role,
            must_change_password: user.must_change_password,
        })
        setEditUserError(null)
        setShowEditUserModal(true)
    }

    function submitLinkAccount(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!linkParticipant || !selectedUserToLink) {
            setLinkError('Please select an account to link.')
            return
        }
        linkMutation.mutate({ participantId: linkParticipant.id, userId: Number(selectedUserToLink) })
    }

    function submitCreateAccount(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!createAccountParticipant) {
            setCreateAccountError('No participant selected.')
            return
        }
        createAccountMutation.mutate({
            participantId: createAccountParticipant.id,
            username: newAccountUsername.trim() || undefined,
            email: newAccountEmail.trim() || undefined,
        })
    }

    function submitEditUser(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!editingUserId) {
            return
        }
        updateUserMutation.mutate({ userId: editingUserId, payload: editUserForm })
    }

    if (usersQuery.isLoading || participantsQuery.isLoading || zevsQuery.isLoading) {
        return <div className="card">Loading accounts and participants...</div>
    }

    if (usersQuery.isError || participantsQuery.isError || zevsQuery.isError) {
        return <div className="card error-banner">Failed to load account management data.</div>
    }

    const users = usersQuery.data?.results ?? []
    const participants = participantsQuery.data?.results ?? []
    const zevNameById = new Map((zevsQuery.data?.results ?? []).map((zev) => [zev.id, zev.name]))
    const userById = new Map(users.map((entry) => [entry.id, entry]))

    const participantByUserId = new Map<number, Participant>()
    for (const participant of participants) {
        if (participant.user != null) {
            participantByUserId.set(participant.user, participant)
        }
    }

    const unlinkedAccounts = users.filter((account) => !participantByUserId.has(account.id))
    const linkableAccounts = unlinkedAccounts.filter((account) => account.role === 'participant' || account.role === 'guest')

    const sortedParticipants = [...participants].sort((left, right) => {
        const zevComparison = (zevNameById.get(left.zev) ?? '').localeCompare(zevNameById.get(right.zev) ?? '')
        if (zevComparison !== 0) {
            return zevComparison
        }
        return participantName(left).localeCompare(participantName(right))
    })

    const sortedUnlinkedAccounts = [...unlinkedAccounts].sort((left, right) => left.username.localeCompare(right.username))

    return (
        <div className="page-stack">
            <header>
                <h2>{t('pages.accounts.title')}</h2>
                <p className="muted">{t('pages.accounts.description')}</p>
            </header>

            {credentialsNotice && (
                <section className="card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                        <div>
                            <h3 style={{ marginTop: 0, marginBottom: '0.5rem' }}>{t('pages.accounts.credentialsTitle')}</h3>
                            <p style={{ marginBottom: '0.35rem' }}><strong>{credentialsNotice.participantName}</strong></p>
                            <p style={{ margin: '0.2rem 0' }}>{t('pages.accounts.usernameLabel')} <strong>{credentialsNotice.username}</strong></p>
                            <p style={{ margin: '0.2rem 0' }}>{t('pages.accounts.passwordLabel')} <strong>{credentialsNotice.password}</strong></p>
                        </div>
                        <button className="button button-secondary" type="button" onClick={() => setCredentialsNotice(null)}>
                            {t('pages.accounts.dismiss')}
                        </button>
                    </div>
                </section>
            )}

            <div className="table-card">
                <table>
                    <thead>
                        <tr>
                            <th>{t('pages.accounts.col.type')}</th>
                            <th>{t('pages.accounts.col.participant')}</th>
                            <th>{t('pages.accounts.col.zev')}</th>
                            <th>{t('pages.accounts.col.account')}</th>
                            <th>{t('pages.accounts.col.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {sortedParticipants.map((participant) => {
                            const linkedAccount = participant.user ? userById.get(participant.user) : undefined
                            return (
                                <tr key={`participant-${participant.id}`}>
                                    <td>Participant</td>
                                    <td>
                                        <div>{participantName(participant)}</div>
                                        <div className="muted">{participant.email || '-'}</div>
                                    </td>
                                    <td>{zevNameById.get(participant.zev) ?? participant.zev}</td>
                                    <td>
                                        {linkedAccount ? (
                                            <>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                                                    <span>{linkedAccount.username}</span>
                                                    <span className="badge badge-neutral">
                                                        {roleLabel(linkedAccount.role)}
                                                    </span>
                                                </div>
                                                <div className="muted">{linkedAccount.email || '-'}</div>
                                            </>
                                        ) : (
                                            <span className="muted">{t('pages.accounts.noLinkedAccount')}</span>
                                        )}
                                    </td>
                                    <td className="actions-cell">
                                        {linkedAccount ? (
                                            <>
                                                {(linkedAccount.role === 'participant' || linkedAccount.role === 'zev_owner') && (
                                                    <button
                                                        className="button button-secondary"
                                                        type="button"
                                                        disabled={impersonationMutation.isPending || dialogLoading}
                                                        onClick={() => {
                                                            const name = participantName(participant)
                                                            confirm({
                                                                title: t('pages.accounts.impersonateTitle'),
                                                                message: t('pages.accounts.impersonateMessage', { name }),
                                                                confirmText: t('pages.accounts.impersonateConfirm'),
                                                                cancelText: 'Cancel',
                                                                onConfirm: async () => {
                                                                    await impersonationMutation.mutateAsync(linkedAccount.id)
                                                                },
                                                            })
                                                        }}
                                                    >
                                                        {t('pages.accounts.impersonate')}
                                                    </button>
                                                )}
                                                <button
                                                    className="button button-primary"
                                                    type="button"
                                                    onClick={() => openEditUserModal(linkedAccount)}
                                                >
                                                    Edit
                                                </button>
                                                <button
                                                    className="button button-secondary"
                                                    type="button"
                                                    disabled={unlinkMutation.isPending || dialogLoading}
                                                    onClick={() => {
                                                        const name = participantName(participant)
                                                        confirm({
                                                            title: t('pages.accounts.unlinkTitle'),
                                                            message: t('pages.accounts.unlinkMessage', { username: linkedAccount.username, name }),
                                                            confirmText: t('pages.accounts.unlinkConfirm'),
                                                            cancelText: 'Cancel',
                                                            onConfirm: async () => {
                                                                await unlinkMutation.mutateAsync(participant.id)
                                                            },
                                                        })
                                                    }}
                                                >
                                                    {t('pages.accounts.unlink')}
                                                </button>
                                            </>
                                        ) : (
                                            <>
                                                <button className="button button-secondary" type="button" onClick={() => openLinkModal(participant)} disabled={linkableAccounts.length === 0}>
                                                    {t('pages.accounts.linkExisting')}
                                                </button>
                                                <button className="button button-primary" type="button" onClick={() => openCreateAccountModal(participant)}>
                                                    {t('pages.accounts.createAccount')}
                                                </button>
                                            </>
                                        )}
                                    </td>
                                </tr>
                            )
                        })}

                        {sortedUnlinkedAccounts.map((account) => (
                            <tr key={`account-${account.id}`}>
                                <td>Account</td>
                                <td className="muted">—</td>
                                <td className="muted">—</td>
                                <td>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                                        <span>{account.username}</span>
                                        <span className="badge badge-neutral">
                                            {roleLabel(account.role)}
                                        </span>
                                    </div>
                                    <div className="muted">{account.email || '-'}</div>
                                </td>
                                <td className="actions-cell">
                                    <button className="button button-primary" type="button" onClick={() => openEditUserModal(account)}>
                                        Edit
                                    </button>
                                    <button
                                        className="button danger"
                                        type="button"
                                        disabled={deleteUserMutation.isPending || dialogLoading}
                                        onClick={() => {
                                            confirm({
                                                title: 'Delete account?',
                                                message: `Delete account ${account.username}? This action cannot be undone.`,
                                                confirmText: 'Delete',
                                                cancelText: 'Cancel',
                                                isDangerous: true,
                                                onConfirm: async () => {
                                                    await deleteUserMutation.mutateAsync(account.id)
                                                },
                                            })
                                        }}
                                    >
                                        Delete
                                    </button>
                                </td>
                            </tr>
                        ))}

                        {sortedParticipants.length === 0 && sortedUnlinkedAccounts.length === 0 && (
                            <tr>
                                <td colSpan={5}>{t('pages.accounts.noAccountsParticipants')}</td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            <FormModal isOpen={showLinkModal} title={t('pages.accounts.linkModal.title')} onClose={() => setShowLinkModal(false)} maxWidth="560px">
                <form onSubmit={submitLinkAccount} style={{ display: 'grid', gap: '1rem' }}>
                    <p style={{ margin: 0 }}>
                        {t('pages.accounts.linkModal.participant')} <strong>{linkParticipant ? participantName(linkParticipant) : '-'}</strong>
                    </p>
                    <label>
                        <span>{t('pages.accounts.linkModal.existingAccount')}</span>
                        <select value={selectedUserToLink} onChange={(event) => setSelectedUserToLink(event.target.value)} required>
                            <option value="">{t('pages.accounts.linkModal.selectAccount')}</option>
                            {linkableAccounts.map((account) => (
                                <option key={account.id} value={account.id}>
                                    {account.username} ({account.email || t('pages.accounts.linkModal.noEmail')})
                                </option>
                            ))}
                        </select>
                    </label>

                    {linkError && <div className="error-banner">{linkError}</div>}

                    <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                        <button className="button button-secondary" type="button" onClick={() => setShowLinkModal(false)}>Cancel</button>
                        <button className="button button-primary" type="submit" disabled={linkMutation.isPending}>{t('pages.accounts.linkModal.linkButton')}</button>
                    </div>
                </form>
            </FormModal>

            <FormModal isOpen={showCreateAccountModal} title={t('pages.accounts.createModal.title')} onClose={() => setShowCreateAccountModal(false)} maxWidth="560px">
                <form onSubmit={submitCreateAccount} style={{ display: 'grid', gap: '1rem' }}>
                    <p style={{ margin: 0 }}>
                        {t('pages.accounts.createModal.participant')} <strong>{createAccountParticipant ? participantName(createAccountParticipant) : '-'}</strong>
                    </p>

                    <label>
                        <span>{t('pages.accounts.createModal.username')}</span>
                        <input value={newAccountUsername} onChange={(event) => setNewAccountUsername(event.target.value)} placeholder={t('pages.accounts.createModal.autoGenerated')} />
                    </label>
                    <label>
                        <span>{t('pages.accounts.createModal.email')}</span>
                        <input type="email" value={newAccountEmail} onChange={(event) => setNewAccountEmail(event.target.value)} />
                    </label>

                    {createAccountError && <div className="error-banner">{createAccountError}</div>}

                    <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                        <button className="button button-secondary" type="button" onClick={() => setShowCreateAccountModal(false)}>Cancel</button>
                        <button className="button button-primary" type="submit" disabled={createAccountMutation.isPending}>{t('pages.accounts.createModal.createButton')}</button>
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
                            disabled={editingUserId === currentUser?.id && currentUser?.role === 'admin'}
                        >
                            <option value="participant">{t('pages.accounts.roles.participant')}</option>
                            <option value="guest">{t('pages.accounts.roles.guest')}</option>
                            <option value="zev_owner">{t('pages.accounts.roles.zev_owner')}</option>
                            <option value="admin">{t('pages.accounts.roles.admin')}</option>
                        </select>
                    </label>

                    {editingUserId === currentUser?.id && currentUser?.role === 'admin' && (
                        <div className="muted" style={{ gridColumn: '1 / -1' }}>
                            {t('pages.accounts.editModal.selfRoleNotice')}
                        </div>
                    )}
                    {editUserError && <div className="error-banner" style={{ gridColumn: '1 / -1' }}>{editUserError}</div>}

                    <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                        <button className="button button-secondary" type="button" onClick={() => setShowEditUserModal(false)}>Cancel</button>
                        <button className="button button-primary" type="submit" disabled={updateUserMutation.isPending}>{t('pages.accounts.editModal.saveButton')}</button>
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
