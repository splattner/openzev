import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import dayjs from 'dayjs'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faChartLine,
    faDatabase,
    faEllipsis,
    faPen,
    faPlus,
    faTrash,
    faUserPlus,
} from '@fortawesome/free-solid-svg-icons'
import { DatePickerInput } from '@mantine/dates'
import { FormControlLabel, Switch } from '@mui/material'
import { DatePicker } from '@mui/x-date-pickers/DatePicker'
import { AdapterDayjs } from '@mui/x-date-pickers/AdapterDayjs'
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider'
import { ActionMenu, type ActionMenuItem } from '../components/ActionMenu'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { FormModal } from '../components/FormModal'
import {
    createMeteringPoint,
    createMeteringPointAssignment,
    deleteMeteringPoint,
    deleteMeteringPointReadings,
    deleteMeteringPointAssignment,
    fetchMeteringPointAssignments,
    fetchMeteringPoints,
    fetchParticipants,
    formatApiError,
    updateMeteringPoint,
    updateMeteringPointAssignment,
} from '../lib/api'
import { formatShortDate, toDayJsDateFormat, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { quickRangeToDates } from '../lib/dateRangePresets'
import { useManagedZev } from '../lib/managedZev'
import { useTranslation } from 'react-i18next'
import { useToast } from '../lib/toast'
import type { MeteringPoint, MeteringPointAssignment, MeteringPointAssignmentInput, MeteringPointInput } from '../types/api'

// ── Default form values ────────────────────────────────────────────────────────

const defaultMpForm = (): MeteringPointInput => ({
    zev: '',
    meter_id: '',
    meter_type: 'consumption',
    is_active: true,
    location_description: '',
})

const defaultAssignmentForm = (meteringPointId = ''): MeteringPointAssignmentInput => ({
    metering_point: meteringPointId,
    participant: '',
    valid_from: new Date().toISOString().slice(0, 10),
    valid_to: null,
})

type MeteringPointStatusFilter = 'all' | 'active' | 'inactive'
type MeteringPointTypeFilter = 'all' | MeteringPoint['meter_type']
type AssignmentState = 'current' | 'upcoming' | 'ended'

function getAssignmentState(assignment: MeteringPointAssignment, todayIso: string): AssignmentState {
    if (assignment.valid_from > todayIso) return 'upcoming'
    if (assignment.valid_to && assignment.valid_to < todayIso) return 'ended'
    return 'current'
}

function assignmentStateBadgeClass(state: AssignmentState): string {
    if (state === 'current') return 'badge badge-success'
    if (state === 'upcoming') return 'badge badge-info'
    return 'badge badge-neutral'
}

function assignmentStateSortOrder(state: AssignmentState): number {
    if (state === 'current') return 0
    if (state === 'upcoming') return 1
    return 2
}

// ── Component ─────────────────────────────────────────────────────────────────

export function MeteringPointsPage() {
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { selectedZevId } = useManagedZev()
    const { t } = useTranslation()
    const canManageMeteringPoints = user?.role === 'admin' || user?.role === 'zev_owner'

    // ── Queries ──────────────────────────────────────────────────────────────────
    const participantsQuery = useQuery({ queryKey: ['participants'], queryFn: fetchParticipants, enabled: canManageMeteringPoints })
    const meteringPointsQuery = useQuery({ queryKey: ['metering-points'], queryFn: fetchMeteringPoints })
    const assignmentsQuery = useQuery({
        queryKey: ['metering-point-assignments'],
        queryFn: () => fetchMeteringPointAssignments(),
        enabled: canManageMeteringPoints,
    })

    // ── Metering-point modal state ───────────────────────────────────────────────
    const [mpForm, setMpForm] = useState<MeteringPointInput>(defaultMpForm())
    const [editingMpId, setEditingMpId] = useState<string | null>(null)
    const [showMpModal, setShowMpModal] = useState(false)

    // ── Assignment modal state ───────────────────────────────────────────────────
    const [assignForm, setAssignForm] = useState<MeteringPointAssignmentInput>(defaultAssignmentForm())
    const [editingAssignId, setEditingAssignId] = useState<string | null>(null)
    const [showAssignModal, setShowAssignModal] = useState(false)
    const [selectedMpId, setSelectedMpId] = useState<string | null>(null)
    const [showDeleteDataModal, setShowDeleteDataModal] = useState(false)
    const [deleteDataTarget, setDeleteDataTarget] = useState<MeteringPoint | null>(null)
    const [deleteDataMode, setDeleteDataMode] = useState<'all' | 'range'>('all')
    const [deleteDataFrom, setDeleteDataFrom] = useState('')
    const [deleteDataTo, setDeleteDataTo] = useState('')
    const [searchTerm, setSearchTerm] = useState('')
    const [statusFilter, setStatusFilter] = useState<MeteringPointStatusFilter>('all')
    const [typeFilter, setTypeFilter] = useState<MeteringPointTypeFilter>('all')

    // ── Lookups ──────────────────────────────────────────────────────────────────
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

    // ── Metering-point mutations ──────────────────────────────────────────────────
    const saveMpMutation = useMutation({
        mutationFn: ({ id, payload }: { id?: string; payload: MeteringPointInput }) =>
            id ? updateMeteringPoint(id, payload) : createMeteringPoint(payload),
        onSuccess: (_, variables) => {
            closeMpModal()
            pushToast(
                variables.id ? t('pages.meteringPoints.messages.updated') : t('pages.meteringPoints.messages.created'),
                'success',
            )
            void queryClient.invalidateQueries({ queryKey: ['metering-points'] })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.meteringPoints.messages.saveFailed')), 'error'),
    })

    const deleteMpMutation = useMutation({
        mutationFn: deleteMeteringPoint,
        onSuccess: () => {
            pushToast(t('pages.meteringPoints.messages.deleted'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['metering-points'] })
            void queryClient.invalidateQueries({ queryKey: ['metering-point-assignments'] })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.meteringPoints.messages.deleteFailed')), 'error'),
    })

    // ── Assignment mutations ──────────────────────────────────────────────────────
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
            void queryClient.invalidateQueries({ queryKey: ['metering-point-assignments'] })
            void queryClient.invalidateQueries({ queryKey: ['metering-points'] })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.meteringPoints.messages.assignmentSaveFailed')), 'error'),
    })

    const deleteAssignMutation = useMutation({
        mutationFn: deleteMeteringPointAssignment,
        onSuccess: () => {
            pushToast(t('pages.meteringPoints.messages.assignmentRemoved'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['metering-point-assignments'] })
            void queryClient.invalidateQueries({ queryKey: ['metering-points'] })
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

    // ── Metering-point form handlers ──────────────────────────────────────────────
    function openCreateMpModal() {
        setEditingMpId(null)
        setMpForm((previous) => ({ ...defaultMpForm(), zev: canManageMeteringPoints ? selectedZevId : previous.zev }))
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
        setMpForm(defaultMpForm())
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

    // ── Assignment form handlers ───────────────────────────────────────────────────
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
        })
        setShowAssignModal(true)
    }

    function closeAssignModal() {
        setShowAssignModal(false)
        setEditingAssignId(null)
        setSelectedMpId(null)
        setAssignForm(defaultAssignmentForm())
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

    // ── Participants that belong to the selected metering point's ZEV ─────────────
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

    // ── Loading / error ───────────────────────────────────────────────────────────
    if (meteringPointsQuery.isLoading) {
        return <div className="card">{t('pages.meteringPoints.loading')}</div>
    }
    if (meteringPointsQuery.isError) {
        return <div className="card error-banner">{t('pages.meteringPoints.loadFailed')}</div>
    }

    return (
        <div className="page-stack">
            <header>
                <h2>{t('pages.meteringPoints.title')}</h2>
                <p className="muted">
                    {canManageMeteringPoints
                        ? t('pages.meteringPoints.adminDescription')
                        : t('pages.meteringPoints.participantDescription')}
                </p>
            </header>

            <section className="card metering-toolbar">
                <div className="metering-toolbar-header">
                    <div className="metering-summary" aria-label={t('pages.meteringPoints.summaryLabel')}>
                        <span className="metering-summary-stat">
                            <span className="metering-summary-label">{t('pages.meteringPoints.summary.total')}</span>
                            <span className="metering-summary-value">{scopedMeteringPoints.length}</span>
                        </span>
                        <span className="metering-summary-stat">
                            <span className="metering-summary-label">{t('pages.meteringPoints.summary.active')}</span>
                            <span className="metering-summary-value">{activeCount}</span>
                        </span>
                        <span className="metering-summary-stat">
                            <span className="metering-summary-label">{t('pages.meteringPoints.summary.inactive')}</span>
                            <span className="metering-summary-value">{inactiveCount}</span>
                        </span>
                        <span className="metering-summary-stat">
                            <span className="metering-summary-label">{t('pages.meteringPoints.summary.assigned')}</span>
                            <span className="metering-summary-value">{assignedCount}</span>
                        </span>
                        <span className="metering-summary-stat">
                            <span className="metering-summary-label">{t('pages.meteringPoints.summary.unassigned')}</span>
                            <span className="metering-summary-value">{scopedMeteringPoints.length - assignedCount}</span>
                        </span>
                    </div>

                    {canManageMeteringPoints && (
                        <button className="button button-primary" type="button" onClick={openCreateMpModal}>
                            <FontAwesomeIcon icon={faPlus} fixedWidth />
                            {t('pages.meteringPoints.newMeteringPoint')}
                        </button>
                    )}
                </div>

                <div className="metering-filter-grid">
                    <label>
                        <span>{t('pages.meteringPoints.filters.search')}</span>
                        <input
                            value={searchTerm}
                            onChange={(event) => setSearchTerm(event.target.value)}
                            placeholder={t('pages.meteringPoints.filters.searchPlaceholder')}
                        />
                    </label>
                    <label>
                        <span>{t('pages.meteringPoints.filters.status')}</span>
                        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as MeteringPointStatusFilter)}>
                            <option value="all">{t('pages.meteringPoints.filters.allStatuses')}</option>
                            <option value="active">{t('pages.meteringPoints.active')}</option>
                            <option value="inactive">{t('pages.meteringPoints.inactive')}</option>
                        </select>
                    </label>
                    <label>
                        <span>{t('pages.meteringPoints.filters.type')}</span>
                        <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as MeteringPointTypeFilter)}>
                            <option value="all">{t('pages.meteringPoints.filters.allTypes')}</option>
                            <option value="consumption">{t('pages.meteringPoints.meterTypes.consumption')}</option>
                            <option value="production">{t('pages.meteringPoints.meterTypes.production')}</option>
                            <option value="bidirectional">{t('pages.meteringPoints.meterTypes.bidirectional')}</option>
                        </select>
                    </label>
                </div>
            </section>

            {/* ── Metering Point Create/Edit Modal ──────────────────────────────────── */}
            <FormModal
                isOpen={showMpModal}
                title={editingMpId ? t('pages.meteringPoints.editTitle') : t('pages.meteringPoints.createTitle')}
                onClose={closeMpModal}
            >
                <form onSubmit={submitMpForm} className="form-grid">
                    <label>
                        <span>{t('pages.meteringPoints.form.meterId')}</span>
                        <input
                            value={mpForm.meter_id}
                            onChange={(e) => setMpForm((prev) => ({ ...prev, meter_id: e.target.value }))}
                            required
                        />
                    </label>

                    <label>
                        <span>{t('pages.meteringPoints.form.meterType')}</span>
                        <select
                            value={mpForm.meter_type}
                            onChange={(e) =>
                                setMpForm((prev) => ({ ...prev, meter_type: e.target.value as MeteringPointInput['meter_type'] }))
                            }
                        >
                            <option value="consumption">{t('pages.meteringPoints.meterTypes.consumption')}</option>
                            <option value="production">{t('pages.meteringPoints.meterTypes.production')}</option>
                            <option value="bidirectional">{t('pages.meteringPoints.meterTypes.bidirectional')}</option>
                        </select>
                    </label>

                    <div style={{ gridColumn: '1 / -1' }}>
                        <FormControlLabel
                            control={
                                <Switch
                                    checked={mpForm.is_active}
                                    onChange={(_event, checked) => setMpForm((prev) => ({ ...prev, is_active: checked }))}
                                />
                            }
                            label={t('pages.meteringPoints.form.active')}
                        />
                    </div>

                    <label style={{ gridColumn: '1 / -1' }}>
                        <span>{t('pages.meteringPoints.form.location')}</span>
                        <input
                            value={mpForm.location_description ?? ''}
                            onChange={(e) => setMpForm((prev) => ({ ...prev, location_description: e.target.value }))}
                        />
                    </label>

                    <div
                        style={{
                            gridColumn: '1 / -1',
                            display: 'flex',
                            gap: '1rem',
                            justifyContent: 'flex-end',
                            marginTop: '1rem',
                        }}
                    >
                        <button className="button button-secondary" type="button" onClick={closeMpModal}>
                            {t('common.cancel')}
                        </button>
                        <button className="button button-primary" type="submit" disabled={saveMpMutation.isPending}>
                            {editingMpId ? t('pages.meteringPoints.saveChanges') : t('pages.meteringPoints.createButton')}
                        </button>
                    </div>
                </form>
            </FormModal>

            {/* ── Assignment Create/Edit Modal ──────────────────────────────────────── */}
            <FormModal
                isOpen={showAssignModal}
                title={editingAssignId ? t('pages.meteringPoints.editAssignTitle') : t('pages.meteringPoints.assignTitle')}
                onClose={closeAssignModal}
            >
                <form onSubmit={submitAssignForm} className="form-grid">
                    <label style={{ gridColumn: '1 / -1' }}>
                        <span>{t('pages.meteringPoints.assignForm.participant')}</span>
                        <select
                            value={assignForm.participant}
                            onChange={(e) => setAssignForm((prev) => ({ ...prev, participant: e.target.value }))}
                            required
                        >
                            <option value="">{t('pages.meteringPoints.assignForm.selectParticipant')}</option>
                            {assignParticipants.map((p) => (
                                <option key={p.id} value={p.id}>
                                    {p.first_name} {p.last_name}
                                </option>
                            ))}
                        </select>
                    </label>

                    <label>
                        <span>{t('pages.meteringPoints.assignForm.validFrom')}</span>
                        <LocalizationProvider dateAdapter={AdapterDayjs}>
                            <DatePicker
                                format={toDayJsDateFormat(settings.date_format_short)}
                                value={assignForm.valid_from ? dayjs(assignForm.valid_from) : null}
                                onChange={(v) => setAssignForm((prev) => ({ ...prev, valid_from: v ? v.format('YYYY-MM-DD') : '' }))}
                                slotProps={{ textField: { required: true, size: 'small' } }}
                            />
                        </LocalizationProvider>
                    </label>
                    <label>
                        <span>{t('pages.meteringPoints.assignForm.validTo')}</span>
                        <LocalizationProvider dateAdapter={AdapterDayjs}>
                            <DatePicker
                                format={toDayJsDateFormat(settings.date_format_short)}
                                value={assignForm.valid_to ? dayjs(assignForm.valid_to) : null}
                                onChange={(v) => setAssignForm((prev) => ({ ...prev, valid_to: v ? v.format('YYYY-MM-DD') : null }))}
                                slotProps={{ textField: { size: 'small' } }}
                            />
                        </LocalizationProvider>
                    </label>

                    <p className="muted" style={{ gridColumn: '1 / -1', margin: 0, fontSize: '0.82rem' }}>
                        {t('pages.meteringPoints.assignForm.validToHint')}
                    </p>

                    <div
                        style={{
                            gridColumn: '1 / -1',
                            display: 'flex',
                            gap: '1rem',
                            justifyContent: 'flex-end',
                            marginTop: '0.5rem',
                        }}
                    >
                        <button className="button button-secondary" type="button" onClick={closeAssignModal}>
                            {t('common.cancel')}
                        </button>
                        <button className="button button-primary" type="submit" disabled={saveAssignMutation.isPending}>
                            {editingAssignId ? t('pages.meteringPoints.saveAssignment') : t('pages.meteringPoints.assignParticipant')}
                        </button>
                    </div>
                </form>
            </FormModal>

            {/* ── Metering Points List ──────────────────────────────────────────────── */}
            <div className="table-card">
                {scopedMeteringPoints.length === 0 ? (
                    <section className="card" style={{ margin: '1rem', display: 'grid', gap: '0.75rem' }}>
                        <h3 style={{ margin: 0 }}>{t('pages.meteringPoints.emptyState.title')}</h3>
                        <p className="muted" style={{ margin: 0 }}>{t('pages.meteringPoints.emptyState.description')}</p>
                        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                            {canManageMeteringPoints && (
                                <button className="button button-primary" type="button" onClick={openCreateMpModal}>
                                    <FontAwesomeIcon icon={faPlus} fixedWidth />
                                    {t('pages.meteringPoints.emptyState.createAction')}
                                </button>
                            )}
                            {canManageMeteringPoints && (
                                <Link className="button button-secondary" to="/participants" style={{ textDecoration: 'none' }}>
                                    {t('pages.meteringPoints.emptyState.participantsAction')}
                                </Link>
                            )}
                        </div>
                    </section>
                ) : meteringPoints.length === 0 ? (
                    <section className="card" style={{ margin: '1rem', display: 'grid', gap: '0.75rem' }}>
                        <h3 style={{ margin: 0 }}>{t('pages.meteringPoints.noResults.title')}</h3>
                        <p className="muted" style={{ margin: 0 }}>{t('pages.meteringPoints.noResults.description')}</p>
                        {hasFilters && (
                            <div>
                                <button
                                    className="button button-secondary"
                                    type="button"
                                    onClick={() => {
                                        setSearchTerm('')
                                        setStatusFilter('all')
                                        setTypeFilter('all')
                                    }}
                                >
                                    {t('pages.meteringPoints.filters.clear')}
                                </button>
                            </div>
                        )}
                    </section>
                ) : (
                    <div className="metering-point-list">
                        {meteringPoints.map((point) => {
                            const assignments = filteredAssignmentsByMeteringPoint.get(point.id) ?? []
                            const todayIso = new Date().toISOString().slice(0, 10)
                            const sortedAssignments = [...assignments].sort((left, right) => {
                                const leftState = getAssignmentState(left, todayIso)
                                const rightState = getAssignmentState(right, todayIso)
                                const stateDelta = assignmentStateSortOrder(leftState) - assignmentStateSortOrder(rightState)

                                if (stateDelta !== 0) return stateDelta
                                return right.valid_from.localeCompare(left.valid_from)
                            })
                            const pointMenuItems: ActionMenuItem[] = []

                            if (canManageMeteringPoints) {
                                pointMenuItems.push({
                                    key: 'edit',
                                    label: t('common.edit'),
                                    icon: <FontAwesomeIcon icon={faPen} fixedWidth />,
                                    onClick: () => openEditMpModal(point),
                                })
                                if (user?.role === 'admin') {
                                    pointMenuItems.push({
                                        key: 'delete-data',
                                        label: t('pages.meteringPoints.deleteData.button'),
                                        icon: <FontAwesomeIcon icon={faDatabase} fixedWidth />,
                                        onClick: () => openDeleteDataModal(point),
                                    })
                                }
                                pointMenuItems.push({
                                    key: 'delete',
                                    label: t('common.delete'),
                                    icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
                                    disabled: deleteMpMutation.isPending || dialogLoading,
                                    danger: true,
                                    onClick: () => confirm({
                                        title: t('pages.meteringPoints.deleteTitle'),
                                        message: t('pages.meteringPoints.deleteMessage', { meterId: point.meter_id }),
                                        confirmText: t('pages.meteringPoints.deleteConfirm'),
                                        isDangerous: true,
                                        onConfirm: () => deleteMpMutation.mutate(point.id),
                                    }),
                                })
                            }

                            return (
                                <article key={point.id} className="metering-point-card">
                                    <div className="metering-point-card-header">
                                        <div className="metering-point-title">
                                            <div className="metering-point-badges">
                                                <span className={point.is_active ? 'badge badge-success' : 'badge badge-danger'}>
                                                    {point.is_active ? t('pages.meteringPoints.active') : t('pages.meteringPoints.inactive')}
                                                </span>
                                                <span className="badge badge-neutral">{t(`pages.meteringPoints.meterTypes.${point.meter_type}`)}</span>
                                            </div>
                                            <strong>{point.meter_id}</strong>
                                        </div>

                                        <div className="metering-point-actions">
                                            {canManageMeteringPoints && assignments.length === 0 && (
                                                <button
                                                    className="button button-primary button-compact"
                                                    type="button"
                                                    onClick={() => openCreateAssignModal(point.id)}
                                                >
                                                    <FontAwesomeIcon icon={faUserPlus} fixedWidth />
                                                    {t('pages.meteringPoints.assign')}
                                                </button>
                                            )}
                                            <Link
                                                className="button button-secondary button-compact"
                                                style={{ textDecoration: 'none' }}
                                                to={`/metering-data?metering_point=${point.id}`}
                                            >
                                                <FontAwesomeIcon icon={faChartLine} fixedWidth />
                                                {t('pages.meteringPoints.chart')}
                                            </Link>
                                            {canManageMeteringPoints && (
                                                <ActionMenu
                                                    label={t('pages.meteringPoints.moreActions')}
                                                    icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                                                    items={pointMenuItems}
                                                />
                                            )}
                                        </div>
                                    </div>

                                    {canManageMeteringPoints && (
                                        <div className="metering-point-body">
                                            {sortedAssignments.length > 0 ? (
                                                <div className="metering-assignment-list">
                                                    {sortedAssignments.map((assignment) => {
                                                        const assignmentState = getAssignmentState(assignment, todayIso)
                                                        return (
                                                            <div key={assignment.id} className="metering-assignment-row">
                                                                <div className="metering-assignment-main">
                                                                    <div className="metering-assignment-line">
                                                                        <strong>{participantNameById.get(assignment.participant) ?? assignment.participant}</strong>
                                                                        <span className={assignmentStateBadgeClass(assignmentState)}>
                                                                            {t(`pages.meteringPoints.assignmentState.${assignmentState}`)}
                                                                        </span>
                                                                    </div>
                                                                    <div className="muted">
                                                                        {formatShortDate(assignment.valid_from, settings)} - {assignment.valid_to ? formatShortDate(assignment.valid_to, settings) : t('pages.meteringPoints.openEnded')}
                                                                    </div>
                                                                </div>

                                                                <div className="metering-assignment-actions">
                                                                    <button
                                                                        className="button button-secondary button-compact"
                                                                        type="button"
                                                                        onClick={() => openEditAssignModal(assignment)}
                                                                    >
                                                                        <FontAwesomeIcon icon={faPen} fixedWidth />
                                                                        {t('common.edit')}
                                                                    </button>
                                                                    <button
                                                                        className="button button-danger button-compact"
                                                                        type="button"
                                                                        disabled={deleteAssignMutation.isPending || dialogLoading}
                                                                        onClick={() => confirm({
                                                                            title: t('pages.meteringPoints.removeAssignTitle'),
                                                                            message: t('pages.meteringPoints.removeAssignMessage', { name: participantNameById.get(assignment.participant) ?? assignment.participant }),
                                                                            confirmText: t('pages.meteringPoints.removeAssignConfirm'),
                                                                            isDangerous: true,
                                                                            onConfirm: () => deleteAssignMutation.mutate(assignment.id),
                                                                        })}
                                                                    >
                                                                        <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                                        {t('pages.meteringPoints.removeAssignment')}
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        )
                                                    })}
                                                </div>
                                            ) : (
                                                <p className="muted metering-no-assignments">{t('pages.meteringPoints.noAssignments')}</p>
                                            )}
                                        </div>
                                    )}
                                </article>
                            )
                        })}
                    </div>
                )}
            </div>

            <FormModal
                isOpen={showDeleteDataModal}
                title={t('pages.meteringPoints.deleteData.title')}
                onClose={closeDeleteDataModal}
            >
                <div className="page-stack" style={{ gap: '1rem' }}>
                    <p className="muted" style={{ margin: 0, lineHeight: 1.45 }}>
                        {t('pages.meteringPoints.deleteData.description', { meterId: deleteDataTarget?.meter_id ?? '' })}
                    </p>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem' }}>
                        <label
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.6rem',
                                border: deleteDataMode === 'all' ? '2px solid #0f766e' : '1px solid var(--color-border, #d1d5db)',
                                borderRadius: '0.6rem',
                                padding: '0.75rem 0.85rem',
                                background: deleteDataMode === 'all' ? '#ecfeff' : 'white',
                                cursor: 'pointer',
                            }}
                        >
                            <input
                                type="radio"
                                name="deleteDataMode"
                                checked={deleteDataMode === 'all'}
                                onChange={() => setDeleteDataMode('all')}
                            />
                            <span style={{ fontWeight: 600 }}>{t('pages.meteringPoints.deleteData.modeAll')}</span>
                        </label>

                        <label
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.6rem',
                                border: deleteDataMode === 'range' ? '2px solid #0f766e' : '1px solid var(--color-border, #d1d5db)',
                                borderRadius: '0.6rem',
                                padding: '0.75rem 0.85rem',
                                background: deleteDataMode === 'range' ? '#ecfeff' : 'white',
                                cursor: 'pointer',
                            }}
                        >
                            <input
                                type="radio"
                                name="deleteDataMode"
                                checked={deleteDataMode === 'range'}
                                onChange={() => setDeleteDataMode('range')}
                            />
                            <span style={{ fontWeight: 600 }}>{t('pages.meteringPoints.deleteData.modeRange')}</span>
                        </label>
                    </div>

                    {deleteDataMode === 'range' && (
                        <label style={{ display: 'grid', gap: '0.4rem' }}>
                            <span style={{ fontWeight: 600 }}>{t('pages.meteringPoints.deleteData.rangeLabel')}</span>
                            <DatePickerInput
                                type="range"
                                value={[deleteDataFrom || null, deleteDataTo || null]}
                                onChange={([nextFrom, nextTo]) => {
                                    setDeleteDataFrom(nextFrom ?? '')
                                    setDeleteDataTo(nextTo ?? '')
                                }}
                                presets={[
                                    {
                                        value: (() => {
                                            const range = quickRangeToDates('this_month')
                                            return [range.from, range.to] as [string, string]
                                        })(),
                                        label: t('common.periodSelector.thisMonth'),
                                    },
                                    {
                                        value: (() => {
                                            const range = quickRangeToDates('last_month')
                                            return [range.from, range.to] as [string, string]
                                        })(),
                                        label: t('common.periodSelector.lastMonth'),
                                    },
                                    {
                                        value: (() => {
                                            const range = quickRangeToDates('this_quarter')
                                            return [range.from, range.to] as [string, string]
                                        })(),
                                        label: t('common.periodSelector.thisQuarter'),
                                    },
                                    {
                                        value: (() => {
                                            const range = quickRangeToDates('last_quarter')
                                            return [range.from, range.to] as [string, string]
                                        })(),
                                        label: t('common.periodSelector.lastQuarter'),
                                    },
                                    {
                                        value: (() => {
                                            const range = quickRangeToDates('this_year')
                                            return [range.from, range.to] as [string, string]
                                        })(),
                                        label: t('common.periodSelector.thisYear'),
                                    },
                                    {
                                        value: (() => {
                                            const range = quickRangeToDates('last_year')
                                            return [range.from, range.to] as [string, string]
                                        })(),
                                        label: t('common.periodSelector.lastYear'),
                                    },
                                ]}
                                valueFormat={toDayJsDateFormat(settings.date_format_short)}
                                clearable={false}
                                popoverProps={{ withinPortal: true, zIndex: 1400 }}
                            />
                        </label>
                    )}

                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '0.25rem' }}>
                        <button className="button button-secondary" type="button" onClick={closeDeleteDataModal}>
                            {t('common.cancel')}
                        </button>
                        <button
                            className="button button-danger"
                            type="button"
                            onClick={submitDeleteData}
                            disabled={deleteMeteringDataMutation.isPending}
                        >
                            {t('pages.meteringPoints.deleteData.confirm')}
                        </button>
                    </div>
                </div>
            </FormModal>

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
        </div>
    )
}
