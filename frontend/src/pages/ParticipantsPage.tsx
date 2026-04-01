import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { FormModal } from '../components/FormModal'
import {
    createParticipant,
    deleteParticipant,
    downloadParticipantContractPdf,
    fetchParticipants,
    fetchZevs,
    formatApiError,
    sendParticipantInvitation,
    updateParticipant,
} from '../lib/api'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useTranslation } from 'react-i18next'
import { useToast } from '../lib/toast'
import type { Participant, ParticipantInput } from '../types/api'

const defaultForm: ParticipantInput = {
    zev: '',
    title: '',
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    address_line1: '',
    address_line2: '',
    postal_code: '',
    city: '',
    notes: '',
    valid_from: new Date().toISOString().slice(0, 10),
    valid_to: null,
}

const titleOptions: Array<{ value: NonNullable<ParticipantInput['title']>; label: string }> = [
    { value: '', label: 'No title' },
    { value: 'mr', label: 'Mr.' },
    { value: 'mrs', label: 'Mrs.' },
    { value: 'ms', label: 'Ms.' },
    { value: 'dr', label: 'Dr.' },
    { value: 'prof', label: 'Prof.' },
]

const titleLabelByValue: Record<string, string> = {
    mr: 'Mr.',
    mrs: 'Mrs.',
    ms: 'Ms.',
    dr: 'Dr.',
    prof: 'Prof.',
}

export function ParticipantsPage() {
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { selectedZevId } = useManagedZev()
    const { t } = useTranslation()
    const isManagedScope = user?.role === 'admin' || user?.role === 'zev_owner'
    const { data, isLoading, isError } = useQuery({ queryKey: ['participants'], queryFn: fetchParticipants })
    const zevsQuery = useQuery({ queryKey: ['zevs'], queryFn: fetchZevs })
    const [form, setForm] = useState<ParticipantInput>(defaultForm)
    const [editingId, setEditingId] = useState<string | null>(null)
    const [showModal, setShowModal] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [credentialsNotice, setCredentialsNotice] = useState<{
        participantName: string
        username: string
        password: string
        message: string
    } | null>(null)

    const createMutation = useMutation({
        mutationFn: createParticipant,
        onSuccess: (participant) => {
            setForm(defaultForm)
            setError(null)
            setShowModal(false)
            pushToast('Participant and account created.', 'success')
            if (participant.account_username && participant.initial_password) {
                setCredentialsNotice({
                    participantName: `${participant.first_name} ${participant.last_name}`,
                    username: participant.account_username,
                    password: participant.initial_password,
                    message: 'Initial login credentials were generated for this participant.',
                })
            }
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
        },
        onError: (error) => setError(formatApiError(error, 'Failed to create participant.')),
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, payload }: { id: string; payload: Partial<ParticipantInput> }) => updateParticipant(id, payload),
        onSuccess: () => {
            setEditingId(null)
            setForm(defaultForm)
            setError(null)
            setShowModal(false)
            pushToast('Participant updated.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
        },
        onError: (error) => setError(formatApiError(error, 'Failed to update participant.')),
    })

    const deleteMutation = useMutation({
        mutationFn: deleteParticipant,
        onSuccess: () => {
            pushToast('Participant deleted.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
        },
    })

    const invitationMutation = useMutation({
        mutationFn: sendParticipantInvitation,
        onSuccess: (result, participantId) => {
            const participant = data?.results.find((entry) => entry.id === participantId)
            pushToast(result.detail, 'success')
            setCredentialsNotice({
                participantName: participant ? `${participant.first_name} ${participant.last_name}` : 'Participant',
                username: result.username,
                password: result.temporary_password,
                message: 'A fresh temporary password was created and emailed to the participant.',
            })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to send invitation.'), 'error'),
    })

    function formatParticipantName(participant: Participant): string {
        const titleLabel = participant.title ? titleLabelByValue[participant.title] : ''
        return [titleLabel, participant.first_name, participant.last_name].filter(Boolean).join(' ')
    }

    function startEdit(participant: Participant) {
        setEditingId(participant.id)
        setForm({
            zev: participant.zev,
            title: participant.title || '',
            first_name: participant.first_name,
            last_name: participant.last_name,
            email: participant.email || '',
            phone: participant.phone || '',
            address_line1: participant.address_line1 || '',
            address_line2: participant.address_line2 || '',
            postal_code: participant.postal_code || '',
            city: participant.city || '',
            notes: participant.notes || '',
            valid_from: participant.valid_from,
            valid_to: participant.valid_to || null,
        })
        setShowModal(true)
    }

    function openCreateModal() {
        setEditingId(null)
        setForm((previous) => ({ ...defaultForm, zev: isManagedScope ? selectedZevId : previous.zev }))
        setError(null)
        setShowModal(true)
    }

    function closeModal() {
        setShowModal(false)
        setEditingId(null)
        setForm(defaultForm)
        setError(null)
    }

    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        const zevForSubmit = isManagedScope ? selectedZevId : form.zev
        if (!zevForSubmit) {
            setError('Please select a ZEV.')
            return
        }
        if (!form.email) {
            setError('Please provide an email address.')
            return
        }
        if (editingId) {
            updateMutation.mutate({ id: editingId, payload: { ...form, zev: zevForSubmit } })
            return
        }
        createMutation.mutate({ ...form, zev: zevForSubmit })
    }

    function participantWarnings(participant: Participant): string[] {
        const warnings: string[] = []
        if (!participant.email) warnings.push(t('pages.participants.warnings.noEmail'))
        const hasAddress = !!(participant.address_line1 && participant.postal_code && participant.city)
        if (!hasAddress) warnings.push(t('pages.participants.warnings.noAddress'))
        if (!participant.has_metering_point_assignment) warnings.push(t('pages.participants.warnings.noMeteringPoint'))
        return warnings
    }

    if (isLoading) return <div className="card">Loading participants...</div>
    if (isError) return <div className="card error-banner">Failed to load participants.</div>

    const participants = (data?.results ?? []).filter((participant) => !isManagedScope || !selectedZevId || participant.zev === selectedZevId)
    const ownerIdByZevId = new Map((zevsQuery.data?.results ?? []).map((zev) => [zev.id, zev.owner]))
    const isOwnerParticipant = (participant: Participant) => ownerIdByZevId.get(participant.zev) === participant.user
    const sortedParticipants = [...participants].sort((left, right) => {
        const leftIsOwner = isOwnerParticipant(left)
        const rightIsOwner = isOwnerParticipant(right)
        if (leftIsOwner !== rightIsOwner) {
            return leftIsOwner ? -1 : 1
        }
        return formatParticipantName(left).localeCompare(formatParticipantName(right))
    })

    return (
        <div className="page-stack">
            <header>
                <h2>{t('pages.participants.title')}</h2>
                <p className="muted">{t('pages.participants.description')}</p>
            </header>

            {credentialsNotice && (
                <section className="card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                        <div>
                            <h3 style={{ marginTop: 0, marginBottom: '0.5rem' }}>{t('pages.participants.credentialsTitle')}</h3>
                            <p className="muted" style={{ marginTop: 0 }}>{credentialsNotice.message}</p>
                            <p style={{ marginBottom: '0.35rem' }}><strong>{credentialsNotice.participantName}</strong></p>
                            <p style={{ margin: '0.2rem 0' }}>{t('pages.participants.usernameLabel')} <strong>{credentialsNotice.username}</strong></p>
                            <p style={{ margin: '0.2rem 0' }}>{t('pages.participants.passwordLabel')} <strong>{credentialsNotice.password}</strong></p>
                        </div>
                        <button className="button button-secondary" type="button" onClick={() => setCredentialsNotice(null)}>
                            {t('pages.participants.dismiss')}
                        </button>
                    </div>
                </section>
            )}

            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
                <button className="button button-primary" onClick={openCreateModal}>
                    {t('pages.participants.newParticipant')}
                </button>
            </div>

            <FormModal
                isOpen={showModal}
                title={editingId ? t('pages.participants.editTitle') : t('pages.participants.createTitle')}
                onClose={closeModal}
                maxWidth="960px"
            >
                <form onSubmit={submit} className="form-grid">
                    <label>
                        <span>{t('pages.participants.form.title')}</span>
                        <select
                            value={form.title ?? ''}
                            onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value as ParticipantInput['title'] }))}
                        >
                            {titleOptions.map((option) => (
                                <option key={option.value || 'none'} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label>
                        <span>{t('pages.participants.form.firstName')}</span>
                        <input
                            value={form.first_name}
                            onChange={(event) => setForm((prev) => ({ ...prev, first_name: event.target.value }))}
                            required
                        />
                    </label>
                    <label>
                        <span>{t('pages.participants.form.lastName')}</span>
                        <input
                            value={form.last_name}
                            onChange={(event) => setForm((prev) => ({ ...prev, last_name: event.target.value }))}
                            required
                        />
                    </label>
                    <label>
                        <span>{t('pages.participants.form.email')}</span>
                        <input
                            type="email"
                            value={form.email}
                            onChange={(event) => setForm((prev) => ({ ...prev, email: event.target.value }))}
                            required
                        />
                    </label>
                    <label>
                        <span>{t('pages.participants.form.phone')}</span>
                        <input
                            value={form.phone ?? ''}
                            onChange={(event) => setForm((prev) => ({ ...prev, phone: event.target.value }))}
                        />
                    </label>
                    <label style={{ gridColumn: '1 / -1' }}>
                        <span>{t('pages.participants.form.addressLine1')}</span>
                        <input
                            value={form.address_line1 ?? ''}
                            onChange={(event) => setForm((prev) => ({ ...prev, address_line1: event.target.value }))}
                        />
                    </label>
                    <label style={{ gridColumn: '1 / -1' }}>
                        <span>{t('pages.participants.form.addressLine2')}</span>
                        <input
                            value={form.address_line2 ?? ''}
                            onChange={(event) => setForm((prev) => ({ ...prev, address_line2: event.target.value }))}
                        />
                    </label>
                    <label>
                        <span>{t('pages.participants.form.postalCode')}</span>
                        <input
                            value={form.postal_code ?? ''}
                            onChange={(event) => setForm((prev) => ({ ...prev, postal_code: event.target.value }))}
                        />
                    </label>
                    <label>
                        <span>{t('pages.participants.form.city')}</span>
                        <input
                            value={form.city ?? ''}
                            onChange={(event) => setForm((prev) => ({ ...prev, city: event.target.value }))}
                        />
                    </label>
                    <label>
                        <span>{t('pages.participants.form.validFrom')}</span>
                        <input
                            type="date"
                            value={form.valid_from}
                            onChange={(event) => setForm((prev) => ({ ...prev, valid_from: event.target.value }))}
                            required
                        />
                    </label>
                    <label>
                        <span>{t('pages.participants.form.validTo')}</span>
                        <input
                            type="date"
                            value={form.valid_to ?? ''}
                            onChange={(event) => setForm((prev) => ({ ...prev, valid_to: event.target.value || null }))}
                        />
                    </label>
                    <label style={{ gridColumn: '1 / -1' }}>
                        <span>{t('pages.participants.form.notes')}</span>
                        <textarea
                            value={form.notes ?? ''}
                            onChange={(event) => setForm((prev) => ({ ...prev, notes: event.target.value }))}
                            rows={3}
                        />
                    </label>

                    {error && <div className="error-banner" style={{ gridColumn: '1 / -1' }}>{error}</div>}

                    <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '1rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
                        <button className="button button-secondary" type="button" onClick={closeModal}>
                            Cancel
                        </button>
                        <button className="button button-primary" type="submit" disabled={createMutation.isPending || updateMutation.isPending}>
                            {editingId ? t('pages.participants.saveParticipant') : t('pages.participants.createTitle')}
                        </button>
                    </div>
                </form>
            </FormModal>

            {sortedParticipants.length === 0 ? (
                <section className="card" style={{ display: 'grid', gap: '0.75rem' }}>
                    <h3 style={{ margin: 0 }}>{t('pages.participants.emptyState.title')}</h3>
                    <p className="muted" style={{ margin: 0 }}>{t('pages.participants.emptyState.description')}</p>
                    <div>
                        <button className="button button-primary" type="button" onClick={openCreateModal}>
                            {t('pages.participants.emptyState.createAction')}
                        </button>
                    </div>
                </section>
            ) : (
                <div className="table-card">
                    <table>
                        <thead>
                            <tr>
                                <th>{t('pages.participants.col.name')}</th>
                                <th>{t('pages.participants.col.contact')}</th>
                                <th>{t('pages.participants.col.address')}</th>
                                <th>{t('pages.participants.col.validFrom')}</th>
                                <th>{t('pages.participants.col.validTo')}</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {sortedParticipants.map((participant) => {
                            const ownerRow = isOwnerParticipant(participant)

                            return (
                                <tr key={participant.id}>
                                    <td>
                                        <div>{formatParticipantName(participant)}</div>
                                        {ownerRow && (
                                            <div>
                                                <span className="badge badge-info" style={{ marginTop: '0.3rem' }}>
                                                    {t('pages.participants.owner')}
                                                </span>
                                            </div>
                                        )}
                                        {participantWarnings(participant).length > 0 && (
                                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem', marginTop: '0.3rem' }}>
                                                {participantWarnings(participant).map((warning) => (
                                                    <span key={warning} className="badge badge-warning">{warning}</span>
                                                ))}
                                            </div>
                                        )}
                                    </td>
                                    <td>
                                        <div>{participant.email || '-'}</div>
                                        <div className="muted">{participant.phone || 'No phone'}</div>
                                    </td>
                                    <td>
                                        {[participant.address_line1, participant.address_line2, [participant.postal_code, participant.city].filter(Boolean).join(' ')].filter(Boolean).join(', ') || '-'}
                                    </td>
                                    <td>{formatShortDate(participant.valid_from, settings)}</td>
                                    <td>{participant.valid_to ? formatShortDate(participant.valid_to, settings) : '-'}</td>
                                    <td className="actions-cell">
                                        <button
                                            className="button"
                                            type="button"
                                            disabled={invitationMutation.isPending}
                                            onClick={() => invitationMutation.mutate(participant.id)}
                                        >
                                            {t('pages.participants.sendInvitation')}
                                        </button>
                                        <button
                                            className="button button-secondary"
                                            type="button"
                                            onClick={() => downloadParticipantContractPdf(
                                                participant.id,
                                                `contract_${participant.last_name}_${participant.first_name}.pdf`
                                            ).catch(() => pushToast(t('pages.participants.contractDownloadError'), 'error'))}
                                        >
                                            {t('pages.participants.downloadContract')}
                                        </button>
                                        <button className="button button-primary" type="button" onClick={() => startEdit(participant)}>
                                            Edit
                                        </button>
                                        {!ownerRow && (
                                            <button
                                                className="button danger"
                                                type="button"
                                                disabled={deleteMutation.isPending || dialogLoading}
                                                onClick={() => confirm({
                                                    title: t('pages.participants.deleteTitle'),
                                                    message: t('pages.participants.deleteMessage', { name: formatParticipantName(participant) }),
                                                    confirmText: t('pages.participants.deleteConfirm'),
                                                    isDangerous: true,
                                                    onConfirm: () => deleteMutation.mutate(participant.id),
                                                })}
                                            >
                                                Delete
                                            </button>
                                        )}
                                    </td>
                                </tr>
                            )
                            })}
                        </tbody>
                    </table>
                </div>
            )}

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
