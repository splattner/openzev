import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { ParticipantCardsSection } from '../features/participants/ParticipantCardsSection'
import type { ParticipantValidityState } from '../features/participants/types'
import {
    ParticipantCredentialsNotice,
    type ParticipantCredentialsNoticeData,
} from '../features/participants/ParticipantCredentialsNotice'
import { ParticipantFormModal } from '../features/participants/ParticipantFormModal'
import { ParticipantsMap } from '../features/participants/ParticipantsMap'
import { ParticipantToolbar, type ParticipantReadinessFilter } from '../features/participants/ParticipantToolbar'
import {
    createParticipant,
    deleteParticipant,
    downloadParticipantContractPdf,
    fetchParticipants,
    fetchZevs,
    sendParticipantInvitation,
    updateParticipant,
} from '../lib/api/zev'
import { formatApiError } from '../lib/api/errors'
import { useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { queryKeys } from '../lib/api/queryKeys'
import { useTranslation } from 'react-i18next'
import { useToast } from '../lib/toast'
import { todayLocalIso } from '../lib/dates'
import type { Participant, ParticipantInput } from '../types/api'

function getParticipantValidityState(participant: Participant, todayIso: string): ParticipantValidityState {
    if (participant.valid_from > todayIso) return 'upcoming'
    if (participant.valid_to && participant.valid_to < todayIso) return 'ended'
    return 'current'
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
    const { data, isLoading, isError } = useQuery({
        queryKey: queryKeys.zev.participants(selectedZevId || undefined),
        queryFn: fetchParticipants,
    })
    const zevsQuery = useQuery({ queryKey: queryKeys.zev.list(), queryFn: fetchZevs })
    const [editingId, setEditingId] = useState<string | null>(null)
    const [showModal, setShowModal] = useState(false)
    const [searchTerm, setSearchTerm] = useState('')
    const [readinessFilter, setReadinessFilter] = useState<ParticipantReadinessFilter>('all')
    const [credentialsNotice, setCredentialsNotice] = useState<ParticipantCredentialsNoticeData | null>(null)

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
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.participants(selectedZevId || undefined) })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.participants.messages.createFailed')), 'error'),
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, payload }: { id: string; payload: Partial<ParticipantInput> }) => updateParticipant(id, payload),
        onSuccess: () => {
            setEditingId(null)
            setShowModal(false)
            pushToast(t('pages.participants.messages.updated'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.participants(selectedZevId || undefined) })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.participants.messages.updateFailed')), 'error'),
    })

    const deleteMutation = useMutation({
        mutationFn: deleteParticipant,
        onSuccess: () => {
            pushToast(t('pages.participants.messages.deleted'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.participants(selectedZevId || undefined) })
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
        setShowModal(true)
    }

    function openCreateModal() {
        if (!selectedZevId) {
            pushToast(t('pages.participants.messages.selectZev'), 'error')
            return
        }
        setEditingId(null)
        setShowModal(true)
    }

    function closeModal() {
        setShowModal(false)
        setEditingId(null)
    }

    function submit(payload: ParticipantInput) {
        if (!selectedZevId) {
            pushToast(t('pages.participants.messages.selectZev'), 'error')
            return
        }

        if (editingId) {
            updateMutation.mutate({ id: editingId, payload: { ...payload, zev: selectedZevId } })
            return
        }

        createMutation.mutate({ ...payload, zev: selectedZevId })
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
    const editingParticipant = participants.find((participant) => participant.id === editingId)
    const todayIso = todayLocalIso()
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

    function clearFilters() {
        setSearchTerm('')
        setReadinessFilter('all')
    }

    function downloadContract(participant: Participant) {
        void downloadParticipantContractPdf(
            participant.id,
            `contract_${participant.last_name}_${participant.first_name}.pdf`,
        ).catch(() => pushToast(t('pages.participants.contractDownloadError'), 'error'))
    }

    function confirmDeleteParticipant(participant: Participant, displayName: string) {
        confirm({
            title: t('pages.participants.deleteTitle'),
            message: t('pages.participants.deleteMessage', { name: displayName }),
            confirmText: t('pages.participants.deleteConfirm'),
            isDangerous: true,
            onConfirm: () => deleteMutation.mutate(participant.id),
        })
    }

    return (
        <div className="page-stack">
            <header>
                <h2>{t('pages.participants.title')}</h2>
                <p className="muted">{t('pages.participants.description')}</p>
            </header>

            {credentialsNotice && <ParticipantCredentialsNotice notice={credentialsNotice} onDismiss={() => setCredentialsNotice(null)} />}

            <ParticipantToolbar
                totalCount={participantCards.length}
                ownerCount={ownerCount}
                warningCount={warningCount}
                noMeteringCount={noMeteringCount}
                searchTerm={searchTerm}
                readinessFilter={readinessFilter}
                onSearchTermChange={setSearchTerm}
                onReadinessFilterChange={setReadinessFilter}
                onOpenCreateModal={openCreateModal}
            />

            <ParticipantFormModal
                isOpen={showModal}
                title={editingId ? t('pages.participants.editTitle') : t('pages.participants.createTitle')}
                onClose={closeModal}
                onSubmit={submit}
                initialParticipant={editingParticipant}
                selectedZevId={selectedZevId || ''}
                isPending={createMutation.isPending || updateMutation.isPending}
            />

            <section className="card">
                <h3 style={{ marginTop: 0 }}>{t('pages.participants.map.title')}</h3>
                <ParticipantsMap
                    participants={participantCards.map((entry) => ({
                        id: entry.participant.id,
                        displayName: entry.displayName,
                        address: entry.address,
                        buildingFootprint: entry.participant.building_footprint,
                    }))}
                />
            </section>

            <ParticipantCardsSection
                participantCards={participantCards}
                filteredParticipants={filteredParticipants}
                hasFilters={hasFilters}
                settings={settings}
                onOpenCreateModal={openCreateModal}
                onClearFilters={clearFilters}
                onStartEdit={startEdit}
                onDownloadContract={downloadContract}
                onInvite={(participantId) => invitationMutation.mutate(participantId)}
                onConfirmDelete={confirmDeleteParticipant}
                invitationPending={invitationMutation.isPending}
                deletePendingOrDialogLoading={deleteMutation.isPending || dialogLoading}
            />

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
