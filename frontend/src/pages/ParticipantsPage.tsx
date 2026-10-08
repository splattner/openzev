import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useEffectEvent, useLayoutEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { ParticipantCardsSection } from '../features/participants/ParticipantCardsSection'
import type { ParticipantValidityState } from '../features/participants/types'
import {
    ParticipantOnboardingNotice,
    type ParticipantOnboardingNoticeData,
} from '../features/participants/ParticipantOnboardingNotice'
import { ParticipantFormModal } from '../features/participants/ParticipantFormModal'
import { useParticipantAccountLinking } from '../features/participants/useParticipantAccountLinking'
import { BuildingsMap } from '../features/participants/BuildingsMap'
import { ParticipantToolbar, type ParticipantReadinessFilter } from '../features/participants/ParticipantToolbar'
import {
    createParticipant,
    deleteParticipant,
    downloadIssuedParticipantContractPdf,
    downloadParticipantContractPdf,
    fetchBuildings,
    fetchParticipantGeocodingEnabled,
    fetchParticipants,
    getOnboardingLink,
    revokeOnboardingLink,
    sendOnboardingLink,
    updateParticipant,
} from '../lib/api/zev'
import { formatApiError } from '../lib/api/errors'
import { useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useWriteScope } from '../lib/useWriteScope'
import { useManagedZev } from '../lib/managedZev'
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'
import { queryKeys } from '../lib/api/queryKeys'
import { PageSkeleton } from '../components/PageSkeleton'
import { useTranslation } from 'react-i18next'
import { useToast } from '../lib/toast'
import { todayBusinessIso } from '../lib/dates'
import { formatParticipantName } from '../lib/participantFormat'
import { getTitleLabelMap } from '../lib/participantTitle'
import type { Participant, ParticipantInput } from '../types/api'
import { PageHeader } from '../components/PageHeader'
import { Notice } from '../components/Notice'
import { ScopeGuard } from '../components/ScopeGuard'

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
    const { selectedZevId, selectedZev, isLoading: scopeLoading } = useManagedZev()
    const { t } = useTranslation()
    const scopeNote = useScopeNote()
    const [searchParams, setSearchParams] = useSearchParams()
    const focusId = searchParams.get('focus')
    const focusField = searchParams.get('field')
    const [highlightedId, setHighlightedId] = useState<string | null>(null)
    const { isZevScope, canWriteSelectedCommunity } = useCommunityAccess()
    const { scope, isCurrent, assertWritable } = useWriteScope({ selectedZevId, canWrite: canWriteSelectedCommunity, accountId: user?.id }, t('common.error'))
    const cancelConfirmation = useEffectEvent(handleCancel)
    const isManagedScope = isZevScope
    const accountLinking = useParticipantAccountLinking({ isAdmin: user?.role === 'admin', confirm })
    const { data, isLoading, isError, isFetching, refetch } = useQuery({
        queryKey: queryKeys.zev.participants(selectedZevId || undefined),
        queryFn: fetchParticipants,
        enabled: !!selectedZevId && selectedZev?.id === selectedZevId,
    })
    // Off by default (#796) — the map section renders only once this is
    // confirmed true, rather than rendering with no data while loading or on
    // error, since a cached building footprint from before the flag was
    // turned off could otherwise still surface on a disabled instance.
    const geocodingEnabledQuery = useQuery({
        queryKey: queryKeys.zev.participantGeocodingEnabled(),
        queryFn: fetchParticipantGeocodingEnabled,
    })
    // The map draws the community's buildings, not billing addresses (#890).
    const buildingsQuery = useQuery({
        queryKey: queryKeys.zev.buildings(selectedZevId || ''),
        queryFn: () => fetchBuildings(selectedZevId || ''),
        enabled: geocodingEnabledQuery.data === true && isManagedScope && !!selectedZevId,
    })
    const [editingId, setEditingId] = useState<string | null>(null)
    const [showModal, setShowModal] = useState(false)
    const [searchTerm, setSearchTerm] = useState('')
    const [readinessFilter, setReadinessFilter] = useState<ParticipantReadinessFilter>('all')
    const [onboardingNotice, setOnboardingNotice] = useState<ParticipantOnboardingNoticeData | null>(null)
    const [modalFocusField, setModalFocusField] = useState<'valid_to' | null>(null)

    const titleLabelByValue = useMemo(() => getTitleLabelMap(t), [t])

    const createMutation = useMutation({
        mutationFn: ({ payload, scope: submittingScope }: { payload: ParticipantInput; scope: typeof scope }) => {
            assertWritable(submittingScope)
            return createParticipant(payload)
        },
        onSuccess: (_, variables) => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.participants(variables.scope.selectedZevId || undefined) })
            if (!isCurrent(variables.scope)) return
            setShowModal(false)
            pushToast(t('pages.participants.messages.created'), 'success')
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope)) pushToast(formatApiError(error, t('pages.participants.messages.createFailed')), 'error')
        },
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, payload, scope: submittingScope }: { id: string; payload: Partial<ParticipantInput>; scope: typeof scope }) => {
            assertWritable(submittingScope)
            return updateParticipant(id, payload)
        },
        onSuccess: (_, variables) => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.participants(variables.scope.selectedZevId || undefined) })
            if (!isCurrent(variables.scope)) return
            setEditingId(null)
            setShowModal(false)
            pushToast(t('pages.participants.messages.updated'), 'success')
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope)) pushToast(formatApiError(error, t('pages.participants.messages.updateFailed')), 'error')
        },
    })

    const deleteMutation = useMutation({
        mutationFn: ({ id, scope: submittingScope }: { id: string; scope: typeof scope }) => {
            assertWritable(submittingScope)
            return deleteParticipant(id)
        },
        onSuccess: (_, variables) => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.participants(variables.scope.selectedZevId || undefined) })
            if (!isCurrent(variables.scope)) return
            pushToast(t('pages.participants.messages.deleted'), 'success')
        },
    })

    function participantDisplayName(participantId: string): string {
        const participant = data?.find((entry) => entry.id === participantId)
        return participant ? `${participant.first_name} ${participant.last_name}` : t('pages.participants.fallbackName')
    }

    const sendLinkMutation = useMutation({
        mutationFn: ({ participantId, scope: submittingScope }: { participantId: string; scope: typeof scope }) => {
            assertWritable(submittingScope)
            return sendOnboardingLink(participantId)
        },
        onSuccess: (result, variables) => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.participants(variables.scope.selectedZevId) })
            if (!isCurrent(variables.scope)) return
            const { participantId } = variables
            const participant = data?.find((entry) => entry.id === participantId)
            pushToast(
                t('pages.participants.messages.onboardingLinkSent', { email: participant?.email || '' }),
                'success',
            )
            setOnboardingNotice({
                participantName: participantDisplayName(participantId),
                onboardingUrl: result.onboarding_url,
                onboardingExpiresAt: result.onboarding_expires_at,
                message: t('pages.participants.messages.onboardingLinkSentDetail'),
            })
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope)) pushToast(formatApiError(error, t('pages.participants.messages.onboardingLinkFailed')), 'error')
        },
    })

    const copyLinkMutation = useMutation({
        mutationFn: ({ participantId, scope: submittingScope }: { participantId: string; scope: typeof scope }) => {
            assertWritable(submittingScope)
            return getOnboardingLink(participantId)
        },
        onSuccess: (result, variables) => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.participants(variables.scope.selectedZevId) })
            if (!isCurrent(variables.scope)) return
            const { participantId } = variables
            setOnboardingNotice({
                participantName: participantDisplayName(participantId),
                onboardingUrl: result.onboarding_url,
                onboardingExpiresAt: result.onboarding_expires_at,
                message: t('pages.participants.messages.onboardingLinkCopiedDetail'),
            })
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope)) pushToast(formatApiError(error, t('pages.participants.messages.onboardingLinkFailed')), 'error')
        },
    })

    const revokeLinkMutation = useMutation({
        mutationFn: ({ participantId, scope: submittingScope }: { participantId: string; scope: typeof scope }) => {
            assertWritable(submittingScope)
            return revokeOnboardingLink(participantId)
        },
        onSuccess: (_, variables) => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.participants(variables.scope.selectedZevId) })
            if (!isCurrent(variables.scope)) return
            pushToast(t('pages.participants.messages.onboardingLinkRevoked'), 'success')
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope)) pushToast(formatApiError(error, t('pages.participants.messages.onboardingLinkFailed')), 'error')
        },
    })

    const onboardingLinkPending = sendLinkMutation.isPending || copyLinkMutation.isPending || revokeLinkMutation.isPending

    function formatParticipantNameWithTitle(participant: Participant): string {
        const titleLabel = participant.title ? (titleLabelByValue[participant.title as keyof typeof titleLabelByValue] ?? '') : ''
        return formatParticipantName(participant, titleLabel)
    }

    function startEdit(participant: Participant) {
        setEditingId(participant.id)
        setModalFocusField(null)
        setShowModal(true)
    }

    function openCreateModal() {
        if (!selectedZevId) {
            pushToast(t('pages.participants.messages.selectZev'), 'error')
            return
        }
        setEditingId(null)
        setModalFocusField(null)
        setShowModal(true)
    }

    function closeModal() {
        setShowModal(false)
        setEditingId(null)
        setModalFocusField(null)
    }

    useLayoutEffect(() => {
        setShowModal(false)
        setEditingId(null)
        setModalFocusField(null)
        setOnboardingNotice(null)
    }, [scope])

    useEffect(() => {
        cancelConfirmation()
    }, [scope])

    // Destination contract (spec §7) for participant-validity links
    // (`?focus=<id>&field=valid_to`). Consuming the URL params (below) must
    // not tear down the highlight timers, so consumption and the scroll/
    // flash lifecycle are separate effects.
    useEffect(() => {
        if (!focusId || isLoading) return
        if (focusField === 'valid_to' && (scopeLoading || (!!selectedZevId && !selectedZev))) return
        const inScope = (data ?? []).some(
            (participant) =>
                participant.id === focusId
                && (!isManagedScope || participant.zev === selectedZevId),
        )
        if (!inScope) return
        // A stale search/readiness filter may keep the card off the page.
        setSearchTerm('')
        setReadinessFilter('all')
        setHighlightedId(focusId)
        if (focusField === 'valid_to' && canWriteSelectedCommunity) {
            const target = (data ?? []).find((participant) => participant.id === focusId)
            if (target) {
                setEditingId(target.id)
                setModalFocusField('valid_to')
                setShowModal(true)
            }
        }
        // Drop the params so the deep link is consumed (and re-linking works):
        // the focusId dependency goes null and this effect stops re-running.
        const params = new URLSearchParams(searchParams)
        params.delete('focus')
        params.delete('field')
        setSearchParams(params, { replace: true })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [focusId, focusField, isLoading, data, isManagedScope, selectedZevId, selectedZev, scopeLoading, canWriteSelectedCommunity])

    useEffect(() => {
        if (!highlightedId) return
        const timers = [
            window.setTimeout(() => {
                document
                    .getElementById(`participant-card-${highlightedId}`)
                    ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
            }, 0),
            window.setTimeout(() => setHighlightedId(null), 4000),
        ]
        return () => timers.forEach((timer) => window.clearTimeout(timer))
    }, [highlightedId])

    function submit(payload: ParticipantInput) {
        if (!isCurrent(scope)) return
        if (!selectedZevId || !canWriteSelectedCommunity) {
            pushToast(t('pages.participants.messages.selectZev'), 'error')
            return
        }

        if (editingId) {
            updateMutation.mutate({ id: editingId, payload: { ...payload, zev: selectedZevId }, scope })
            return
        }

        createMutation.mutate({ payload: { ...payload, zev: selectedZevId }, scope })
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

    const header = (
        <PageHeader
            eyebrow={selectedZev?.name}
            communitySwitch
            scopeNote={scopeNote}
            title={t('pages.participants.title')}
            description={t('pages.participants.description')}
        />
    )

    const participants = (data ?? []).filter((participant) => !isManagedScope || participant.zev === selectedZevId)
    const editingParticipant = participants.find((participant) => participant.id === editingId)
    const todayIso = todayBusinessIso()
    const participantCards = [...participants]
        .map((participant) => {
            const warnings = participantWarnings(participant)
            // The party's roles held today (#761): issuer, representative, landowner.
            const roles = [...new Set((participant.roles ?? [])
                .filter((role) => role.valid_from <= todayIso)
                .map((role) => role.role))]
            const validityState = getParticipantValidityState(participant, todayIso)

            return {
                participant,
                warnings,
                roles,
                validityState,
                displayName: formatParticipantNameWithTitle(participant),
                address: formatParticipantAddress(participant),
            }
        })
        .sort((left, right) => {
            const leftIssuer = left.roles.includes('issuer')
            if (leftIssuer !== right.roles.includes('issuer')) {
                return leftIssuer ? -1 : 1
            }
            return left.displayName.localeCompare(right.displayName)
        })
    const normalizedSearch = searchTerm.trim().toLowerCase()
    const filteredParticipants = participantCards.filter((entry) => {
        const matchesReadiness = readinessFilter === 'all'
            || (readinessFilter === 'attention' && entry.warnings.length > 0)
            || (readinessFilter === 'noMetering' && !entry.participant.has_metering_point_assignment)
        const matchesSearch = !normalizedSearch
            || entry.displayName.toLowerCase().includes(normalizedSearch)
            || (entry.participant.email || '').toLowerCase().includes(normalizedSearch)
            || entry.address.toLowerCase().includes(normalizedSearch)

        return matchesReadiness && matchesSearch
    })
    const warningCount = participantCards.filter((entry) => entry.warnings.length > 0).length
    const noMeteringCount = participantCards.filter((entry) => !entry.participant.has_metering_point_assignment).length

    function clearFilters() {
        setSearchTerm('')
        setReadinessFilter('all')
    }

    function downloadContract(participant: Participant) {
        // A viewer may read the issued contract but not issue a new version.
        // Managers of a disabled ZEV keep read access only.
        const download = canWriteSelectedCommunity ? downloadParticipantContractPdf : downloadIssuedParticipantContractPdf
        void download(
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
            onConfirm: () => {
                if (scope.canWrite && isCurrent(scope)) deleteMutation.mutate({ id: participant.id, scope })
            },
        })
    }

    return (
        <div className="page-stack">
            {header}
            <ScopeGuard>
            {isLoading ? <PageSkeleton variant="cardList" /> : isError ? (
                <Notice tone="error" onRetry={() => void refetch()} isRetrying={isFetching}>{t('common.error')}</Notice>
            ) : <>
            {onboardingNotice && <ParticipantOnboardingNotice notice={onboardingNotice} onDismiss={() => setOnboardingNotice(null)} />}

            <ParticipantToolbar
                totalCount={participantCards.length}
                warningCount={warningCount}
                noMeteringCount={noMeteringCount}
                searchTerm={searchTerm}
                readinessFilter={readinessFilter}
                onSearchTermChange={setSearchTerm}
                onReadinessFilterChange={setReadinessFilter}
                onOpenCreateModal={openCreateModal}
                readOnly={!canWriteSelectedCommunity}
            />

            <ParticipantFormModal
                isOpen={showModal}
                title={editingId ? t('pages.participants.editTitle') : t('pages.participants.createTitle')}
                onClose={closeModal}
                onSubmit={submit}
                initialParticipant={editingParticipant}
                selectedZevId={selectedZevId || ''}
                isPending={createMutation.isPending || updateMutation.isPending}
                focusField={modalFocusField}
            />

            {geocodingEnabledQuery.data === true && isManagedScope && (
                <section className="card">
                    <h3 style={{ marginTop: 0 }}>{t('pages.participants.map.title')}</h3>
                    <BuildingsMap buildings={buildingsQuery.data ?? []} />
                </section>
            )}

            <ParticipantCardsSection
                participantCards={participantCards}
                filteredParticipants={filteredParticipants}
                settings={settings}
                onOpenCreateModal={openCreateModal}
                onClearFilters={clearFilters}
                onStartEdit={startEdit}
                onDownloadContract={downloadContract}
                onSendOnboardingLink={(participantId) => sendLinkMutation.mutate({ participantId, scope })}
                onCopyOnboardingLink={(participantId) => copyLinkMutation.mutate({ participantId, scope })}
                onRevokeOnboardingLink={(participantId) => revokeLinkMutation.mutate({ participantId, scope })}
                onConfirmDelete={confirmDeleteParticipant}
                canLinkAccount={accountLinking.canLink}
                canUnlinkAccount={accountLinking.canUnlink}
                onLinkAccount={accountLinking.openLink}
                onUnlinkAccount={(participant, name) =>
                    accountLinking.confirmUnlink(participant, name, participant.account_username ?? '')}
                accountActionPending={accountLinking.pending || dialogLoading}
                onboardingLinkPending={onboardingLinkPending}
                deletePendingOrDialogLoading={deleteMutation.isPending || dialogLoading}
                focusParticipantId={highlightedId}
                readOnly={!canWriteSelectedCommunity}
            />

            {accountLinking.linkModal}

            {dialog && (
                <ConfirmDialog
                    {...dialog}
                    isLoading={dialogLoading}
                    onConfirm={handleConfirm}
                    onCancel={handleCancel}
                />
            )}
            </>}
            </ScopeGuard>
        </div>
    )
}
