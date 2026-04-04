import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faDownload,
    faEllipsis,
    faEnvelope,
    faPen,
    faPlus,
    faTrash,
    faTriangleExclamation,
} from '@fortawesome/free-solid-svg-icons'
import { ActionMenu, type ActionMenuItem } from '../components/ActionMenu'
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

type ParticipantReadinessFilter = 'all' | 'attention' | 'ready'
type ParticipantValidityState = 'current' | 'upcoming' | 'ended'

function getParticipantValidityState(participant: Participant, todayIso: string): ParticipantValidityState {
    if (participant.valid_from > todayIso) return 'upcoming'
    if (participant.valid_to && participant.valid_to < todayIso) return 'ended'
    return 'current'
}

function participantValidityBadgeClass(state: ParticipantValidityState): string {
    if (state === 'current') return 'badge badge-success'
    if (state === 'upcoming') return 'badge badge-info'
    return 'badge badge-neutral'
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
    const [searchTerm, setSearchTerm] = useState('')
    const [readinessFilter, setReadinessFilter] = useState<ParticipantReadinessFilter>('all')
    const [credentialsNotice, setCredentialsNotice] = useState<{
        participantName: string
        username: string
        password: string
        message: string
    } | null>(null)

    const titleOptions = useMemo(
        () => [
            { value: '' as const, label: t('pages.zevs.titles.none') },
            { value: 'mr' as const, label: t('pages.zevs.titles.mr') },
            { value: 'mrs' as const, label: t('pages.zevs.titles.mrs') },
            { value: 'ms' as const, label: t('pages.zevs.titles.ms') },
            { value: 'dr' as const, label: t('pages.zevs.titles.dr') },
            { value: 'prof' as const, label: t('pages.zevs.titles.prof') },
        ],
        [t],
    )
    const titleLabelByValue = useMemo(
        () => ({
            mr: t('pages.zevs.titles.mr'),
            mrs: t('pages.zevs.titles.mrs'),
            ms: t('pages.zevs.titles.ms'),
            dr: t('pages.zevs.titles.dr'),
            prof: t('pages.zevs.titles.prof'),
        }),
        [t],
    )

    const createMutation = useMutation({
        mutationFn: createParticipant,
        onSuccess: (participant) => {
            setForm(defaultForm)
            setError(null)
            setShowModal(false)
            pushToast(t('pages.participants.messages.created'), 'success')
            if (participant.account_username && participant.initial_password) {
                setCredentialsNotice({
                    participantName: `${participant.first_name} ${participant.last_name}`,
                    username: participant.account_username,
                    password: participant.initial_password,
                    message: t('pages.participants.messages.credentialsGenerated'),
                })
            }
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
        },
        onError: (error) => setError(formatApiError(error, t('pages.participants.messages.createFailed'))),
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, payload }: { id: string; payload: Partial<ParticipantInput> }) => updateParticipant(id, payload),
        onSuccess: () => {
            setEditingId(null)
            setForm(defaultForm)
            setError(null)
            setShowModal(false)
            pushToast(t('pages.participants.messages.updated'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
        },
        onError: (error) => setError(formatApiError(error, t('pages.participants.messages.updateFailed'))),
    })

    const deleteMutation = useMutation({
        mutationFn: deleteParticipant,
        onSuccess: () => {
            pushToast(t('pages.participants.messages.deleted'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['participants'] })
        },
    })

    const invitationMutation = useMutation({
        mutationFn: sendParticipantInvitation,
        onSuccess: (result, participantId) => {
            const participant = data?.results.find((entry) => entry.id === participantId)
            pushToast(
                t('pages.participants.messages.invitationSent', {
                    email: participant?.email || '',
                }),
                'success',
            )
            setCredentialsNotice({
                participantName: participant ? `${participant.first_name} ${participant.last_name}` : t('pages.participants.fallbackName'),
                username: result.username,
                password: result.temporary_password,
                message: t('pages.participants.messages.invitationReset'),
            })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.participants.messages.invitationFailed')), 'error'),
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
            setError(t('pages.participants.messages.selectZev'))
            return
        }
        if (!form.email) {
            setError(t('pages.participants.messages.emailRequired'))
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

    function formatParticipantAddress(participant: Participant): string {
        return [
            participant.address_line1,
            participant.address_line2,
            [participant.postal_code, participant.city].filter(Boolean).join(' '),
        ].filter(Boolean).join(', ')
    }

    if (isLoading) return <div className="card">{t('common.loading')}</div>
    if (isError) return <div className="card error-banner">{t('common.error')}</div>

    const participants = (data?.results ?? []).filter((participant) => !isManagedScope || !selectedZevId || participant.zev === selectedZevId)
    const ownerIdByZevId = new Map((zevsQuery.data?.results ?? []).map((zev) => [zev.id, zev.owner]))
    const isOwnerParticipant = (participant: Participant) => ownerIdByZevId.get(participant.zev) === participant.user
    const todayIso = new Date().toISOString().slice(0, 10)
    const participantCards = [...participants]
        .map((participant) => {
            const warnings = participantWarnings(participant)
            const ownerRow = isOwnerParticipant(participant)
            const validityState = getParticipantValidityState(participant, todayIso)

            return {
                participant,
                warnings,
                ownerRow,
                validityState,
                displayName: formatParticipantName(participant),
                address: formatParticipantAddress(participant),
            }
        })
        .sort((left, right) => {
            if (left.ownerRow !== right.ownerRow) {
                return left.ownerRow ? -1 : 1
            }
            return left.displayName.localeCompare(right.displayName)
        })
    const normalizedSearch = searchTerm.trim().toLowerCase()
    const filteredParticipants = participantCards.filter((entry) => {
        const matchesReadiness = readinessFilter === 'all'
            || (readinessFilter === 'attention' && entry.warnings.length > 0)
            || (readinessFilter === 'ready' && entry.warnings.length === 0)
        const matchesSearch = !normalizedSearch
            || entry.displayName.toLowerCase().includes(normalizedSearch)
            || (entry.participant.email || '').toLowerCase().includes(normalizedSearch)
            || entry.address.toLowerCase().includes(normalizedSearch)

        return matchesReadiness && matchesSearch
    })
    const ownerCount = participantCards.filter((entry) => entry.ownerRow).length
    const warningCount = participantCards.filter((entry) => entry.warnings.length > 0).length
    const noMeteringCount = participantCards.filter((entry) => !entry.participant.has_metering_point_assignment).length
    const hasFilters = !!normalizedSearch || readinessFilter !== 'all'

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

            <section className="card participant-toolbar">
                <div className="participant-toolbar-header">
                    <div className="participant-summary" aria-label={t('pages.participants.summaryLabel')}>
                        <span className="participant-summary-stat">
                            <span className="participant-summary-label">{t('pages.participants.summary.total')}</span>
                            <span className="participant-summary-value">{participantCards.length}</span>
                        </span>
                        <span className="participant-summary-stat">
                            <span className="participant-summary-label">{t('pages.participants.summary.owners')}</span>
                            <span className="participant-summary-value">{ownerCount}</span>
                        </span>
                        <span className="participant-summary-stat">
                            <span className="participant-summary-label">{t('pages.participants.summary.attention')}</span>
                            <span className="participant-summary-value">{warningCount}</span>
                        </span>
                        <span className="participant-summary-stat">
                            <span className="participant-summary-label">{t('pages.participants.summary.noMetering')}</span>
                            <span className="participant-summary-value">{noMeteringCount}</span>
                        </span>
                    </div>

                    <button className="button button-primary" type="button" onClick={openCreateModal}>
                        <FontAwesomeIcon icon={faPlus} fixedWidth />
                        {t('pages.participants.newParticipant')}
                    </button>
                </div>

                <div className="participant-filter-grid">
                    <label>
                        <span>{t('pages.participants.filters.search')}</span>
                        <input
                            value={searchTerm}
                            onChange={(event) => setSearchTerm(event.target.value)}
                            placeholder={t('pages.participants.filters.searchPlaceholder')}
                        />
                    </label>
                    <label>
                        <span>{t('pages.participants.filters.readiness')}</span>
                        <select value={readinessFilter} onChange={(event) => setReadinessFilter(event.target.value as ParticipantReadinessFilter)}>
                            <option value="all">{t('pages.participants.filters.all')}</option>
                            <option value="attention">{t('pages.participants.filters.attention')}</option>
                            <option value="ready">{t('pages.participants.filters.ready')}</option>
                        </select>
                    </label>
                </div>
            </section>

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
                            {t('common.cancel')}
                        </button>
                        <button className="button button-primary" type="submit" disabled={createMutation.isPending || updateMutation.isPending}>
                            {editingId ? t('pages.participants.saveParticipant') : t('common.create')}
                        </button>
                    </div>
                </form>
            </FormModal>

            {participantCards.length === 0 ? (
                <section className="card" style={{ display: 'grid', gap: '0.75rem' }}>
                    <h3 style={{ margin: 0 }}>{t('pages.participants.emptyState.title')}</h3>
                    <p className="muted" style={{ margin: 0 }}>{t('pages.participants.emptyState.description')}</p>
                    <div>
                        <button className="button button-primary" type="button" onClick={openCreateModal}>
                            <FontAwesomeIcon icon={faPlus} fixedWidth />
                            {t('pages.participants.emptyState.createAction')}
                        </button>
                    </div>
                </section>
            ) : filteredParticipants.length === 0 ? (
                <section className="card" style={{ display: 'grid', gap: '0.75rem' }}>
                    <h3 style={{ margin: 0 }}>{t('pages.participants.noResults.title')}</h3>
                    <p className="muted" style={{ margin: 0 }}>{t('pages.participants.noResults.description')}</p>
                    {hasFilters && (
                        <div>
                            <button
                                className="button button-secondary"
                                type="button"
                                onClick={() => {
                                    setSearchTerm('')
                                    setReadinessFilter('all')
                                }}
                            >
                                {t('pages.participants.filters.clear')}
                            </button>
                        </div>
                    )}
                </section>
            ) : (
                <div className="table-card participant-card-list">
                    {filteredParticipants.map(({ participant, warnings, ownerRow, validityState, displayName, address }) => {
                        const menuItems: ActionMenuItem[] = []

                        menuItems.push({
                            key: 'invitation',
                            label: t('pages.participants.sendInvitation'),
                            icon: <FontAwesomeIcon icon={faEnvelope} fixedWidth />,
                            disabled: invitationMutation.isPending || !participant.email,
                            onClick: () => invitationMutation.mutate(participant.id),
                        })

                        if (!ownerRow) {
                            menuItems.push({
                                key: 'delete',
                                label: t('common.delete'),
                                icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
                                disabled: deleteMutation.isPending || dialogLoading,
                                danger: true,
                                onClick: () => confirm({
                                    title: t('pages.participants.deleteTitle'),
                                    message: t('pages.participants.deleteMessage', { name: displayName }),
                                    confirmText: t('pages.participants.deleteConfirm'),
                                    isDangerous: true,
                                    onConfirm: () => deleteMutation.mutate(participant.id),
                                }),
                            })
                        }

                        const directAction = menuItems.length === 1 && !ownerRow ? menuItems[0] : null
                        const overflowItems = directAction ? [] : menuItems

                        return (
                            <article key={participant.id} className="participant-card">
                                <div className="participant-card-header">
                                    <div className="participant-card-title">
                                        <div className="participant-card-badges">
                                            {ownerRow && <span className="badge badge-info">{t('pages.participants.owner')}</span>}
                                            <span className={participantValidityBadgeClass(validityState)}>
                                                {t(`pages.participants.validity.${validityState}`)}
                                            </span>
                                            {warnings.length > 0 && (
                                                <span className="badge badge-warning">
                                                    <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />
                                                    {t('pages.participants.attentionNeeded')}
                                                </span>
                                            )}
                                        </div>
                                        <strong>{displayName}</strong>
                                    </div>

                                    <div className="participant-card-actions">
                                        <button className="button button-primary button-compact" type="button" onClick={() => startEdit(participant)}>
                                            <FontAwesomeIcon icon={faPen} fixedWidth />
                                            {t('common.edit')}
                                        </button>
                                        <button
                                            className="button button-secondary button-compact"
                                            type="button"
                                            onClick={() => downloadParticipantContractPdf(
                                                participant.id,
                                                `contract_${participant.last_name}_${participant.first_name}.pdf`,
                                            ).catch(() => pushToast(t('pages.participants.contractDownloadError'), 'error'))}
                                        >
                                            <FontAwesomeIcon icon={faDownload} fixedWidth />
                                            {t('pages.participants.downloadContract')}
                                        </button>
                                        {directAction && (
                                            <button
                                                className={`button ${directAction.danger ? 'button-danger' : 'button-secondary'} button-compact`}
                                                type="button"
                                                disabled={directAction.disabled}
                                                onClick={directAction.onClick}
                                            >
                                                {directAction.icon}
                                                {directAction.label}
                                            </button>
                                        )}
                                        {overflowItems.length > 0 && (
                                            <ActionMenu
                                                label={t('pages.participants.moreActions')}
                                                icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                                                items={overflowItems}
                                            />
                                        )}
                                    </div>
                                </div>

                                <div className="participant-card-body">
                                    <div className="participant-card-grid">
                                        <div className="participant-card-section">
                                            <div className="participant-card-label">{t('pages.participants.section.contact')}</div>
                                            <div>{participant.email || t('pages.participants.noEmailValue')}</div>
                                            <div className="muted">{participant.phone || t('pages.participants.noPhone')}</div>
                                        </div>
                                        <div className="participant-card-section">
                                            <div className="participant-card-label">{t('pages.participants.section.address')}</div>
                                            <div>{address || t('pages.participants.noAddressValue')}</div>
                                        </div>
                                        <div className="participant-card-section">
                                            <div className="participant-card-label">{t('pages.participants.section.validity')}</div>
                                            <div>{formatShortDate(participant.valid_from, settings)}</div>
                                            <div className="muted">{participant.valid_to ? formatShortDate(participant.valid_to, settings) : t('pages.participants.openEnded')}</div>
                                        </div>
                                    </div>

                                    {warnings.length > 0 && (
                                        <div className="participant-warning-list">
                                            {warnings.map((warning) => (
                                                <span key={warning} className="badge badge-warning">{warning}</span>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </article>
                        )
                    })}
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
