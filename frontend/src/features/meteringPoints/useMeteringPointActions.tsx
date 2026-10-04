import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { useConfirmDialog } from '../../components/ConfirmDialog'
import {
    createBuilding,
    createMeteringPoint,
    createMeteringPointAssignment,
    deleteBuilding,
    deleteMeteringPoint,
    deleteMeteringPointReadings,
    deleteMeteringPointAssignment,
    fetchBuildings,
    fetchMeteringPointAssignments,
    fetchMeteringPoints,
    fetchPartyRoles,
    fetchParticipants,
    updateBuilding,
    updateMeteringPoint,
    updateMeteringPointAssignment,
} from '../../lib/api/zev'
import { formatApiError } from '../../lib/api/errors'
import { fetchMeteringDataQualityStatus } from '../../lib/api/metering'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { todayBusinessIso } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import { useAuth } from '../../lib/auth'
import { useWriteScope } from '../../lib/useWriteScope'
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
    readMeteringPointBuildingFilter,
    readMeteringPointAttentionFilter,
    readMeteringPointStatusFilter,
    readMeteringPointTypeFilter,
    type MeteringPointAssignmentFilter,
    type MeteringPointBuildingFilter,
    type MeteringPointAttentionFilter,
    type MeteringPointHealth,
    type MeteringPointStatusFilter,
    type MeteringPointTypeFilter,
} from './useMeteringPointForms'
import type {
    Building,
    BuildingInput,
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
        isManagedScope,
        searchTerm,
        statusFilter,
        typeFilter,
        attentionFilter = 'all',
        needsAttentionByMeteringPoint,
        assignmentFilter = 'all',
        buildingFilter = 'all',
        isAssignedByMeteringPoint,
        participantNamesByMeteringPoint,
    }: {
        selectedZevId: string | null
        isManagedScope: boolean
        searchTerm: string
        statusFilter: MeteringPointStatusFilter
        typeFilter: MeteringPointTypeFilter
        attentionFilter?: MeteringPointAttentionFilter
        /** Only consulted when `attentionFilter` is `'attention'`; a missing entry does not match. */
        needsAttentionByMeteringPoint?: Map<string, boolean>
        assignmentFilter?: MeteringPointAssignmentFilter
        /** `'all'`, or a building id (#890). */
        buildingFilter?: MeteringPointBuildingFilter
        /** Only consulted when `assignmentFilter` isn't `'all'`; a missing entry counts as unassigned. */
        isAssignedByMeteringPoint?: Map<string, boolean>
        /** Space-joined names of every participant ever assigned to the meter, so search can match "which meter is Anna's?". */
        participantNamesByMeteringPoint?: Map<string, string>
    },
) {
    const scopedMeteringPoints = points.filter(
        (point) => !isManagedScope || point.zev === selectedZevId,
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
            || (point.building_name ?? '').toLowerCase().includes(normalizedSearch)
            || (participantNamesByMeteringPoint?.get(point.id) ?? '').toLowerCase().includes(normalizedSearch)
        const matchesBuilding = buildingFilter === 'all' || point.building === buildingFilter
        const matchesAttention = attentionFilter === 'all'
            || !!needsAttentionByMeteringPoint?.get(point.id)
        const isAssigned = !!isAssignedByMeteringPoint?.get(point.id)
        const matchesAssignment = assignmentFilter === 'all'
            || (assignmentFilter === 'assigned' && isAssigned)
            || (assignmentFilter === 'unassigned' && !isAssigned)

        return matchesStatus && matchesType && matchesSearch && matchesAttention && matchesAssignment && matchesBuilding
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
    isManagedScope,
    canWrite,
    canDeleteData,
}: {
    selectedZevId: string | null
    isManagedScope: boolean
    canWrite: boolean
    canDeleteData: boolean
}) {
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { settings } = useAppSettings()
    const { t } = useTranslation()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const { user } = useAuth()
    const { scope, isCurrent, assertWritable } = useWriteScope({ selectedZevId, canWrite, accountId: user?.id }, t('common.error'))

    function ownsCurrentSession(submittedScope: { selectedZevId: string | null }) {
        // AuthProvider clears the mutation cache on account/session changes.
        // Community switches and ordinary navigation leave this operation there.
        return queryClient.getMutationCache().getAll().some(mutation => mutation.state.context === submittedScope)
    }

    function requireWriteAccess(submittingScope: typeof scope) {
        assertWritable(submittingScope, isManagedScope)
    }

    const todayIso = todayBusinessIso()

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

    // Initialize filters from the URL; setters update state and replace query parameters.
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

    const [buildingFilter, setBuildingFilterState] = useState<MeteringPointBuildingFilter>(
        () => readMeteringPointBuildingFilter(searchParams.get(FILTER.building)),
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

    function setBuildingFilter(value: MeteringPointBuildingFilter) {
        setBuildingFilterState(value)
        writeFilterParam(FILTER.building, value, value === 'all')
    }

    function clearFilters() {
        setSearchTermState('')
        setStatusFilterState('all')
        setTypeFilterState('all')
        setAttentionFilterState('all')
        setAssignmentFilterState('all')
        setBuildingFilterState('all')
        setSearchParams((previous) => {
            const next = new URLSearchParams(previous)
            Object.values(FILTER).forEach((key) => next.delete(key))
            return next
        }, { replace: true })
    }

    const participantsQuery = useQuery({
        queryKey: queryKeys.zev.participants(selectedZevId || undefined),
        queryFn: fetchParticipants,
        enabled: isManagedScope && !!selectedZevId,
    })
    // The building select and filter only exist for a ZEV with several (#890).
    const buildingsQuery = useQuery({
        queryKey: queryKeys.zev.buildings(selectedZevId || ''),
        queryFn: () => fetchBuildings(selectedZevId || ''),
        enabled: isManagedScope && !!selectedZevId,
    })
    const buildings = buildingsQuery.data ?? []
    // Which landowners own which building (their role row names it).
    const partyRolesQuery = useQuery({
        queryKey: queryKeys.zev.partyRoles(selectedZevId || '', false),
        queryFn: () => fetchPartyRoles(selectedZevId || ''),
        enabled: isManagedScope && !!selectedZevId,
    })
    const landownersOf = (building: Building): string[] => [
        ...new Set(
            (partyRolesQuery.data ?? [])
                .filter((row) => row.role === 'landowner' && row.building === building.id && (row.valid_to === null || row.valid_to >= todayIso))
                .map((row) => row.party_display_name),
        ),
    ]

    // Building modal
    const [editingBuilding, setEditingBuilding] = useState<Building | null>(null)
    const [showBuildingModal, setShowBuildingModal] = useState(false)
    function openCreateBuildingModal() {
        if (!isCurrent(scope) || !canWrite) return
        setEditingBuilding(null)
        setShowBuildingModal(true)
    }
    function openEditBuildingModal(building: Building) {
        if (!isCurrent(scope) || !canWrite) return
        setEditingBuilding(building)
        setShowBuildingModal(true)
    }
    function closeBuildingModal() {
        setShowBuildingModal(false)
        setEditingBuilding(null)
    }
    function afterBuildingChange(zevId: string | null) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.zev.buildings(zevId || '') })
        void queryClient.invalidateQueries({ queryKey: ['zev', 'partyRoles'] })
        void queryClient.invalidateQueries({ queryKey: queryKeys.metering.points(zevId || undefined) })
    }
    const saveBuildingMutation = useMutation({
        mutationFn: ({ id, input, scope: submittingScope }: { id?: string; input: BuildingInput; scope: typeof scope }) => {
            requireWriteAccess(submittingScope)
            return id ? updateBuilding(id, input) : createBuilding({ ...input, zev: submittingScope.selectedZevId || '' })
        },
        onMutate: (variables) => ({ selectedZevId: variables.scope.selectedZevId, scope: variables.scope }),
        onSuccess: (_, _variables, submittedScope) => {
            if (!ownsCurrentSession(submittedScope)) return
            afterBuildingChange(submittedScope.selectedZevId)
            if (!isCurrent(submittedScope.scope)) return
            closeBuildingModal()
            pushToast(t('pages.meteringPoints.buildings.saved'), 'success')
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope) && variables.scope.canWrite) pushToast(formatApiError(error, t('pages.meteringPoints.buildings.saveFailed')), 'error')
        },
    })
    function submitBuilding(input: BuildingInput) {
        saveBuildingMutation.mutate({ id: editingBuilding?.id, input, scope })
    }
    const deleteBuildingMutation = useMutation({
        mutationFn: ({ id, scope: submittingScope }: { id: string; scope: typeof scope }) => {
            requireWriteAccess(submittingScope)
            return deleteBuilding(id)
        },
        onMutate: (variables) => ({ selectedZevId: variables.scope.selectedZevId, scope: variables.scope }),
        onSuccess: (_, _variables, submittedScope) => {
            if (!ownsCurrentSession(submittedScope)) return
            afterBuildingChange(submittedScope.selectedZevId)
            if (!isCurrent(submittedScope.scope)) return
            pushToast(t('pages.meteringPoints.buildings.deleted'), 'success')
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope) && variables.scope.canWrite) pushToast(formatApiError(error, t('pages.meteringPoints.buildings.saveFailed')), 'error')
        },
    })
    function confirmDeleteBuilding(building: Building) {
        const submittingScope = scope
        confirm({
            title: t('pages.meteringPoints.buildings.deleteTitle'),
            message: t('pages.meteringPoints.buildings.deleteMessage', { name: building.name }),
            confirmText: t('common.delete'),
            isDangerous: true,
            onConfirm: () => deleteBuildingMutation.mutateAsync({ id: building.id, scope: submittingScope }).then(() => undefined),
        })
    }
    const meteringPointsQuery = useQuery({
        queryKey: queryKeys.metering.points(selectedZevId || undefined),
        queryFn: () => fetchMeteringPoints(selectedZevId || undefined),
        enabled: !isManagedScope || !!selectedZevId,
    })
    const assignmentsQuery = useQuery({
        queryKey: queryKeys.metering.pointAssignments(),
        queryFn: () => fetchMeteringPointAssignments(),
        enabled: isManagedScope && !!selectedZevId,
    })
    // Not role-gated: the endpoint scopes readings to what the caller may
    // see (a participant's own assigned meters), so the health indicator
    // stays accurate for every role instead of being hidden for some (#623).
    const healthWindow = getMeteringPointHealthWindow(todayIso)
    const dataQualityQuery = useQuery({
        queryKey: queryKeys.metering.qualityStatus(
            healthWindow.from,
            healthWindow.to,
            isManagedScope ? (selectedZevId || undefined) : undefined,
            undefined,
        ),
        queryFn: () =>
            fetchMeteringDataQualityStatus({
                dateFrom: healthWindow.from,
                dateTo: healthWindow.to,
                zevId: isManagedScope ? (selectedZevId || undefined) : undefined,
            }),
        enabled: !isManagedScope || !!selectedZevId,
    })

    const saveMpMutation = useMutation({
        mutationFn: ({ id, payload, scope: submittingScope }: { id?: string; payload: MeteringPointInput; scope: typeof scope }) => {
            requireWriteAccess(submittingScope)
            return id ? updateMeteringPoint(id, payload) : createMeteringPoint(payload)
        },
        onMutate: (variables) => ({ selectedZevId: variables.scope.selectedZevId, scope: variables.scope }),
        onSuccess: (_, variables, submittedScope) => {
            if (!ownsCurrentSession(submittedScope)) return
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.points(submittedScope.selectedZevId || undefined) })
            if (!isCurrent(submittedScope.scope)) return
            closeMpModal()
            pushToast(
                variables.id ? t('pages.meteringPoints.messages.updated') : t('pages.meteringPoints.messages.created'),
                'success',
            )
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope) && variables.scope.canWrite) pushToast(formatApiError(error, t('pages.meteringPoints.messages.saveFailed')), 'error')
        },
    })

    const deleteMpMutation = useMutation({
        mutationFn: ({ id, scope: submittingScope }: { id: string; scope: typeof scope }) => {
            requireWriteAccess(submittingScope)
            return deleteMeteringPoint(id)
        },
        onMutate: (variables) => ({ selectedZevId: variables.scope.selectedZevId, scope: variables.scope }),
        onSuccess: (_, _variables, submittedScope) => {
            if (!ownsCurrentSession(submittedScope)) return
            // Deleting a metering point cascades to its readings and assignment
            // history (MeterReading/MeteringPointAssignment both CASCADE on
            // metering_point), so every reading-derived view is stale too —
            // invalidate the whole metering namespace rather than enumerating keys.
            void queryClient.invalidateQueries({ queryKey: ['metering'] })
            if (!isCurrent(submittedScope.scope)) return
            pushToast(t('pages.meteringPoints.messages.deleted'), 'success')
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope) && variables.scope.canWrite) pushToast(formatApiError(error, t('pages.meteringPoints.messages.deleteFailed')), 'error')
        },
    })

    const saveAssignMutation = useMutation({
        mutationFn: ({ id, payload, scope: submittingScope }: { id?: string; payload: MeteringPointAssignmentInput; scope: typeof scope }) => {
            requireWriteAccess(submittingScope)
            return id ? updateMeteringPointAssignment(id, payload) : createMeteringPointAssignment(payload)
        },
        onMutate: (variables) => ({ selectedZevId: variables.scope.selectedZevId, scope: variables.scope }),
        onSuccess: (_, variables, submittedScope) => {
            if (!ownsCurrentSession(submittedScope)) return
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.pointAssignments() })
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.points(submittedScope.selectedZevId || undefined) })
            // Participants derive has_metering_point_assignment / metering_points
            // from these rows, so their readiness state changes too.
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.participants(submittedScope.selectedZevId || undefined) })
            if (!isCurrent(submittedScope.scope)) return
            closeAssignModal()
            pushToast(
                variables.id
                    ? t('pages.meteringPoints.messages.assignmentUpdated')
                    : t('pages.meteringPoints.messages.assignmentCreated'),
                'success',
            )
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope) && variables.scope.canWrite) pushToast(formatApiError(error, t('pages.meteringPoints.messages.assignmentSaveFailed')), 'error')
        },
    })

    const deleteAssignMutation = useMutation({
        mutationFn: ({ id, scope: submittingScope }: { id: string; scope: typeof scope }) => {
            requireWriteAccess(submittingScope)
            return deleteMeteringPointAssignment(id)
        },
        onMutate: (variables) => ({ selectedZevId: variables.scope.selectedZevId, scope: variables.scope }),
        onSuccess: (_, _variables, submittedScope) => {
            if (!ownsCurrentSession(submittedScope)) return
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.pointAssignments() })
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.points(submittedScope.selectedZevId || undefined) })
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.participants(submittedScope.selectedZevId || undefined) })
            if (!isCurrent(submittedScope.scope)) return
            pushToast(t('pages.meteringPoints.messages.assignmentRemoved'), 'success')
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope) && variables.scope.canWrite) pushToast(formatApiError(error, t('pages.meteringPoints.messages.assignmentRemoveFailed')), 'error')
        },
    })

    const deleteMeteringDataMutation = useMutation({
        mutationFn: ({
            meteringPointId,
            payload,
            scope: submittingScope,
        }: {
            meteringPointId: string
            scope: typeof scope
            payload: { delete_all: boolean; date_from?: string; date_to?: string }
        }) => {
            requireWriteAccess(submittingScope)
            if (!canDeleteData) throw new Error(t('common.error'))
            return deleteMeteringPointReadings(meteringPointId, payload)
        },
        onMutate: (variables) => ({ selectedZevId: variables.scope.selectedZevId, scope: variables.scope }),
        onSuccess: (result, _variables, submittedScope) => {
            if (!ownsCurrentSession(submittedScope)) return
            // Deleted readings affect every reading-derived view (chart, raw
            // data, dashboard summary, data-quality status).
            void queryClient.invalidateQueries({ queryKey: ['metering'] })
            if (!isCurrent(submittedScope.scope)) return
            pushToast(t('pages.meteringPoints.deleteData.success', { count: result.deleted_count }), 'success')
            closeDeleteDataModal()
        },
        onError: (error, variables) => {
            if (isCurrent(variables.scope) && variables.scope.canWrite) pushToast(formatApiError(error, t('pages.meteringPoints.deleteData.failed')), 'error')
        },
    })

    const assignmentsByMeteringPoint = useMemo(() => {
        const map = new Map<string, MeteringPointAssignment[]>()
        for (const a of assignmentsQuery.data ?? []) {
            const list = map.get(a.metering_point) ?? []
            list.push(a)
            map.set(a.metering_point, list)
        }
        return map
    }, [assignmentsQuery.data])

    function openCreateMpModal() {
        if (!isCurrent(scope) || !canWrite) return
        setEditingMpId(null)
        setMpForm((previous) => ({
            ...defaultMeteringPointForm(),
            zev: isManagedScope ? (selectedZevId || '') : previous.zev,
        }))
        setShowMpModal(true)
    }

    /** "Add metering point" from a building's header: that building is preselected. */
    function openCreateMpModalInBuilding(buildingId: string) {
        if (!isCurrent(scope) || !canWrite) return
        setEditingMpId(null)
        setMpForm({ ...defaultMeteringPointForm(), zev: selectedZevId || '', building: buildingId })
        setShowMpModal(true)
    }

    function openEditMpModal(point: MeteringPoint) {
        if (!isCurrent(scope) || !canWrite) return
        setEditingMpId(point.id)
        setMpForm({
            zev: point.zev,
            meter_id: point.meter_id,
            meter_type: point.meter_type,
            is_active: point.is_active,
            location_description: point.location_description ?? '',
            has_behind_meter_generation: point.has_behind_meter_generation,
            building: point.building,
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
        if (!isCurrent(scope) || !canWrite) return
        const zevForSubmit = mpForm.zev
        if (!zevForSubmit || (isManagedScope && zevForSubmit !== selectedZevId)) {
            pushToast(t('pages.meteringPoints.messages.selectZev'), 'error')
            return
        }
        const payload: MeteringPointInput = {
            ...mpForm,
            zev: zevForSubmit,
        }
        saveMpMutation.mutate({ id: editingMpId ?? undefined, payload, scope })
    }

    function openCreateAssignModal(meteringPointId: string) {
        if (!isCurrent(scope) || !canWrite) return
        setSelectedMpId(meteringPointId)
        setEditingAssignId(null)
        const existingAssignments = assignmentsByMeteringPoint.get(meteringPointId) ?? []
        const { suggestedValidFrom, hasOpenEndedAssignment } = getNextAssignmentGuidance(existingAssignments, todayIso)
        setAssignForm({ ...defaultAssignmentForm(meteringPointId), valid_from: suggestedValidFrom })
        setAssignHasOpenEndedWarning(hasOpenEndedAssignment)
        setShowAssignModal(true)
    }

    function openEditAssignModal(assignment: MeteringPointAssignment) {
        if (!isCurrent(scope) || !canWrite) return
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
        if (!isCurrent(scope) || !canWrite) return
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
        saveAssignMutation.mutate({ id: editingAssignId ?? undefined, payload, scope })
    }

    function openDeleteDataModal(point: MeteringPoint) {
        if (!isCurrent(scope) || !canWrite || !canDeleteData) return
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
        if (!isCurrent(scope) || !canWrite || !canDeleteData || !deleteDataTarget) return

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
                try {
                    await deleteMeteringDataMutation.mutateAsync({
                        scope,
                        meteringPointId: deleteDataTarget.id,
                        payload,
                    })
                } catch (error) {
                    if (isCurrent(scope)) throw error
                }
            },
        })
    }

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
        if (!isManagedScope) return map
        for (const point of meteringPointsQuery.data ?? []) {
            map.set(point.id, isMeteringPointHolderLess(point, assignmentsByMeteringPoint.get(point.id) ?? [], todayIso))
        }
        return map
    }, [isManagedScope, meteringPointsQuery.data, assignmentsByMeteringPoint, todayIso])

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
        isManagedScope,
        searchTerm,
        statusFilter,
        typeFilter,
        attentionFilter,
        needsAttentionByMeteringPoint,
        assignmentFilter,
        buildingFilter,
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
        || buildingFilter !== 'all'

    return {
        // Queries
        participantsQuery,
        meteringPointsQuery,
        assignmentsQuery,
        dataQualityQuery,
        // Mutations
        scope,
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
        buildingFilter,
        setBuildingFilter,
        buildings,
        landownersOf,
        editingBuilding,
        showBuildingModal,
        openCreateBuildingModal,
        openEditBuildingModal,
        closeBuildingModal,
        saveBuildingMutation,
        submitBuilding,
        deleteBuildingMutation,
        confirmDeleteBuilding,
        openCreateMpModalInBuilding,
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
