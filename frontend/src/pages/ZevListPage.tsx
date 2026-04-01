import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type FormEvent } from 'react'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { ZevEmailTemplateFields } from '../components/ZevEmailTemplateFields'
import { ZevGeneralSettingsFields } from '../components/ZevGeneralSettingsFields'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { FormModal } from '../components/FormModal'
import { createZevWithOwner, deleteZev, fetchParticipants, fetchUsers, fetchZevs, formatApiError, updateZev } from '../lib/api'
import { useTranslation } from 'react-i18next'
import { getDefaultZevForm, mapZevToForm } from '../lib/zevForm'
import type { OwnerMeteringPointInput, Zev, ZevInput, ZevWizardInput, ZevWizardResult } from '../types/api'

const defaultCreateForm = (): ZevWizardInput => ({
    name: '',
    start_date: new Date().toISOString().slice(0, 10),
    zev_type: 'vzev',
    grid_operator: '',
    billing_interval: 'monthly',
    owner: {
        title: '',
        first_name: '',
        last_name: '',
        email: '',
        phone: '',
        address_line1: '',
        address_line2: '',
        postal_code: '',
        city: '',
        username: '',
    },
    metering_points: [
        {
            meter_id: '',
            meter_type: 'consumption',
            is_active: true,
            location_description: '',
        },
    ],
})

type WizardStep = 1 | 2 | 3 | 4 | 5

export function ZevListPage() {
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const isAdmin = user?.role === 'admin'
    const { t } = useTranslation()
    const queryClient = useQueryClient()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const { data, isLoading, isError } = useQuery({ queryKey: ['zevs'], queryFn: fetchZevs })
    const usersQuery = useQuery({
        queryKey: ['users'],
        queryFn: fetchUsers,
        enabled: isAdmin,
    })
    const participantsQuery = useQuery({
        queryKey: ['participants'],
        queryFn: fetchParticipants,
        enabled: isAdmin,
    })

    const [editingId, setEditingId] = useState<string | null>(null)
    const [editForm, setEditForm] = useState<ZevInput>(getDefaultZevForm())
    const [createForm, setCreateForm] = useState<ZevWizardInput>(defaultCreateForm)
    const [wizardStep, setWizardStep] = useState<WizardStep>(1)
    const [showEditModal, setShowEditModal] = useState(false)
    const [showOwnerModal, setShowOwnerModal] = useState(false)
    const [showCreateModal, setShowCreateModal] = useState(false)
    const [editError, setEditError] = useState<string | null>(null)
    const [ownerError, setOwnerError] = useState<string | null>(null)
    const [createError, setCreateError] = useState<string | null>(null)
    const [createdCredentials, setCreatedCredentials] = useState<ZevWizardResult['owner'] | null>(null)
    const [createdZevName, setCreatedZevName] = useState<string>('')
    const [copyFeedback, setCopyFeedback] = useState<string | null>(null)
    const [expandedMeteringPointIndex, setExpandedMeteringPointIndex] = useState<number | null>(null)
    const [editingMeteringPointData, setEditingMeteringPointData] = useState<OwnerMeteringPointInput | null>(null)
    const [ownerTargetZev, setOwnerTargetZev] = useState<Zev | null>(null)
    const [newOwnerId, setNewOwnerId] = useState<string>('')
    const createSubmittedRef = useRef(false)

    const createMutation = useMutation({
        mutationFn: createZevWithOwner,
        onSuccess: (result) => {
            setCreateError(null)
            setCreatedCredentials(result.owner)
            setCreatedZevName(result.zev.name)
            setWizardStep(5)
            void queryClient.invalidateQueries({ queryKey: ['zevs'] })
        },
        onError: (error) => setCreateError(formatApiError(error, 'Failed to create ZEV.')),
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, payload }: { id: string; payload: Partial<ZevInput> }) => updateZev(id, payload),
        onSuccess: () => {
            setEditingId(null)
            setEditForm(getDefaultZevForm())
            setShowEditModal(false)
            setEditError(null)
            void queryClient.invalidateQueries({ queryKey: ['zevs'] })
        },
        onError: (error) => setEditError(formatApiError(error, 'Failed to update ZEV.')),
    })

    const deleteMutation = useMutation({
        mutationFn: deleteZev,
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['zevs'] })
        },
    })

    const assignOwnerMutation = useMutation({
        mutationFn: ({ id, owner }: { id: string; owner: number }) => updateZev(id, { owner }),
        onSuccess: () => {
            setShowOwnerModal(false)
            setOwnerTargetZev(null)
            setNewOwnerId('')
            setOwnerError(null)
            void queryClient.invalidateQueries({ queryKey: ['zevs'] })
        },
        onError: (error) => setOwnerError(formatApiError(error, 'Failed to assign owner.')),
    })

    function startEdit(zev: Zev) {
        setEditingId(zev.id)
        setEditForm(mapZevToForm(zev))
        setEditError(null)
        setShowEditModal(true)
    }

    function openCreateModal() {
        if (!isAdmin) {
            return
        }
        setCreateForm(defaultCreateForm())
        setWizardStep(1)
        setCreateError(null)
        setShowCreateModal(true)
    }

    function openOwnerModal(zev: Zev) {
        setOwnerTargetZev(zev)
        setNewOwnerId(String(zev.owner))
        setOwnerError(null)
        setShowOwnerModal(true)
    }

    function closeOwnerModal() {
        setShowOwnerModal(false)
        setOwnerTargetZev(null)
        setNewOwnerId('')
        setOwnerError(null)
    }

    function closeEditModal() {
        setShowEditModal(false)
        setEditingId(null)
        setEditForm(getDefaultZevForm())
        setEditError(null)
    }

    function closeCreateModal() {
        setShowCreateModal(false)
        setCreateError(null)
        setWizardStep(1)
        setExpandedMeteringPointIndex(null)
        setEditingMeteringPointData(null)
        setCreatedCredentials(null)
        setCreatedZevName('')
        setCopyFeedback(null)
        createSubmittedRef.current = false
        if (wizardStep === 5) {
            setCreateForm(defaultCreateForm())
        }
    }

    async function copyToClipboard(value: string, label: string) {
        try {
            await navigator.clipboard.writeText(value)
            setCopyFeedback(`${label} copied.`)
            window.setTimeout(() => setCopyFeedback(null), 2000)
        } catch {
            setCopyFeedback(`Could not copy ${label.toLowerCase()}.`)
            window.setTimeout(() => setCopyFeedback(null), 2000)
        }
    }

    function submitEdit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!editingId) return
        updateMutation.mutate({ id: editingId, payload: editForm })
    }

    function validateWizardStep(step: WizardStep): string | null {
        if (step === 1) {
            if (!createForm.name.trim()) return 'ZEV name is required.'
            if (!createForm.start_date) return 'Start date is required.'
        }

        if (step === 2) {
            if (!createForm.owner.first_name.trim()) return 'Owner first name is required.'
            if (!createForm.owner.last_name.trim()) return 'Owner last name is required.'
            if (!createForm.owner.email.trim()) return 'Owner email is required.'
        }

        if (step === 3) {
            if (!createForm.metering_points.length) return 'At least one metering point is required.'
            if (createForm.metering_points.some((point) => !point.meter_id.trim())) {
                return 'Each metering point needs a meter ID.'
            }
        }

        return null
    }

    function goToNextStep() {
        const validationError = validateWizardStep(wizardStep)
        if (validationError) {
            setCreateError(validationError)
            return
        }
        setCreateError(null)
        const nextStep = (wizardStep < 4 ? wizardStep + 1 : wizardStep) as WizardStep
        setWizardStep(nextStep)
        // Auto-open the first metering point for editing when entering step 3
        if (nextStep === 3 && createForm.metering_points.length > 0 && expandedMeteringPointIndex === null) {
            setEditingMeteringPointData({ ...createForm.metering_points[0] })
            setExpandedMeteringPointIndex(0)
        }
    }

    function goToPreviousStep() {
        setCreateError(null)
        setWizardStep((previous) => (previous > 1 ? (previous - 1) as WizardStep : previous))
    }

    function submitCreate(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
    }

    function handleCreateZev() {
        if (wizardStep !== 4 || createSubmittedRef.current || createMutation.isPending) return
        createSubmittedRef.current = true
        createMutation.mutate(createForm)
    }

    function submitOwnerAssignment(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!ownerTargetZev || !newOwnerId) {
            setOwnerError('Please select a new owner.')
            return
        }

        const currentOwnerName = ownerNameById.get(ownerTargetZev.owner) ?? `User ${ownerTargetZev.owner}`
        const nextOwnerNumericId = Number(newOwnerId)
        const nextOwnerName = ownerNameById.get(nextOwnerNumericId) ?? `User ${newOwnerId}`

        confirm({
            title: t('pages.zevs.ownerModal.transferTitle'),
            message: t('pages.zevs.ownerModal.transferMessage', { zev: ownerTargetZev.name, from: currentOwnerName, to: nextOwnerName }),
            confirmText: t('pages.zevs.ownerModal.transferConfirm'),
            cancelText: 'Cancel',
            isDangerous: true,
            onConfirm: async () => {
                await assignOwnerMutation.mutateAsync({ id: ownerTargetZev.id, owner: nextOwnerNumericId })
            },
        })
    }

    function addMeteringPoint() {
        const newPoint: OwnerMeteringPointInput = {
            meter_id: '',
            meter_type: 'consumption',
            is_active: true,
            location_description: '',
        }
        setEditingMeteringPointData(newPoint)
        setExpandedMeteringPointIndex(-1)
    }

    function openEditMeteringPoint(index: number) {
        setEditingMeteringPointData({ ...createForm.metering_points[index] })
        setExpandedMeteringPointIndex(index)
    }

    function closeEditMeteringPoint() {
        setExpandedMeteringPointIndex(null)
        setEditingMeteringPointData(null)
    }

    function updateEditingMeteringPoint(updates: Partial<OwnerMeteringPointInput>) {
        if (!editingMeteringPointData) return
        setEditingMeteringPointData({ ...editingMeteringPointData, ...updates })
    }

    function saveMeteringPoint() {
        if (!editingMeteringPointData) return
        if (expandedMeteringPointIndex === -1) {
            // Add new metering point
            setCreateForm((previous) => ({ ...previous, metering_points: [...previous.metering_points, editingMeteringPointData] }))
        } else if (expandedMeteringPointIndex !== null && expandedMeteringPointIndex >= 0) {
            // Update existing metering point
            setCreateForm((previous) => ({
                ...previous,
                metering_points: previous.metering_points.map((point, pointIndex) => (
                    pointIndex === expandedMeteringPointIndex ? editingMeteringPointData : point
                )),
            }))
        }
        closeEditMeteringPoint()
    }

    function removeMeteringPoint(index: number) {
        setCreateForm((previous) => {
            if (previous.metering_points.length <= 1) return previous
            return {
                ...previous,
                metering_points: previous.metering_points.filter((_, pointIndex) => pointIndex !== index),
            }
        })
        // Close accordion if we're editing the deleted point
        if (expandedMeteringPointIndex === index) {
            closeEditMeteringPoint()
        }
    }

    if (isLoading) return <div className="card">Loading ZEVs...</div>
    if (isError) return <div className="card error-banner">Failed to load ZEVs.</div>

    const ownerNameById = new Map((usersQuery.data?.results ?? []).map((candidate) => [candidate.id, `${candidate.first_name} ${candidate.last_name}`]))
    const linkedParticipantsForTarget = (participantsQuery.data?.results ?? []).filter((participant) => (
        participant.zev === ownerTargetZev?.id && participant.user != null
    ))
    const ownerCandidates = linkedParticipantsForTarget
        .map((participant) => {
            const linkedUserId = participant.user as number
            const linkedUser = usersQuery.data?.results.find((candidate) => candidate.id === linkedUserId)
            return {
                participant,
                userId: linkedUserId,
                label: linkedUser
                    ? `${participant.first_name} ${participant.last_name} (${linkedUser.username})`
                    : `${participant.first_name} ${participant.last_name}`,
                email: linkedUser?.email || participant.email || '',
            }
        })
        .sort((left, right) => left.label.localeCompare(right.label))

    const currentOwnerId = ownerTargetZev ? String(ownerTargetZev.owner) : ''
    const currentOwnerLabel = ownerTargetZev
        ? ownerCandidates.find((candidate) => String(candidate.userId) === String(ownerTargetZev.owner))?.label
        ?? ownerNameById.get(ownerTargetZev.owner)
        ?? `User ${ownerTargetZev.owner}`
        : ''
    const eligibleOwnerCandidates = ownerCandidates.filter((candidate) => String(candidate.userId) !== currentOwnerId)

    return (
        <div className="page-stack">
            <header>
                <h2>{t('pages.zevs.title')}</h2>
                <p className="muted">{t('pages.zevs.description')}</p>
            </header>

            <div className="actions-row actions-row-gap-lg mb-1">
                {isAdmin ? (
                    <button className="button button-primary" onClick={openCreateModal}>
                        {t('pages.zevs.newZev')}
                    </button>
                ) : (
                    <p className="muted" style={{ margin: 0 }}>{t('pages.zevs.adminOnly')}</p>
                )}
            </div>

            <FormModal isOpen={showCreateModal} title={wizardStep === 5 ? t('pages.zevs.wizard.titleDone') : t('pages.zevs.wizard.titleStep', { step: wizardStep })} onClose={closeCreateModal} maxWidth="960px">
                <form onSubmit={submitCreate} className="form-grid">
                    {wizardStep === 1 && (
                        <>
                            <div className="card grid-span-full" style={{ padding: '0.85rem 1rem' }}>
                                <strong>{t('pages.zevs.wizard.step1Header')}</strong>
                                <p className="muted" style={{ margin: '0.35rem 0 0' }}>{t('pages.zevs.wizard.step1Description')}</p>
                            </div>
                            <label>
                                <span>{t('pages.zevs.form.name')}</span>
                                <input value={createForm.name} onChange={(event) => setCreateForm((previous) => ({ ...previous, name: event.target.value }))} required />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.startDate')}</span>
                                <input type="date" value={createForm.start_date} onChange={(event) => setCreateForm((previous) => ({ ...previous, start_date: event.target.value }))} required />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.zevType')}</span>
                                <select value={createForm.zev_type} onChange={(event) => setCreateForm((previous) => ({ ...previous, zev_type: event.target.value as ZevInput['zev_type'] }))}>
                                    <option value="vzev">{t('pages.zevs.zevTypes.vzev')}</option>
                                    <option value="zev">{t('pages.zevs.zevTypes.zev')}</option>
                                </select>
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.billingInterval')}</span>
                                <select value={createForm.billing_interval} onChange={(event) => setCreateForm((previous) => ({ ...previous, billing_interval: event.target.value as ZevInput['billing_interval'] }))}>
                                    <option value="monthly">{t('pages.zevs.billingIntervals.monthly')}</option>
                                    <option value="quarterly">{t('pages.zevs.billingIntervals.quarterly')}</option>
                                    <option value="semi_annual">{t('pages.zevs.billingIntervals.semi_annual')}</option>
                                    <option value="annual">{t('pages.zevs.billingIntervals.annual')}</option>
                                </select>
                            </label>
                            <label className="grid-span-full">
                                <span>{t('pages.zevs.form.gridOperator')}</span>
                                <input value={createForm.grid_operator ?? ''} onChange={(event) => setCreateForm((previous) => ({ ...previous, grid_operator: event.target.value }))} />
                            </label>
                        </>
                    )}

                    {wizardStep === 2 && (
                        <>
                            <div className="card grid-span-full" style={{ padding: '0.85rem 1rem' }}>
                                <strong>{t('pages.zevs.wizard.step2Header')}</strong>
                                <p className="muted" style={{ margin: '0.35rem 0 0' }}>{t('pages.zevs.wizard.step2Description')}</p>
                            </div>
                            <label>
                                <span>{t('pages.zevs.form.title')}</span>
                                <select value={createForm.owner.title ?? ''} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, title: event.target.value as ZevWizardInput['owner']['title'] } }))}>
                                    <option value="">{t('pages.zevs.titles.none')}</option>
                                    <option value="mr">{t('pages.zevs.titles.mr')}</option>
                                    <option value="mrs">{t('pages.zevs.titles.mrs')}</option>
                                    <option value="ms">{t('pages.zevs.titles.ms')}</option>
                                    <option value="dr">{t('pages.zevs.titles.dr')}</option>
                                    <option value="prof">{t('pages.zevs.titles.prof')}</option>
                                </select>
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.usernameOptional')}</span>
                                <input value={createForm.owner.username ?? ''} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, username: event.target.value } }))} />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.firstName')}</span>
                                <input value={createForm.owner.first_name} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, first_name: event.target.value } }))} required />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.lastName')}</span>
                                <input value={createForm.owner.last_name} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, last_name: event.target.value } }))} required />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.email')}</span>
                                <input type="email" value={createForm.owner.email} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, email: event.target.value } }))} required />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.phone')}</span>
                                <input value={createForm.owner.phone ?? ''} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, phone: event.target.value } }))} />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.addressLine1')}</span>
                                <input value={createForm.owner.address_line1 ?? ''} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, address_line1: event.target.value } }))} />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.addressLine2')}</span>
                                <input value={createForm.owner.address_line2 ?? ''} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, address_line2: event.target.value } }))} />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.postalCode')}</span>
                                <input value={createForm.owner.postal_code ?? ''} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, postal_code: event.target.value } }))} />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.city')}</span>
                                <input value={createForm.owner.city ?? ''} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, city: event.target.value } }))} />
                            </label>
                        </>
                    )}

                    {wizardStep === 3 && (
                        <div className="grid-span-full page-stack">
                            <div className="card" style={{ padding: '0.85rem 1rem' }}>
                                <strong>{t('pages.zevs.wizard.step3Header')}</strong>
                                <p className="muted" style={{ margin: '0.35rem 0 0' }}>{t('pages.zevs.wizard.step3Description')}</p>
                            </div>

                            <div>
                                <button className="button button-secondary" type="button" onClick={addMeteringPoint}>{t('pages.zevs.wizard.addMeteringPoint')}</button>
                            </div>

                            {expandedMeteringPointIndex !== null && editingMeteringPointData && (
                                <div className="card" style={{ padding: '1rem', border: '1px solid var(--border-color)' }}>
                                    <h4 style={{ marginTop: 0, marginBottom: '1rem' }}>
                                        {expandedMeteringPointIndex === -1 ? t('pages.zevs.wizard.newMeteringPointTitle') : t('pages.zevs.wizard.editMeteringPointTitle')}
                                    </h4>
                                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1rem', marginBottom: '1rem' }}>
                                        <label>
                                            <span>{t('pages.zevs.form.meterId')}</span>
                                            <input
                                                value={editingMeteringPointData.meter_id}
                                                onChange={(event) => updateEditingMeteringPoint({ meter_id: event.target.value })}
                                                required
                                            />
                                        </label>
                                        <label>
                                            <span>{t('pages.zevs.form.meterType')}</span>
                                            <select
                                                value={editingMeteringPointData.meter_type}
                                                onChange={(event) => updateEditingMeteringPoint({ meter_type: event.target.value as OwnerMeteringPointInput['meter_type'] })}
                                            >
                                                <option value="consumption">{t('pages.zevs.meterTypes.consumption')}</option>
                                                <option value="production">{t('pages.zevs.meterTypes.production')}</option>
                                                <option value="bidirectional">{t('pages.zevs.meterTypes.bidirectional')}</option>
                                            </select>
                                        </label>
                                        <label className="grid-span-full">
                                            <span>{t('pages.zevs.form.locationDescription')}</span>
                                            <input
                                                value={editingMeteringPointData.location_description ?? ''}
                                                onChange={(event) => updateEditingMeteringPoint({ location_description: event.target.value })}
                                            />
                                        </label>
                                    </div>
                                    <div style={{ display: 'flex', gap: '0.75rem' }}>
                                        <button className="button button-primary" type="button" onClick={saveMeteringPoint}>
                                            {expandedMeteringPointIndex === -1 ? t('pages.zevs.wizard.add') : t('pages.zevs.wizard.save')}
                                        </button>
                                        <button className="button button-secondary" type="button" onClick={closeEditMeteringPoint}>{t('pages.tariffs.cancel')}</button>
                                    </div>
                                </div>
                            )}

                            {createForm.metering_points.length > 0 && (
                                <div className="table-card" style={{ padding: '0.5rem' }}>
                                    <table>
                                        <thead>
                                            <tr>
                                                <th>{t('pages.zevs.meterCol.meterId')}</th>
                                                <th>{t('pages.zevs.meterCol.type')}</th>
                                                <th>{t('pages.zevs.meterCol.location')}</th>
                                                <th>{t('pages.zevs.meterCol.actions')}</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {createForm.metering_points.map((meteringPoint, index) => (
                                                <tr key={`${index}-${meteringPoint.meter_id}`}>
                                                    <td>{meteringPoint.meter_id}</td>
                                                    <td>{meteringPoint.meter_type}</td>
                                                    <td>{meteringPoint.location_description || '-'}</td>
                                                    <td>
                                                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                            <button
                                                                className="button button-secondary"
                                                                type="button"
                                                                onClick={() => openEditMeteringPoint(index)}
                                                            >
                                                                Edit
                                                            </button>
                                                            <button
                                                                className="button danger"
                                                                type="button"
                                                                onClick={() => removeMeteringPoint(index)}
                                                                disabled={createForm.metering_points.length === 1}
                                                            >
                                                                Delete
                                                            </button>
                                                        </div>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </div>
                    )}

                    {wizardStep === 4 && (
                        <div className="card grid-span-full">
                            <h3 style={{ marginTop: 0 }}>{t('pages.zevs.wizard.review')}</h3>
                            <p><strong>{t('pages.zevs.wizard.reviewZev')}</strong> {createForm.name} ({t(`pages.zevs.zevTypes.${createForm.zev_type}` as Parameters<typeof t>[0])}) starting {formatShortDate(createForm.start_date, settings)}</p>
                            <p><strong>{t('pages.zevs.wizard.reviewOwner')}</strong> {createForm.owner.first_name} {createForm.owner.last_name} ({createForm.owner.email})</p>
                            <p><strong>{t('pages.zevs.wizard.reviewMeteringPoints')}</strong> {createForm.metering_points.length}</p>
                            <p className="muted" style={{ marginBottom: 0 }}>{t('pages.zevs.wizard.reviewHint')}</p>
                        </div>
                    )}

                    {wizardStep === 5 && createdCredentials && (
                        <div className="grid-span-full page-stack">
                            <p style={{ margin: 0 }}>
                                {t('pages.zevs.wizard.createdIntro', { name: createdZevName })}
                            </p>

                            <div className="card" style={{ padding: '1rem' }}>
                                <p style={{ margin: '0 0 0.5rem' }}><strong>{t('pages.zevs.wizard.usernameLabel')}</strong></p>
                                <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                    <code>{createdCredentials.username}</code>
                                    <button
                                        className="button button-secondary"
                                        type="button"
                                        onClick={() => copyToClipboard(createdCredentials.username, 'Username')}
                                    >
                                        {t('pages.zevs.wizard.copyUsername')}
                                    </button>
                                </div>

                                <p style={{ margin: '1rem 0 0.5rem' }}><strong>{t('pages.zevs.wizard.passwordLabel')}</strong></p>
                                <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                    <code>{createdCredentials.temporary_password}</code>
                                    <button
                                        className="button button-secondary"
                                        type="button"
                                        onClick={() => copyToClipboard(createdCredentials.temporary_password, 'Password')}
                                    >
                                        {t('pages.zevs.wizard.copyPassword')}
                                    </button>
                                </div>
                            </div>

                            {copyFeedback && <div className="muted">{copyFeedback}</div>}
                        </div>
                    )}

                    {createError && <div className="error-banner grid-span-full">{createError}</div>}

                    <div className="actions-row actions-row-end actions-row-gap-lg grid-span-full mt-1">
                        {wizardStep < 5 && <button className="button button-secondary" type="button" onClick={closeCreateModal}>{t('pages.tariffs.cancel')}</button>}
                        {wizardStep > 1 && wizardStep < 5 && <button className="button button-secondary" type="button" onClick={goToPreviousStep}>{t('pages.zevs.wizard.back')}</button>}
                        {wizardStep < 4 && (
                            <button key="next" className="button button-primary" type="button" onClick={goToNextStep}>{t('pages.zevs.wizard.next')}</button>
                        )}
                        {wizardStep === 4 && (
                            <button key="create" className="button button-primary" type="button" onClick={handleCreateZev} disabled={createMutation.isPending}>
                                {createMutation.isPending ? t('pages.zevs.wizard.creating') : t('pages.zevs.wizard.createZev')}
                            </button>
                        )}
                        {wizardStep === 5 && (
                            <button key="done" className="button button-primary" type="button" onClick={closeCreateModal}>{t('pages.zevs.wizard.done')}</button>
                        )}
                    </div>
                </form>
            </FormModal>

            <FormModal isOpen={showEditModal} title={t('pages.zevs.editModalTitle')} onClose={closeEditModal} maxWidth="960px">
                <form onSubmit={submitEdit} className="page-stack">
                    <section className="card page-stack">
                        <ZevGeneralSettingsFields
                            form={editForm}
                            onChange={(patch) => setEditForm((previous) => ({ ...previous, ...patch }))}
                        />
                    </section>

                    <section className="card page-stack">
                        <ZevEmailTemplateFields
                            subjectTemplate={editForm.email_subject_template ?? ''}
                            bodyTemplate={editForm.email_body_template ?? ''}
                            onSubjectTemplateChange={(value) =>
                                setEditForm((previous) => ({ ...previous, email_subject_template: value }))
                            }
                            onBodyTemplateChange={(value) =>
                                setEditForm((previous) => ({ ...previous, email_body_template: value }))
                            }
                        />
                    </section>

                    {editError && <div className="error-banner">{editError}</div>}

                    <div className="actions-row actions-row-end actions-row-gap-lg">
                        <button className="button button-secondary" type="button" onClick={closeEditModal}>{t('pages.tariffs.cancel')}</button>
                        <button className="button button-primary" type="submit" disabled={updateMutation.isPending}>{t('pages.zevs.saveZev')}</button>
                    </div>
                </form>
            </FormModal>

            <FormModal isOpen={showOwnerModal} title={t('pages.zevs.ownerModal.title')} onClose={closeOwnerModal} maxWidth="560px">
                <form onSubmit={submitOwnerAssignment} style={{ display: 'grid', gap: '1rem' }}>
                    <p style={{ margin: 0 }}>
                        {t('pages.zevs.ownerModal.intro', { name: ownerTargetZev?.name ?? '-' })}
                    </p>

                    <label>
                        <span>{t('pages.zevs.ownerModal.ownerLabel')}</span>
                        <select value={newOwnerId} onChange={(event) => setNewOwnerId(event.target.value)} required>
                            <option value="">{t('pages.zevs.ownerModal.selectOwner')}</option>
                            {ownerTargetZev && (
                                <optgroup label={t('pages.zevs.ownerModal.currentGroup')}>
                                    <option value={String(ownerTargetZev.owner)} disabled>
                                        {currentOwnerLabel}
                                    </option>
                                </optgroup>
                            )}
                            {eligibleOwnerCandidates.length > 0 && (
                                <optgroup label={t('pages.zevs.ownerModal.eligibleGroup')}>
                                    {eligibleOwnerCandidates.map((candidate) => (
                                        <option key={candidate.userId} value={candidate.userId}>
                                            {candidate.label}{candidate.email ? ` (${candidate.email})` : ''}
                                        </option>
                                    ))}
                                </optgroup>
                            )}
                        </select>
                    </label>

                    {eligibleOwnerCandidates.length === 0 && (
                        <div className="muted">{t('pages.zevs.ownerModal.noEligible')}</div>
                    )}

                    {ownerError && <div className="error-banner">{ownerError}</div>}

                    <div className="actions-row actions-row-end actions-row-gap-lg">
                        <button className="button button-secondary" type="button" onClick={closeOwnerModal}>{t('pages.tariffs.cancel')}</button>
                        <button
                            className="button button-primary"
                            type="submit"
                            disabled={assignOwnerMutation.isPending || dialogLoading || !ownerTargetZev || String(ownerTargetZev.owner) === newOwnerId}
                        >
                            {t('pages.zevs.ownerModal.saveOwner')}
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

            <div className="table-card">
                <table>
                    <thead>
                        <tr>
                            <th>{t('pages.zevs.col.name')}</th>
                            <th>{t('pages.zevs.col.owner')}</th>
                            <th>{t('pages.zevs.col.startDate')}</th>
                            <th>{t('pages.zevs.col.gridOperator')}</th>
                            <th>{t('pages.zevs.col.billingInterval')}</th>
                            <th>{t('pages.zevs.col.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {data?.results.length ? data.results.map((zev) => (
                            <tr key={zev.id}>
                                <td>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <span>{zev.name}</span>
                                        <span className="badge badge-info">
                                            {zev.zev_type.toUpperCase()}
                                        </span>
                                    </div>
                                </td>
                                <td>{ownerNameById.get(zev.owner) ?? (user?.id === zev.owner ? user.username : zev.owner)}</td>
                                <td>{formatShortDate(zev.start_date, settings)}</td>
                                <td>{zev.grid_operator || '-'}</td>
                                <td>{t(`pages.zevs.billingIntervals.${zev.billing_interval}` as Parameters<typeof t>[0], { defaultValue: zev.billing_interval })}</td>
                                <td className="actions-cell">
                                    <button className="button button-primary" type="button" onClick={() => startEdit(zev)}>Edit</button>
                                    {isAdmin && (
                                        <button className="button button-secondary" type="button" onClick={() => openOwnerModal(zev)}>
                                            {t('pages.zevs.setOwner')}
                                        </button>
                                    )}
                                    <button className="button danger" type="button" disabled={deleteMutation.isPending || dialogLoading} onClick={() => confirm({
                                        title: t('pages.zevs.deleteTitle'),
                                        message: t('pages.zevs.deleteMessage', { name: zev.name }),
                                        confirmText: t('pages.zevs.deleteConfirm'),
                                        isDangerous: true,
                                        onConfirm: () => deleteMutation.mutate(zev.id),
                                    })}>Delete</button>
                                </td>
                            </tr>
                        )) : (
                            <tr>
                                <td colSpan={6}>{t('pages.zevs.noZevs')}</td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    )
}
