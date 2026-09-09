import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { useConfirmDialog } from '../../components/ConfirmDialog'
import {
    createMeteringPoint,
    createMeteringPointAssignment,
    deleteMeteringPoint,
    deleteMeteringPointReadings,
    deleteMeteringPointAssignment,
    fetchMeteringPointAssignments,
    fetchMeteringPoints,
    fetchParticipants,
    updateMeteringPoint,
    updateMeteringPointAssignment,
} from '../../lib/api/zev'
import { formatApiError } from '../../lib/api/errors'
import { fetchMeteringDataQualityStatus } from '../../lib/api/metering'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { todayLocalIso } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import {
    defaultAssignmentForm,
    defaultMeteringPointForm,
    getMeteringPointHealth,
    getMeteringPointHealthWindow,
    getNextAssignmentGuidance,
    isAssignmentCurrent,
    isMeteringPointHolderLess,
    METERING_POINT_FILTER_KEYS,
    meteringPointNeedsAttention,
    readMeteringPointAssignmentFilter,
    readMeteringPointAttentionFilter,
    readMeteringPointStatusFilter,
    readMeteringPointTypeFilter,
    type MeteringPointAssignmentFilter,
    type MeteringPointAttentionFilter,
    type MeteringPointHealth,
    type MeteringPointStatusFilter,
    type MeteringPointTypeFilter,
} from './useMeteringPointForms'
import type {
    MeteringPoint,
    MeteringPointAssignment,
    MeteringPointAssignmentInput,
    MeteringPointDataQuality,
    MeteringPointInput,
} from '../../types/api'

export function getScopedAndFilteredMeteringPoints(
    points: MeteringPoint[],
    {
        selectedZevId,
        canManageMeteringPoints,
        searchTerm,
        statusFilter,
        typeFilter,
        attentionFilter = 'all',
        needsAttentionByMeteringPoint,
        assignmentFilter = 'all',
        isAssignedByMeteringPoint,
        participantNamesByMeteringPoint,
    }: {
        selectedZevId: string | null
        canManageMeteringPoints: boolean
        searchTerm: string
        statusFilter: MeteringPointStatusFilter
        typeFilter: MeteringPointTypeFilter
        attentionFilter?: MeteringPointAttentionFilter
        /** Only consulted when `attentionFilter` is `'attention'`; a missing entry does not match. */
        needsAttentionByMeteringPoint?: Map<string, boolean>
        assignmentFilter?: MeteringPointAssignmentFilter
        /** Only consulted when `assignmentFilter` isn't `'all'`; a missing entry counts as unassigned. */
        isAssignedByMeteringPoint?: Map<string, boolean>
        /** Space-joined names of every participant ever assigned to the meter, so search can match "which meter is Anna's?". */
        participantNamesByMeteringPoint?: Map<string, string>
    },
) {
    const scopedMeteringPoints = points.filter(
        (point) => !canManageMeteringPoints || !selectedZevId || point.zev === selectedZevId,
    )

    const normalizedSearch = searchTerm.trim().toLowerCase()
    const meteringPoints = scopedMeteringPoints.filter((point) => {
        const matchesStatus = statusFilter === 'all'
            || (statusFilter === 'active' && point.is_active)
            || (statusFilter === 'inactive' && !point.is_active)
        const matchesType = typeFilter === 'all' || point.meter_type === typeFilter
        const matchesSearch = !normalizedSearch
            || point.meter_id.toLowerCase().includes(normalizedSearch)
            || (point.location_description ?? '').toLowerCase().includes(normalizedSearch)
            || (participantNamesByMeteringPoint?.get(point.id) ?? '').toLowerCase().includes(normalizedSearch)
        const matchesAttention = attentionFilter === 'all'
            || !!needsAttentionByMeteringPoint?.get(point.id)
        const isAssigned = !!isAssignedByMeteringPoint?.get(point.id)
        const matchesAssignment = assignmentFilter === 'all'
            || (assignmentFilter === 'assigned' && isAssigned)
            || (assignmentFilter === 'unassigned' && !isAssigned)

        return matchesStatus && matchesType && matchesSearch && matchesAttention && matchesAssignment
    })

    return { scopedMeteringPoints, meteringPoints }
}

export type MeteringPointCounts = {
    activeCount: number
    inactiveCount: number
    /** Meters with a holder *today* — an assignment that already ended (or has yet to start) does not count. */
    assignedCount: number
    /** Meters flagged by `meteringPointNeedsAttention` — see #623. */
    needsAttentionCount: number
}

export function getMeteringPointCounts(
    scopedMeteringPoints: MeteringPoint[],
    assignmentsByMeteringPoint: Map<string, MeteringPointAssignment[]>,
    todayIso: string,
    needsAttentionByMeteringPoint: Map<string, boolean> = new Map(),
): MeteringPointCounts {
    const activeCount = scopedMeteringPoints.filter((point) => point.is_active).length
    const inactiveCount = scopedMeteringPoints.length - activeCount
    const assignedCount = scopedMeteringPoints.filter((point) =>
        (assignmentsByMeteringPoint.get(point.id) ?? []).some((assignment) => isAssignmentCurrent(assignment, todayIso)),
    ).length
    const needsAttentionCount = scopedMeteringPoints.filter((point) => needsAttentionByMeteringPoint.get(point.id)).length

    return { activeCount, inactiveCount, assignedCount, needsAttentionCount }
}

export function useMeteringPointActions({
    selectedZevId,
    canManageMeteringPoints,
}: {
    selectedZevId: string | null
    canManageMeteringPoints: boolean
}) {
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { settings } = useAppSettings()
    const { t } = useTranslation()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    // Plain value, not a hook — safe to compute once up front and reuse
    // everywhere below (assignment prefill, counts, health).
    const todayIso = todayLocalIso()

    // ── Modal form state ──────────────────────────────────────────────────────────

    // Metering point modal
    const [mpForm, setMpForm] = useState<MeteringPointInput>(defaultMeteringPointForm())
    const [editingMpId, setEditingMpId] = useState<string | null>(null)
    const [showMpModal, setShowMpModal] = useState(false)

    // Assignment modal
    const [assignForm, setAssignForm] = useState<MeteringPointAssignmentInput>(defaultAssignmentForm())
    const [editingAssignId, setEditingAssignId] = useState<string | null>(null)
    const [showAssignModal, setShowAssignModal] = useState(false)
    const [selectedMpId, setSelectedMpId] = useState<string | null>(null)
    const [assignHasOpenEndedWarning, setAssignHasOpenEndedWarning] = useState(false)

    // Delete data modal
    const [showDeleteDataModal, setShowDeleteDataModal] = useState(false)
    const [deleteDataTarget, setDeleteDataTarget] = useState<MeteringPoint | null>(null)
    const [deleteDataMode, setDeleteDataMode] = useState<'all' | 'range'>('all')
    const [deleteDataFrom, setDeleteDataFrom] = useState('')
    const [deleteDataTo, setDeleteDataTo] = useState('')

    // ── Filtering — mirrored into the URL (#625) ────────────────────────────────────
    //
    // Local state is still the source of truth React renders from (matches the
    // metering_point/tab pattern MeteringChartPage already uses) — each setter
    // below just also writes the corresponding query param, and the lazy
    // useState initializers below read it back on mount. That round-trip is
    // what makes a filtered view survive "click Chart, then Back": the click
    // unmounts this page for a different route, and Back remounts it fresh
    // with the URL (and therefore the filters) already restored, no separate
    // rehydration effect required.
    const [searchParams, setSearchParams] = useSearchParams()
    const FILTER = METERING_POINT_FILTER_KEYS

    const [searchTerm, setSearchTermState] = useState(() => searchParams.get(FILTER.search) ?? '')
    const [statusFilter, setStatusFilterState] = useState<MeteringPointStatusFilter>(
        () => readMeteringPointStatusFilter(searchParams.get(FILTER.status)),
    )
    const [typeFilter, setTypeFilterState] = useState<MeteringPointTypeFilter>(
        () => readMeteringPointTypeFilter(searchParams.get(FILTER.type)),
    )
    const [attentionFilter, setAttentionFilterState] = useState<MeteringPointAttentionFilter>(
        () => readMeteringPointAttentionFilter(searchParams.get(FILTER.attention)),
    )
    const [assignmentFilter, setAssignmentFilterState] = useState<MeteringPointAssignmentFilter>(
        () => readMeteringPointAssignmentFilter(searchParams.get(FILTER.assignment)),
    )

    /** Sets or removes one query param, without touching the others already there. */
    function writeFilterParam(key: string, value: string, isDefault: boolean) {
        setSearchParams((previous) => {
            const next = new URLSearchParams(previous)
            if (isDefault) next.delete(key)
            else next.set(key, value)
            return next
        }, { replace: true })
    }

    function setSearchTerm(value: string) {
        setSearchTermState(value)
        writeFilterParam(FILTER.search, value, value === '')
    }
    function setStatusFilter(value: MeteringPointStatusFilter) {
        setStatusFilterState(value)
        writeFilterParam(FILTER.status, value, value === 'all')
    }
    function setTypeFilter(value: MeteringPointTypeFilter) {
        setTypeFilterState(value)
        writeFilterParam(FILTER.type, value, value === 'all')
    }
    function setAttentionFilter(value: MeteringPointAttentionFilter) {
        setAttentionFilterState(value)
        writeFilterParam(FILTER.attention, value, value === 'all')
    }
    function setAssignmentFilter(value: MeteringPointAssignmentFilter) {
        setAssignmentFilterState(value)
        writeFilterParam(FILTER.assignment, value, value === 'all')
    }

    function clearFilters() {
        setSearchTermState('')
        setStatusFilterState('all')
        setTypeFilterState('all')
        setAttentionFilterState('all')
        setAssignmentFilterState('all')
        setSearchParams((previous) => {
            const next = new URLSearchParams(previous)
            Object.values(FILTER).forEach((key) => next.delete(key))
            return next
        }, { replace: true })
    }

    // ── Queries ──────────────────────────────────────────────────────────────────

    const participantsQuery = useQuery({
        queryKey: queryKeys.zev.participants(selectedZevId || undefined),
        queryFn: fetchParticipants,
        enabled: canManageMeteringPoints,
    })
    const meteringPointsQuery = useQuery({
        queryKey: queryKeys.metering.points(selectedZevId || undefined),
        queryFn: fetchMeteringPoints,
    })
    const assignmentsQuery = useQuery({
        queryKey: queryKeys.metering.pointAssignments(),
        queryFn: () => fetchMeteringPointAssignments(),
        enabled: canManageMeteringPoints,
    })
    // Not role-gated: the endpoint scopes readings to what the caller may
    // see (a participant's own assigned meters), so the health indicator
    // stays accurate for every role instead of being hidden for some (#623).
    const healthWindow = getMeteringPointHealthWindow(todayIso)
    const dataQualityQuery = useQuery({
        queryKey: queryKeys.metering.qualityStatus(
            healthWindow.from,
            healthWindow.to,
            canManageMeteringPoints ? (selectedZevId || undefined) : undefined,
            undefined,
        ),
        queryFn: () =>
            fetchMeteringDataQualityStatus({
                dateFrom: healthWindow.from,
                dateTo: healthWindow.to,
                zevId: canManageMeteringPoints ? (selectedZevId || undefined) : undefined,
            }),
    })

    // ── Mutations ──────────────────────────────────────────────────────────────────

    const saveMpMutation = useMutation({
        mutationFn: ({ id, payload }: { id?: string; payload: MeteringPointInput }) =>
            id ? updateMeteringPoint(id, payload) : createMeteringPoint(payload),
        onSuccess: (_, variables) => {
            closeMpModal()
            pushToast(
                variables.id ? t('pages.meteringPoints.messages.updated') : t('pages.meteringPoints.messages.created'),
                'success',
            )
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.points(selectedZevId || undefined) })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.meteringPoints.messages.saveFailed')), 'error'),
    })

    const deleteMpMutation = useMutation({
        mutationFn: deleteMeteringPoint,
        onSuccess: () => {
            pushToast(t('pages.meteringPoints.messages.deleted'), 'success')
            // Deleting a metering point cascades to its readings and assignment
            // history (MeterReading/MeteringPointAssignment both CASCADE on
            // metering_point), so every reading-derived view is stale too —
            // invalidate the whole metering namespace rather than enumerating keys.
            void queryClient.invalidateQueries({ queryKey: ['metering'] })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.meteringPoints.messages.deleteFailed')), 'error'),
    })

    const saveAssignMutation = useMutation({
        mutationFn: ({ id, payload }: { id?: string; payload: MeteringPointAssignmentInput }) =>
            id ? updateMeteringPointAssignment(id, payload) : createMeteringPointAssignment(payload),
        onSuccess: (_, variables) => {
            closeAssignModal()
            pushToast(
                variables.id
                    ? t('pages.meteringPoints.messages.assignmentUpdated')
                    : t('pages.meteringPoints.messages.assignmentCreated'),
                'success',
            )
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.pointAssignments() })
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.points(selectedZevId || undefined) })
            // Participants derive has_metering_point_assignment / metering_points
            // from these rows, so their readiness state changes too.
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.participants(selectedZevId || undefined) })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.meteringPoints.messages.assignmentSaveFailed')), 'error'),
    })

    const deleteAssignMutation = useMutation({
        mutationFn: deleteMeteringPointAssignment,
        onSuccess: () => {
            pushToast(t('pages.meteringPoints.messages.assignmentRemoved'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.pointAssignments() })
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.points(selectedZevId || undefined) })
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.participants(selectedZevId || undefined) })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.meteringPoints.messages.assignmentRemoveFailed')), 'error'),
    })

    const deleteMeteringDataMutation = useMutation({
        mutationFn: ({
            meteringPointId,
            payload,
        }: {
            meteringPointId: string
            payload: { delete_all: boolean; date_from?: string; date_to?: string }
        }) => deleteMeteringPointReadings(meteringPointId, payload),
        onSuccess: (result) => {
            pushToast(t('pages.meteringPoints.deleteData.success', { count: result.deleted_count }), 'success')
            closeDeleteDataModal()
            // Deleted readings affect every reading-derived view (chart, raw
            // data, dashboard summary, data-quality status).
            void queryClient.invalidateQueries({ queryKey: ['metering'] })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.meteringPoints.deleteData.failed')), 'error'),
    })

    // Declared ahead of the form handlers below: openCreateAssignModal reads
    // it to prefill the next assignment's valid_from (see #619).
    const assignmentsByMeteringPoint = useMemo(() => {
        const map = new Map<string, MeteringPointAssignment[]>()
        for (const a of assignmentsQuery.data ?? []) {
            const list = map.get(a.metering_point) ?? []
            list.push(a)
            map.set(a.metering_point, list)
        }
        return map
    }, [assignmentsQuery.data])

    // ── Form handlers ──────────────────────────────────────────────────────────────

    function openCreateMpModal() {
        setEditingMpId(null)
        setMpForm((previous) => ({
            ...defaultMeteringPointForm(),
            zev: canManageMeteringPoints ? (selectedZevId || '') : previous.zev,
        }))
        setShowMpModal(true)
    }

    function openEditMpModal(point: MeteringPoint) {
        setEditingMpId(point.id)
        setMpForm({
            zev: point.zev,
            meter_id: point.meter_id,
            meter_type: point.meter_type,
            is_active: point.is_active,
            location_description: point.location_description ?? '',
        })
        setShowMpModal(true)
    }

    function closeMpModal() {
        setShowMpModal(false)
        setEditingMpId(null)
        setMpForm(defaultMeteringPointForm())
    }

    function submitMpForm(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        const zevForSubmit = canManageMeteringPoints ? selectedZevId : mpForm.zev
        if (!zevForSubmit) {
            pushToast(t('pages.meteringPoints.messages.selectZev'), 'error')
            return
        }
        const payload: MeteringPointInput = {
            ...mpForm,
            zev: zevForSubmit,
        }
        saveMpMutation.mutate({ id: editingMpId ?? undefined, payload })
    }

    function openCreateAssignModal(meteringPointId: string) {
        setSelectedMpId(meteringPointId)
        setEditingAssignId(null)
        const existingAssignments = assignmentsByMeteringPoint.get(meteringPointId) ?? []
        const { suggestedValidFrom, hasOpenEndedAssignment } = getNextAssignmentGuidance(existingAssignments, todayIso)
        setAssignForm({ ...defaultAssignmentForm(meteringPointId), valid_from: suggestedValidFrom })
        setAssignHasOpenEndedWarning(hasOpenEndedAssignment)
        setShowAssignModal(true)
    }

    function openEditAssignModal(assignment: MeteringPointAssignment) {
        setSelectedMpId(assignment.metering_point)
        setEditingAssignId(assignment.id)
        setAssignForm({
            metering_point: assignment.metering_point,
            participant: assignment.participant,
            valid_from: assignment.valid_from,
            valid_to: assignment.valid_to ?? null,
            allocation_mode: assignment.allocation_mode,
        })
        setAssignHasOpenEndedWarning(false)
        setShowAssignModal(true)
    }

    function closeAssignModal() {
        setShowAssignModal(false)
        setEditingAssignId(null)
        setSelectedMpId(null)
        setAssignForm(defaultAssignmentForm())
        setAssignHasOpenEndedWarning(false)
    }

    function submitAssignForm(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!assignForm.participant) {
            pushToast(t('pages.meteringPoints.messages.selectParticipant'), 'error')
            return
        }
        if (!assignForm.valid_from) {
            pushToast(t('pages.meteringPoints.messages.missingValidFrom'), 'error')
            return
        }
        const payload: MeteringPointAssignmentInput = {
            ...assignForm,
            valid_to: assignForm.valid_to || null,
        }
        saveAssignMutation.mutate({ id: editingAssignId ?? undefined, payload })
    }

    function openDeleteDataModal(point: MeteringPoint) {
        setDeleteDataTarget(point)
        setDeleteDataMode('all')
        setDeleteDataFrom('')
        setDeleteDataTo('')
        setShowDeleteDataModal(true)
    }

    function closeDeleteDataModal() {
        setShowDeleteDataModal(false)
        setDeleteDataTarget(null)
        setDeleteDataMode('all')
        setDeleteDataFrom('')
        setDeleteDataTo('')
    }

    function submitDeleteData() {
        if (!deleteDataTarget) return

        let payload: { delete_all: boolean; date_from?: string; date_to?: string }
        let confirmMessage: string

        if (deleteDataMode === 'range') {
            if (!deleteDataFrom || !deleteDataTo) {
                pushToast(t('pages.meteringPoints.deleteData.validationDatesRequired'), 'error')
                return
            }
            if (deleteDataTo < deleteDataFrom) {
                pushToast(t('pages.meteringPoints.deleteData.validationDateOrder'), 'error')
                return
            }
            payload = {
                delete_all: false,
                date_from: deleteDataFrom,
                date_to: deleteDataTo,
            }
            confirmMessage = t('pages.meteringPoints.deleteData.confirmMessageRange', {
                meterId: deleteDataTarget.meter_id,
                from: formatShortDate(deleteDataFrom, settings),
                to: formatShortDate(deleteDataTo, settings),
            })
        } else {
            payload = { delete_all: true }
            confirmMessage = t('pages.meteringPoints.deleteData.confirmMessageAll', {
                meterId: deleteDataTarget.meter_id,
            })
        }

        confirm({
            title: t('pages.meteringPoints.deleteData.confirmTitle'),
            message: confirmMessage,
            confirmText: t('pages.meteringPoints.deleteData.confirm'),
            isDangerous: true,
            onConfirm: async () => {
                await deleteMeteringDataMutation.mutateAsync({
                    meteringPointId: deleteDataTarget.id,
                    payload,
                })
            },
        })
    }

    // ── Computed lookups ───────────────────────────────────────────────────────────

    const participantNameById = useMemo(
        () =>
            new Map(
                (participantsQuery.data ?? []).map((p) => [p.id, `${p.first_name} ${p.last_name}`]),
            ),
        [participantsQuery.data],
    )

    const assignParticipants = useMemo(() => {
        if (!selectedMpId) return participantsQuery.data ?? []
        const mp = meteringPointsQuery.data?.find((m) => m.id === selectedMpId)
        if (!mp) return participantsQuery.data ?? []
        return (participantsQuery.data ?? []).filter((p) => p.zev === mp.zev)
    }, [selectedMpId, meteringPointsQuery.data, participantsQuery.data])

    // ── Data health (#623) ────────────────────────────────────────────────────────

    const qualityByMeteringPoint = useMemo(() => {
        const map = new Map<string, MeteringPointDataQuality>()
        for (const dq of dataQualityQuery.data?.metering_points ?? []) {
            map.set(dq.id, dq)
        }
        return map
    }, [dataQualityQuery.data])

    const meteringPointHealthById = useMemo(() => {
        const map = new Map<string, MeteringPointHealth>()
        for (const point of meteringPointsQuery.data ?? []) {
            map.set(point.id, getMeteringPointHealth(point, qualityByMeteringPoint.get(point.id)))
        }
        return map
    }, [meteringPointsQuery.data, qualityByMeteringPoint])

    // Empty (rather than computed with an empty assignment map, which would
    // read every meter as holder-less) when assignments aren't loaded for
    // this role — see isMeteringPointHolderLess's contract.
    const meteringPointHolderLessById = useMemo(() => {
        const map = new Map<string, boolean>()
        if (!canManageMeteringPoints) return map
        for (const point of meteringPointsQuery.data ?? []) {
            map.set(point.id, isMeteringPointHolderLess(point, assignmentsByMeteringPoint.get(point.id) ?? [], todayIso))
        }
        return map
    }, [canManageMeteringPoints, meteringPointsQuery.data, assignmentsByMeteringPoint, todayIso])

    const needsAttentionByMeteringPoint = useMemo(() => {
        const map = new Map<string, boolean>()
        for (const point of meteringPointsQuery.data ?? []) {
            const health = meteringPointHealthById.get(point.id) ?? 'no_data'
            const holderLess = meteringPointHolderLessById.get(point.id) ?? false
            map.set(point.id, meteringPointNeedsAttention(point, health, holderLess))
        }
        return map
    }, [meteringPointsQuery.data, meteringPointHealthById, meteringPointHolderLessById])

    // Empty for a role with no assignment data loaded, same as
    // meteringPointHolderLessById — the "Assigned"/"Unassigned" chips are
    // hidden for that role in the toolbar, so this never needs to fall back.
    const isAssignedByMeteringPoint = useMemo(() => {
        const map = new Map<string, boolean>()
        for (const point of meteringPointsQuery.data ?? []) {
            map.set(
                point.id,
                (assignmentsByMeteringPoint.get(point.id) ?? []).some((assignment) => isAssignmentCurrent(assignment, todayIso)),
            )
        }
        return map
    }, [meteringPointsQuery.data, assignmentsByMeteringPoint, todayIso])

    // Every participant ever assigned, not just the current holder — a
    // search for a former tenant's name should still find their old meter.
    const participantNamesByMeteringPoint = useMemo(() => {
        const map = new Map<string, string>()
        for (const [meteringPointId, assignments] of assignmentsByMeteringPoint.entries()) {
            const names = assignments
                .map((assignment) => participantNameById.get(assignment.participant))
                .filter((name): name is string => !!name)
                .join(' ')
            map.set(meteringPointId, names)
        }
        return map
    }, [assignmentsByMeteringPoint, participantNameById])

    const { scopedMeteringPoints, meteringPoints } = getScopedAndFilteredMeteringPoints(meteringPointsQuery.data ?? [], {
        selectedZevId,
        canManageMeteringPoints,
        searchTerm,
        statusFilter,
        typeFilter,
        attentionFilter,
        needsAttentionByMeteringPoint,
        assignmentFilter,
        isAssignedByMeteringPoint,
        participantNamesByMeteringPoint,
    })

    const filteredAssignmentsByMeteringPoint = new Map(
        Array.from(assignmentsByMeteringPoint.entries()).filter(([meteringPointId]) =>
            scopedMeteringPoints.some((point) => point.id === meteringPointId),
        ),
    )

    const { activeCount, inactiveCount, assignedCount, needsAttentionCount } = getMeteringPointCounts(
        scopedMeteringPoints,
        filteredAssignmentsByMeteringPoint,
        todayIso,
        needsAttentionByMeteringPoint,
    )
    const hasFilters = !!searchTerm.trim()
        || statusFilter !== 'all'
        || typeFilter !== 'all'
        || attentionFilter !== 'all'
        || assignmentFilter !== 'all'

    return {
        // Queries
        participantsQuery,
        meteringPointsQuery,
        assignmentsQuery,
        dataQualityQuery,
        // Mutations
        saveMpMutation,
        deleteMpMutation,
        saveAssignMutation,
        deleteAssignMutation,
        deleteMeteringDataMutation,
        // Modal form state
        mpForm,
        setMpForm,
        editingMpId,
        showMpModal,
        assignForm,
        setAssignForm,
        editingAssignId,
        showAssignModal,
        selectedMpId,
        assignHasOpenEndedWarning,
        showDeleteDataModal,
        deleteDataTarget,
        deleteDataMode,
        setDeleteDataMode,
        deleteDataFrom,
        setDeleteDataFrom,
        deleteDataTo,
        setDeleteDataTo,
        searchTerm,
        setSearchTerm,
        statusFilter,
        setStatusFilter,
        typeFilter,
        setTypeFilter,
        attentionFilter,
        setAttentionFilter,
        assignmentFilter,
        setAssignmentFilter,
        clearFilters,
        // Form handlers
        openCreateMpModal,
        openEditMpModal,
        closeMpModal,
        submitMpForm,
        openCreateAssignModal,
        openEditAssignModal,
        closeAssignModal,
        submitAssignForm,
        openDeleteDataModal,
        closeDeleteDataModal,
        submitDeleteData,
        // Computed
        participantNameById,
        assignmentsByMeteringPoint,
        assignParticipants,
        scopedMeteringPoints,
        filteredAssignmentsByMeteringPoint,
        meteringPoints,
        activeCount,
        inactiveCount,
        assignedCount,
        needsAttentionCount,
        hasFilters,
        // Data health (#623)
        meteringPointHealthById,
        meteringPointHolderLessById,
        needsAttentionByMeteringPoint,
        // Dialog
        dialog,
        confirm,
        dialogLoading,
        handleConfirm,
        handleCancel,
    }
}
