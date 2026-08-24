import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
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
import { queryKeys } from '../../lib/api/queryKeys'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { useToast } from '../../lib/toast'
import {
    defaultAssignmentForm,
    defaultMeteringPointForm,
    type MeteringPointStatusFilter,
    type MeteringPointTypeFilter,
} from './useMeteringPointForms'
import type { MeteringPoint, MeteringPointAssignment, MeteringPointAssignmentInput, MeteringPointInput } from '../../types/api'

export function getScopedAndFilteredMeteringPoints(
    points: MeteringPoint[],
    {
        selectedZevId,
        canManageMeteringPoints,
        searchTerm,
        statusFilter,
        typeFilter,
    }: {
        selectedZevId: string | null
        canManageMeteringPoints: boolean
        searchTerm: string
        statusFilter: MeteringPointStatusFilter
        typeFilter: MeteringPointTypeFilter
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

        return matchesStatus && matchesType && matchesSearch
    })

    return { scopedMeteringPoints, meteringPoints }
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

    // Delete data modal
    const [showDeleteDataModal, setShowDeleteDataModal] = useState(false)
    const [deleteDataTarget, setDeleteDataTarget] = useState<MeteringPoint | null>(null)
    const [deleteDataMode, setDeleteDataMode] = useState<'all' | 'range'>('all')
    const [deleteDataFrom, setDeleteDataFrom] = useState('')
    const [deleteDataTo, setDeleteDataTo] = useState('')

    // Filtering
    const [searchTerm, setSearchTerm] = useState('')
    const [statusFilter, setStatusFilter] = useState<MeteringPointStatusFilter>('all')
    const [typeFilter, setTypeFilter] = useState<MeteringPointTypeFilter>('all')

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
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.points(selectedZevId || undefined) })
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.pointAssignments() })
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
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.meteringPoints.messages.assignmentSaveFailed')), 'error'),
    })

    const deleteAssignMutation = useMutation({
        mutationFn: deleteMeteringPointAssignment,
        onSuccess: () => {
            pushToast(t('pages.meteringPoints.messages.assignmentRemoved'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.pointAssignments() })
            void queryClient.invalidateQueries({ queryKey: queryKeys.metering.points(selectedZevId || undefined) })
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
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.meteringPoints.deleteData.failed')), 'error'),
    })

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
        setAssignForm(defaultAssignmentForm(meteringPointId))
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
        setShowAssignModal(true)
    }

    function closeAssignModal() {
        setShowAssignModal(false)
        setEditingAssignId(null)
        setSelectedMpId(null)
        setAssignForm(defaultAssignmentForm())
    }

    function submitAssignForm(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!assignForm.participant) {
            pushToast(t('pages.meteringPoints.messages.selectParticipant'), 'error')
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
                (participantsQuery.data?.results ?? []).map((p) => [p.id, `${p.first_name} ${p.last_name}`]),
            ),
        [participantsQuery.data],
    )

    const assignmentsByMeteringPoint = useMemo(() => {
        const map = new Map<string, MeteringPointAssignment[]>()
        for (const a of assignmentsQuery.data?.results ?? []) {
            const list = map.get(a.metering_point) ?? []
            list.push(a)
            map.set(a.metering_point, list)
        }
        return map
    }, [assignmentsQuery.data])

    const assignParticipants = useMemo(() => {
        if (!selectedMpId) return participantsQuery.data?.results ?? []
        const mp = meteringPointsQuery.data?.results.find((m) => m.id === selectedMpId)
        if (!mp) return participantsQuery.data?.results ?? []
        return (participantsQuery.data?.results ?? []).filter((p) => p.zev === mp.zev)
    }, [selectedMpId, meteringPointsQuery.data, participantsQuery.data])

    const scopedMeteringPoints = (meteringPointsQuery.data?.results ?? []).filter(
        (point) => !canManageMeteringPoints || !selectedZevId || point.zev === selectedZevId,
    )

    const filteredAssignmentsByMeteringPoint = new Map(
        Array.from(assignmentsByMeteringPoint.entries()).filter(([meteringPointId]) =>
            scopedMeteringPoints.some((point) => point.id === meteringPointId),
        ),
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

        return matchesStatus && matchesType && matchesSearch
    })

    const activeCount = scopedMeteringPoints.filter((point) => point.is_active).length
    const inactiveCount = scopedMeteringPoints.length - activeCount
    const assignedCount = scopedMeteringPoints.filter((point) => (filteredAssignmentsByMeteringPoint.get(point.id) ?? []).length > 0).length
    const hasFilters = !!normalizedSearch || statusFilter !== 'all' || typeFilter !== 'all'

    return {
        // Queries
        participantsQuery,
        meteringPointsQuery,
        assignmentsQuery,
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
        hasFilters,
        // Dialog
        dialog,
        confirm,
        dialogLoading,
        handleConfirm,
        handleCancel,
    }
}
