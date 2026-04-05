import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faCopy, faEllipsis, faLink, faPen, faPlus, faTrash, faUser, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useState, type FormEvent } from 'react'
import { ActionMenu } from '../components/ActionMenu'
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
            pushToast(t('pages.accounts.feedback.linkSuccess'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
            void queryClient.invalidateQueries({ queryKey: ['users'] })
        },
        onError: (error) => setLinkError(formatApiError(error, t('pages.accounts.feedback.linkFailed'))),
    })

    const unlinkMutation = useMutation({
        mutationFn: (participantId: string) => unlinkParticipantAccount(participantId),
        onSuccess: () => {
            pushToast(t('pages.accounts.feedback.unlinkSuccess'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
            void queryClient.invalidateQueries({ queryKey: ['users'] })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.accounts.feedback.unlinkFailed')), 'error'),
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
            pushToast(t('pages.accounts.feedback.createSuccess'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
            void queryClient.invalidateQueries({ queryKey: ['users'] })
        },
        onError: (error) => setCreateAccountError(formatApiError(error, t('pages.accounts.feedback.createFailed'))),
    })

    const updateUserMutation = useMutation({
        mutationFn: ({ userId, payload }: { userId: number; payload: Partial<UserInput> }) => updateUser(userId, payload),
        onSuccess: () => {
            setShowEditUserModal(false)
            setEditingUserId(null)
            setEditUserForm(defaultEditUserForm)
            setEditUserError(null)
            pushToast(t('pages.accounts.feedback.updateSuccess'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['users'] })
        },
        onError: (error) => setEditUserError(formatApiError(error, t('pages.accounts.feedback.updateFailed'))),
    })

    const deleteUserMutation = useMutation({
        mutationFn: (userId: number) => deleteUser(userId),
        onSuccess: () => {
            pushToast(t('pages.accounts.feedback.deleteSuccess'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['users'] })
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.accounts.feedback.deleteFailed')), 'error'),
    })

    const impersonationMutation = useMutation({
        mutationFn: async (participantUserId: number) => {
            await startImpersonation(participantUserId)
        },
        onSuccess: () => {
            pushToast(t('pages.accounts.feedback.impersonationSuccess'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.accounts.feedback.impersonationFailed')), 'error'),
    })

    function roleLabel(role: User['role']) {
        return t(`pages.accounts.roles.${role}` as Parameters<typeof t>[0], { defaultValue: role })
    }

    function participantName(participant: Participant) {
        return [participant.first_name, participant.last_name].filter(Boolean).join(' ')
    }

    async function copyValue(value: string, successMessage: string) {
        try {
            await navigator.clipboard.writeText(value)
            pushToast(successMessage, 'success')
        } catch {
            pushToast(t('pages.accounts.feedback.copyFailed'), 'error')
        }
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
            setLinkError(t('pages.accounts.validation.selectAccount'))
            return
        }
        linkMutation.mutate({ participantId: linkParticipant.id, userId: Number(selectedUserToLink) })
    }

    function submitCreateAccount(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!createAccountParticipant) {
            setCreateAccountError(t('pages.accounts.validation.noParticipantSelected'))
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
        return <div className="card">{t('pages.accounts.loading')}</div>
    }

    if (usersQuery.isError || participantsQuery.isError || zevsQuery.isError) {
        return <div className="card error-banner">{t('pages.accounts.loadFailed')}</div>
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
    const linkedParticipantsCount = participants.filter((participant) => participant.user != null).length
    const standaloneAccountsCount = unlinkedAccounts.length

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

            <section style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                <article className="stat-card">
                    <div className="muted">{t('pages.accounts.stats.totalParticipants')}</div>
                    <h3>{participants.length}</h3>
                </article>
                <article className="stat-card">
                    <div className="muted">{t('pages.accounts.stats.linkedParticipants')}</div>
                    <h3>{linkedParticipantsCount}</h3>
                </article>
                <article className="stat-card">
                    <div className="muted">{t('pages.accounts.stats.standaloneAccounts')}</div>
                    <h3>{standaloneAccountsCount}</h3>
                </article>
            </section>

            {credentialsNotice && (
                <section className="card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                        <div>
                            <h3 style={{ marginTop: 0, marginBottom: '0.5rem' }}>{t('pages.accounts.credentialsTitle')}</h3>
                            <p style={{ marginBottom: '0.35rem' }}><strong>{credentialsNotice.participantName}</strong></p>
                            <p style={{ margin: '0.2rem 0' }}>{t('pages.accounts.usernameLabel')} <strong>{credentialsNotice.username}</strong></p>
                            <p style={{ margin: '0.2rem 0' }}>{t('pages.accounts.passwordLabel')} <strong>{credentialsNotice.password}</strong></p>
                        </div>
                        <div className="actions-row actions-row-wrap actions-row-end">
                            <button
                                className="button button-secondary button-compact"
                                type="button"
                                onClick={() => void copyValue(credentialsNotice.username, t('pages.accounts.feedback.copyUsernameSuccess'))}
                            >
                                <FontAwesomeIcon icon={faCopy} fixedWidth />
                                {t('pages.accounts.copyUsername')}
                            </button>
                            <button
                                className="button button-secondary button-compact"
                                type="button"
                                onClick={() => void copyValue(credentialsNotice.password, t('pages.accounts.feedback.copyPasswordSuccess'))}
                            >
                                <FontAwesomeIcon icon={faCopy} fixedWidth />
                                {t('pages.accounts.copyPassword')}
                            </button>
                            <button className="button button-secondary button-compact" type="button" onClick={() => setCredentialsNotice(null)}>
                                <FontAwesomeIcon icon={faXmark} fixedWidth />
                                {t('pages.accounts.dismiss')}
                            </button>
                        </div>
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
                            const linkedRowActions = linkedAccount
                                ? [
                                    ...((linkedAccount.role === 'participant' || linkedAccount.role === 'zev_owner')
                                        ? [{
                                            key: 'impersonate',
                                            label: t('pages.accounts.impersonate'),
                                            icon: <FontAwesomeIcon icon={faUser} fixedWidth />,
                                            disabled: impersonationMutation.isPending || dialogLoading,
                                            onClick: () => {
                                                const name = participantName(participant)
                                                confirm({
                                                    title: t('pages.accounts.impersonateTitle'),
                                                    message: t('pages.accounts.impersonateMessage', { name }),
                                                    confirmText: t('pages.accounts.impersonateConfirm'),
                                                    cancelText: t('common.cancel'),
                                                    onConfirm: async () => {
                                                        await impersonationMutation.mutateAsync(linkedAccount.id)
                                                    },
                                                })
                                            },
                                        }]
                                        : []),
                                    {
                                        key: 'unlink',
                                        label: t('pages.accounts.unlink'),
                                        icon: <FontAwesomeIcon icon={faXmark} fixedWidth />,
                                        disabled: unlinkMutation.isPending || dialogLoading,
                                        onClick: () => {
                                            const name = participantName(participant)
                                            confirm({
                                                title: t('pages.accounts.unlinkTitle'),
                                                message: t('pages.accounts.unlinkMessage', { username: linkedAccount.username, name }),
                                                confirmText: t('pages.accounts.unlinkConfirm'),
                                                cancelText: t('common.cancel'),
                                                onConfirm: async () => {
                                                    await unlinkMutation.mutateAsync(participant.id)
                                                },
                                            })
                                        },
                                    },
                                ]
                                : []
                            return (
                                <tr key={`participant-${participant.id}`}>
                                    <td>
                                        <span className="badge badge-info">{t('pages.accounts.typeValues.participant')}</span>
                                    </td>
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
                                                <button
                                                    className="button button-primary button-compact"
                                                    type="button"
                                                    onClick={() => openEditUserModal(linkedAccount)}
                                                >
                                                    <FontAwesomeIcon icon={faPen} fixedWidth />
                                                    {t('common.edit')}
                                                </button>
                                                <ActionMenu
                                                    label={t('pages.accounts.moreActions')}
                                                    icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                                                    items={linkedRowActions}
                                                />
                                            </>
                                        ) : (
                                            <>
                                                <button className="button button-secondary button-compact" type="button" onClick={() => openLinkModal(participant)} disabled={linkableAccounts.length === 0}>
                                                    <FontAwesomeIcon icon={faLink} fixedWidth />
                                                    {t('pages.accounts.linkExisting')}
                                                </button>
                                                <button className="button button-primary button-compact" type="button" onClick={() => openCreateAccountModal(participant)}>
                                                    <FontAwesomeIcon icon={faPlus} fixedWidth />
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
                                <td>
                                    <span className="badge badge-neutral">{t('pages.accounts.typeValues.account')}</span>
                                </td>
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
                                    <button className="button button-primary button-compact" type="button" onClick={() => openEditUserModal(account)}>
                                        <FontAwesomeIcon icon={faPen} fixedWidth />
                                        {t('common.edit')}
                                    </button>
                                    <button
                                        className="button button-danger button-compact"
                                        type="button"
                                        disabled={deleteUserMutation.isPending || dialogLoading}
                                        onClick={() => {
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
                                        }}
                                    >
                                        <FontAwesomeIcon icon={faTrash} fixedWidth />
                                        {t('common.delete')}
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

                    <div className="actions-row actions-row-end actions-row-wrap">
                        <button className="button button-secondary" type="button" onClick={() => setShowLinkModal(false)}>
                            <FontAwesomeIcon icon={faXmark} fixedWidth />
                            {t('common.cancel')}
                        </button>
                        <button className="button button-primary" type="submit" disabled={linkMutation.isPending}>
                            <FontAwesomeIcon icon={faLink} fixedWidth />
                            {t('pages.accounts.linkModal.linkButton')}
                        </button>
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

                    <div className="actions-row actions-row-end actions-row-wrap">
                        <button className="button button-secondary" type="button" onClick={() => setShowCreateAccountModal(false)}>
                            <FontAwesomeIcon icon={faXmark} fixedWidth />
                            {t('common.cancel')}
                        </button>
                        <button className="button button-primary" type="submit" disabled={createAccountMutation.isPending}>
                            <FontAwesomeIcon icon={faPlus} fixedWidth />
                            {t('pages.accounts.createModal.createButton')}
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
