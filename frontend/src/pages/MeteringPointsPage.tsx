import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import dayjs from 'dayjs'
import { DatePicker } from '@mui/x-date-pickers/DatePicker'
import { AdapterDayjs } from '@mui/x-date-pickers/AdapterDayjs'
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { FormModal } from '../components/FormModal'
import {
    createMeteringPoint,
    createMeteringPointAssignment,
    deleteMeteringPoint,
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
            pushToast(variables.id ? 'Metering point updated.' : 'Metering point created.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['metering-points'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to save metering point.'), 'error'),
    })

    const deleteMpMutation = useMutation({
        mutationFn: deleteMeteringPoint,
        onSuccess: () => {
            pushToast('Metering point deleted.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['metering-points'] })
            void queryClient.invalidateQueries({ queryKey: ['metering-point-assignments'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to delete metering point.'), 'error'),
    })

    // ── Assignment mutations ──────────────────────────────────────────────────────
    const saveAssignMutation = useMutation({
        mutationFn: ({ id, payload }: { id?: string; payload: MeteringPointAssignmentInput }) =>
            id ? updateMeteringPointAssignment(id, payload) : createMeteringPointAssignment(payload),
        onSuccess: (_, variables) => {
            closeAssignModal()
            pushToast(variables.id ? 'Assignment updated.' : 'Assignment created.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['metering-point-assignments'] })
            void queryClient.invalidateQueries({ queryKey: ['metering-points'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to save assignment.'), 'error'),
    })

    const deleteAssignMutation = useMutation({
        mutationFn: deleteMeteringPointAssignment,
        onSuccess: () => {
            pushToast('Assignment removed.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['metering-point-assignments'] })
            void queryClient.invalidateQueries({ queryKey: ['metering-points'] })
        },
        onError: (error) => pushToast(formatApiError(error, 'Failed to remove assignment.'), 'error'),
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
            pushToast('Select a ZEV before saving the metering point.', 'error')
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

    function submitAssignForm(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!assignForm.participant) {
            pushToast('Select a participant.', 'error')
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

    const meteringPoints = (meteringPointsQuery.data?.results ?? []).filter(
        (point) => !canManageMeteringPoints || !selectedZevId || point.zev === selectedZevId,
    )
    const filteredAssignmentsByMeteringPoint = new Map(
        Array.from(assignmentsByMeteringPoint.entries()).filter(([meteringPointId]) =>
            meteringPoints.some((point) => point.id === meteringPointId),
        ),
    )

    // ── Loading / error ───────────────────────────────────────────────────────────
    if (meteringPointsQuery.isLoading) {
        return <div className="card">Loading metering points…</div>
    }
    if (meteringPointsQuery.isError) {
        return <div className="card error-banner">Failed to load metering points.</div>
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

            {canManageMeteringPoints && (
                <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
                    <button className="button button-primary" onClick={openCreateMpModal}>
                        {t('pages.meteringPoints.newMeteringPoint')}
                    </button>
                </div>
            )}

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

                    <label>
                        <span>{t('pages.meteringPoints.form.active')}</span>
                        <select
                            value={String(mpForm.is_active)}
                            onChange={(e) => setMpForm((prev) => ({ ...prev, is_active: e.target.value === 'true' }))}
                        >
                            <option value="true">Yes</option>
                            <option value="false">No</option>
                        </select>
                    </label>

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
                            Cancel
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
                            Cancel
                        </button>
                        <button className="button button-primary" type="submit" disabled={saveAssignMutation.isPending}>
                            {editingAssignId ? t('pages.meteringPoints.saveAssignment') : t('pages.meteringPoints.assignParticipant')}
                        </button>
                    </div>
                </form>
            </FormModal>

            {/* ── Metering Points List ──────────────────────────────────────────────── */}
            <div className="table-card">
                {meteringPoints.length === 0 ? (
                    <section className="card" style={{ margin: '1rem', display: 'grid', gap: '0.75rem' }}>
                        <h3 style={{ margin: 0 }}>{t('pages.meteringPoints.emptyState.title')}</h3>
                        <p className="muted" style={{ margin: 0 }}>{t('pages.meteringPoints.emptyState.description')}</p>
                        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                            {canManageMeteringPoints && (
                                <button className="button button-primary" type="button" onClick={openCreateMpModal}>
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
                ) : (
                    meteringPoints.map((point) => {
                        const assignments = filteredAssignmentsByMeteringPoint.get(point.id) ?? []
                        const todayIso = new Date().toISOString().slice(0, 10)

                        return (
                            <div
                                key={point.id}
                                style={{
                                    border: '1px solid var(--color-border, #e0e0e0)',
                                    borderRadius: '6px',
                                    marginBottom: '1rem',
                                    overflow: 'hidden',
                                }}
                            >
                                {/* Header row */}
                                <div
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.75rem',
                                        padding: '0.75rem 1rem',
                                        background: 'var(--color-surface-alt, #f6f8fa)',
                                        borderBottom: assignments.length > 0 ? '1px solid var(--color-border, #e0e0e0)' : undefined,
                                        flexWrap: 'wrap',
                                    }}
                                >
                                    <div style={{ flex: 1, minWidth: 180 }}>
                                        <span
                                            style={{
                                                fontSize: '0.78rem',
                                                padding: '2px 8px',
                                                borderRadius: '4px',
                                                background: point.is_active ? '#d1fae5' : '#fee2e2',
                                                color: point.is_active ? '#065f46' : '#991b1b',
                                                marginRight: '0.6rem',
                                            }}
                                        >
                                            {point.is_active ? t('pages.meteringPoints.active') : t('pages.meteringPoints.inactive')}
                                        </span>
                                        <strong>{point.meter_id}</strong>
                                    </div>
                                    <span className="muted" style={{ fontSize: '0.82rem' }}><strong>{t('pages.meteringPoints.typeLabel')}</strong> {point.meter_type}</span>
                                    {canManageMeteringPoints && (
                                        <button
                                            className="button button-primary"
                                            type="button"
                                            style={{ padding: '4px 10px', fontSize: '0.8rem' }}
                                            onClick={() => openCreateAssignModal(point.id)}
                                        >
                                            {t('pages.meteringPoints.assign')}
                                        </button>
                                    )}
                                    <Link
                                        className="button button-primary"
                                        style={{ padding: '4px 10px', fontSize: '0.8rem', textDecoration: 'none' }}
                                        to={`/metering-data?metering_point=${point.id}`}
                                    >
                                        {t('pages.meteringPoints.chart')}
                                    </Link>
                                    {canManageMeteringPoints && (
                                        <>
                                            <button
                                                className="button button-primary"
                                                type="button"
                                                style={{ padding: '4px 10px', fontSize: '0.8rem' }}
                                                onClick={() => openEditMpModal(point)}
                                            >
                                                Edit
                                            </button>
                                            <button
                                                className="button danger"
                                                type="button"
                                                style={{ padding: '4px 10px', fontSize: '0.8rem' }}
                                                disabled={deleteMpMutation.isPending || dialogLoading}
                                                onClick={() => confirm({
                                                    title: t('pages.meteringPoints.deleteTitle'),
                                                    message: t('pages.meteringPoints.deleteMessage', { meterId: point.meter_id }),
                                                    confirmText: t('pages.meteringPoints.deleteConfirm'),
                                                    isDangerous: true,
                                                    onConfirm: () => deleteMpMutation.mutate(point.id),
                                                })}
                                            >
                                                Delete
                                            </button>
                                        </>
                                    )}
                                </div>

                                {/* Assignment rows */}
                                {canManageMeteringPoints && assignments.length > 0 ? (
                                    <table style={{ width: '100%', fontSize: '0.88rem' }}>
                                        <thead>
                                            <tr>
                                                <th style={{ textAlign: 'left', padding: '0.4rem 1rem', fontWeight: 500 }}>
                                                    {t('pages.meteringPoints.assignCol.participant')}
                                                </th>
                                                <th style={{ textAlign: 'left', padding: '0.4rem 1rem', fontWeight: 500 }}>
                                                    {t('pages.meteringPoints.assignCol.validFrom')}
                                                </th>
                                                <th style={{ textAlign: 'left', padding: '0.4rem 1rem', fontWeight: 500 }}>{t('pages.meteringPoints.assignCol.validTo')}</th>
                                                <th style={{ padding: '0.4rem 1rem' }}></th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {assignments.map((a) => (
                                                <tr
                                                    key={a.id}
                                                    style={{
                                                        borderTop: '1px solid var(--color-border, #e0e0e0)',
                                                        background: a.valid_to && a.valid_to < todayIso ? '#f8fafc' : undefined,
                                                        color: a.valid_to && a.valid_to < todayIso ? '#94a3b8' : undefined,
                                                    }}
                                                >
                                                    <td style={{ padding: '0.4rem 1rem' }}>
                                                        {participantNameById.get(a.participant) ?? a.participant}
                                                    </td>
                                                    <td style={{ padding: '0.4rem 1rem' }}>{formatShortDate(a.valid_from, settings)}</td>
                                                    <td style={{ padding: '0.4rem 1rem' }}>{a.valid_to ? formatShortDate(a.valid_to, settings) : '—'}</td>
                                                    <td style={{ padding: '0.4rem 1rem', textAlign: 'right' }}>
                                                        <span style={{ display: 'inline-flex', gap: '0.5rem' }}>
                                                            <button
                                                                className="button button-primary"
                                                                type="button"
                                                                style={{ padding: '2px 8px', fontSize: '0.78rem' }}
                                                                onClick={() => openEditAssignModal(a)}
                                                            >
                                                                Edit
                                                            </button>
                                                            <button
                                                                className="button danger"
                                                                type="button"
                                                                style={{ padding: '2px 8px', fontSize: '0.78rem' }}
                                                                disabled={deleteAssignMutation.isPending || dialogLoading}
                                                                onClick={() => confirm({
                                                                    title: t('pages.meteringPoints.removeAssignTitle'),
                                                                    message: t('pages.meteringPoints.removeAssignMessage', { name: participantNameById.get(a.participant) ?? a.participant }),
                                                                    confirmText: t('pages.meteringPoints.removeAssignConfirm'),
                                                                    isDangerous: true,
                                                                    onConfirm: () => deleteAssignMutation.mutate(a.id),
                                                                })}
                                                            >
                                                                Remove
                                                            </button>
                                                        </span>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                ) : canManageMeteringPoints ? (
                                    <p
                                        className="muted"
                                        style={{ margin: 0, padding: '0.5rem 1rem', fontSize: '0.82rem', fontStyle: 'italic' }}
                                    >
                                        {t('pages.meteringPoints.noAssignments')}
                                    </p>
                                ) : null}
                            </div>
                        )
                    })
                )}
            </div>

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
        </div>
    )
}
