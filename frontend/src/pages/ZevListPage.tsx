import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faArrowLeft,
    faArrowRight,
    faBan,
    faCheck,
    faCopy,
    faPen,
    faPlay,
    faPlus,
    faSkullCrossbones,
    faTrash,
    faUpload,
    faXmark,
} from '@fortawesome/free-solid-svg-icons'
import { useManagedZev } from '../lib/managedZev'
import { useToast } from '../lib/toast'
import { ConfirmDialog, consumeReportedError, useConfirmDialog } from '../components/ConfirmDialog'
import { ZevEmailTemplateFields } from '../components/ZevEmailTemplateFields'
import { ZevGeneralSettingsFields } from '../components/ZevGeneralSettingsFields'
import { ZevImportModal } from '../features/zev/ZevImportModal'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { FormModal } from '../components/FormModal'
import { createZevWithOwner, disableZev, enableZev, fetchZevs, purgeZev, updateZev } from '../lib/api/zev'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { EmptyState } from '../components/EmptyState'
import { PageSkeleton } from '../components/PageSkeleton'
import { useTranslation } from 'react-i18next'
import { todayBusinessIso } from '../lib/dates'
import { isValidIban, normalizeIban } from '../lib/iban'
import { getDefaultZevForm, mapZevToForm } from '../lib/zevForm'
import { copyToClipboard } from '../lib/clipboard'
import { BILLING_INTERVAL_OPTIONS, METER_TYPE_OPTIONS, ZEV_TYPE_OPTIONS } from '../lib/options'
import { TITLE_KEYS } from '../lib/participantTitle'
import type { OwnerMeteringPointInput, Zev, ZevInput, ZevWizardInput, ZevWizardResult } from '../types/api'
import { GridOperatorField } from '../features/zev/GridOperatorField'
import { GridOperatorSuggestion } from '../features/zev/GridOperatorSuggestion'
import { PageHeader } from '../components/PageHeader'
import { Notice } from '../components/Notice'

const defaultCreateForm = (): ZevWizardInput => ({
    name: '',
    start_date: todayBusinessIso(),
    zev_type: 'vzev',
    grid_operator: '',
    billing_interval: 'monthly',
    bank_iban: '',
    bank_name: '',
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

type MeteringPointError = 'missing' | 'duplicate'

let meteringPointKeySeed = 0

/**
 * Stable per-row identity for wizard metering points. Row indexes shift when an
 * earlier row is deleted, so the active editor is tracked by key instead.
 */
function createMeteringPointKey(): string {
    meteringPointKeySeed += 1
    return `metering-point-${meteringPointKeySeed}`
}

/**
 * Per-row problems on the metering point step: a missing meter ID, or one
 * already used by an earlier row. Keyed by row index.
 */
function getMeteringPointErrors(points: OwnerMeteringPointInput[]): Record<number, MeteringPointError> {
    const errors: Record<number, MeteringPointError> = {}
    const seen = new Set<string>()
    points.forEach((point, index) => {
        const meterId = point.meter_id.trim()
        if (!meterId) {
            errors[index] = 'missing'
        } else if (seen.has(meterId)) {
            errors[index] = 'duplicate'
        }
        seen.add(meterId)
    })
    return errors
}

/**
 * `embedded` drops the page header (mounted inside an admin hub tab since
 * phase 3).
 */
export function ZevListPage({ embedded = false }: { embedded?: boolean }) {
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const isAdmin = user?.role === 'admin'
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { setSelectedZevId } = useManagedZev()
    const queryClient = useQueryClient()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const { dialog: purgeDialog, confirm: confirmPurge, handleConfirm: handlePurgeConfirm, handleCancel: handlePurgeCancel } = useConfirmDialog()
    const { pushToast } = useToast()

    const { data, isLoading, isError, isFetching, refetch } = useQuery({ queryKey: queryKeys.zev.list(), queryFn: fetchZevs })

    const [editingId, setEditingId] = useState<string | null>(null)
    const [editForm, setEditForm] = useState<ZevInput>(getDefaultZevForm())
    const [createForm, setCreateForm] = useState<ZevWizardInput>(defaultCreateForm)
    const [wizardStep, setWizardStep] = useState<WizardStep>(1)
    const [showEditModal, setShowEditModal] = useState(false)
    const [showCreateModal, setShowCreateModal] = useState(false)
    const [showImportModal, setShowImportModal] = useState(false)
    const [editError, setEditError] = useState<string | null>(null)
    const [createError, setCreateError] = useState<string | null>(null)
    const [createdCredentials, setCreatedCredentials] = useState<ZevWizardResult['owner'] | null>(null)
    const [createdZevName, setCreatedZevName] = useState<string>('')
    const [copyFeedback, setCopyFeedback] = useState<string | null>(null)
    const copyFeedbackTimeoutRef = useRef<number | null>(null)
    const [meteringPointKeys, setMeteringPointKeys] = useState<string[]>(() => [createMeteringPointKey()])
    const [showMeteringPointErrors, setShowMeteringPointErrors] = useState(false)
    const [focusMeteringPointKey, setFocusMeteringPointKey] = useState<string | null>(null)
    const createSubmittedRef = useRef(false)
    const [purgeTarget, setPurgeTarget] = useState<Zev | null>(null)
    const [purgeConfirmation, setPurgeConfirmation] = useState('')
    // State controls the button; the ref supplies current input at dispatch.
    const purgeConfirmationRef = useRef('')

    const createMutation = useMutation({
        mutationFn: createZevWithOwner,
        onSuccess: (result) => {
            setCreateError(null)
            setCreatedCredentials(result.owner)
            setCreatedZevName(result.zev.name)
            setWizardStep(5)
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.list() })
        },
        onError: (error) => setCreateError(formatApiError(error, t('pages.zevs.messages.createFailed'))),
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, payload }: { id: string; payload: Partial<ZevInput> }) => updateZev(id, payload),
        onSuccess: () => {
            setEditingId(null)
            setEditForm(getDefaultZevForm())
            setShowEditModal(false)
            setEditError(null)
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.list() })
        },
        onError: (error) => setEditError(formatApiError(error, t('pages.zevs.messages.updateFailed'))),
    })

    const disableMutation = useMutation({
        mutationFn: (id: string) => disableZev(id),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.list() })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.zevs.disableFailed')), 'error'),
    })

    const enableMutation = useMutation({
        mutationFn: enableZev,
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.list() })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.zevs.enableFailed')), 'error'),
    })

    const purgeMutation = useMutation({
        mutationFn: ({ id, confirmation }: { id: string; confirmation: string }) => purgeZev(id, confirmation),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.list() })
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.zevs.purgeFailed')), 'error'),
    })

    function openPurgeDialog(zev: Zev) {
        setPurgeTarget(zev)
        setPurgeConfirmation('')
        purgeConfirmationRef.current = ''
        confirmPurge({
            title: t('pages.zevs.purgeTitle'),
            message: t('pages.zevs.purgeMessage', { name: zev.name }),
            confirmText: t('pages.zevs.purgeConfirm'),
            isDangerous: true,
            onConfirm: () => {
                const confirmation = purgeConfirmationRef.current
                if (confirmation.trim() !== zev.name.trim()) return false
                return consumeReportedError(purgeMutation.mutateAsync({ id: zev.id, confirmation }))
            },
            onCancel: () => {
                setPurgeTarget(null)
                setPurgeConfirmation('')
                purgeConfirmationRef.current = ''
            },
        })
    }

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
        setMeteringPointKeys([createMeteringPointKey()])
        setShowMeteringPointErrors(false)
        setWizardStep(1)
        setCreateError(null)
        setShowCreateModal(true)
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
        setShowMeteringPointErrors(false)
        setCreatedCredentials(null)
        setCreatedZevName('')
        if (copyFeedbackTimeoutRef.current) window.clearTimeout(copyFeedbackTimeoutRef.current)
        setCopyFeedback(null)
        createSubmittedRef.current = false
        if (wizardStep === 5) {
            setCreateForm(defaultCreateForm())
        }
    }

    async function copyToClipboardWithFeedback(value: string, label: string) {
        const ok = await copyToClipboard(value)
        setCopyFeedback(t(ok ? 'common.copyFeedback.copied' : 'common.copyFeedback.error', { label }))
        if (copyFeedbackTimeoutRef.current) window.clearTimeout(copyFeedbackTimeoutRef.current)
        copyFeedbackTimeoutRef.current = window.setTimeout(() => setCopyFeedback(null), 2000)
    }

    useEffect(() => () => {
        if (copyFeedbackTimeoutRef.current) window.clearTimeout(copyFeedbackTimeoutRef.current)
    }, [])

    function submitEdit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!editingId) return
        updateMutation.mutate({ id: editingId, payload: editForm })
    }

    function validateWizardStep(step: WizardStep, form: ZevWizardInput = createForm): string | null {
        if (step === 1) {
            if (!form.name.trim()) return t('pages.zevs.validation.zevNameRequired')
            if (!form.start_date) return t('pages.zevs.validation.startDateRequired')
        }

        if (step === 2) {
            if (!form.owner.first_name.trim()) return t('pages.zevs.validation.ownerFirstNameRequired')
            if (!form.owner.last_name.trim()) return t('pages.zevs.validation.ownerLastNameRequired')
            if (!form.owner.email.trim()) return t('pages.zevs.validation.ownerEmailRequired')
            if (form.bank_iban?.trim() && !isValidIban(form.bank_iban)) return t('pages.zevs.validation.invalidIban')
            if (form.bank_iban?.trim() && !form.owner.address_line1?.trim()) {
                return t('pages.zevs.validation.ownerAddressRequiredForIban')
            }
            if (form.bank_iban?.trim() && !form.owner.postal_code?.trim()) {
                return t('pages.zevs.validation.ownerPostalCodeRequiredForIban')
            }
            if (form.bank_iban?.trim() && !form.owner.city?.trim()) {
                return t('pages.zevs.validation.ownerCityRequiredForIban')
            }
        }

        if (step === 3) {
            if (!form.metering_points.length) return t('pages.zevs.validation.meteringPointRequired')
            const errors = Object.values(getMeteringPointErrors(form.metering_points))
            if (errors.includes('missing')) return t('pages.zevs.validation.meterIdRequired')
            if (errors.includes('duplicate')) return t('pages.zevs.validation.meterIdDuplicate')
        }

        return null
    }

    function goToNextStep() {
        const validationError = validateWizardStep(wizardStep)
        if (validationError) {
            if (wizardStep === 3) setShowMeteringPointErrors(true)
            setCreateError(validationError)
            return
        }
        setCreateError(null)
        setWizardStep((wizardStep < 4 ? wizardStep + 1 : wizardStep) as WizardStep)
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
        createMutation.mutate({
            ...createForm,
            bank_iban: normalizeIban(createForm.bank_iban ?? ''),
        })
    }

    function addMeteringPoint() {
        const key = createMeteringPointKey()
        setCreateForm((previous) => ({
            ...previous,
            metering_points: [
                ...previous.metering_points,
                { meter_id: '', meter_type: 'consumption', is_active: true, location_description: '' },
            ],
        }))
        setMeteringPointKeys((previous) => [...previous, key])
        setFocusMeteringPointKey(key)
    }

    function updateMeteringPoint(key: string, updates: Partial<OwnerMeteringPointInput>) {
        const index = meteringPointKeys.indexOf(key)
        if (index === -1) return
        setCreateForm((previous) => ({
            ...previous,
            metering_points: previous.metering_points.map((point, pointIndex) => (
                pointIndex === index ? { ...point, ...updates } : point
            )),
        }))
    }

    function removeMeteringPoint(key: string) {
        const index = meteringPointKeys.indexOf(key)
        if (index === -1 || createForm.metering_points.length <= 1) return
        setCreateForm((previous) => ({
            ...previous,
            metering_points: previous.metering_points.filter((_, pointIndex) => pointIndex !== index),
        }))
        setMeteringPointKeys((previous) => previous.filter((existingKey) => existingKey !== key))
    }

    // Move the cursor into a freshly added row so it can be typed into right away.
    useEffect(() => {
        if (!focusMeteringPointKey) return
        document.getElementById(`wizard-meter-id-${focusMeteringPointKey}`)?.focus()
        setFocusMeteringPointKey(null)
    }, [focusMeteringPointKey])

    const header = !embedded ? (
        <PageHeader
            eyebrow={t('nav.platformScope')}
            title={t('pages.zevs.title')}
            description={t('pages.zevs.description')}
        />
    ) : null

    if (isLoading)
        return (
            <div className="page-stack">
                {header}
                <PageSkeleton variant="table" />
            </div>
        )
    if (isError) return (
        <div className="page-stack">
            {header}
            <Notice tone="error" onRetry={() => void refetch()} isRetrying={isFetching}>{t('common.error')}</Notice>
        </div>
    )

    const reviewIban = createForm.bank_iban?.trim() || '–'
    const reviewBankName = createForm.bank_name?.trim()
    const reviewRecipientAddress = [
        createForm.owner.address_line1,
        createForm.owner.address_line2,
        [createForm.owner.postal_code, createForm.owner.city].filter((part) => part && part.trim()).join(' '),
    ].filter((part) => part && part.trim()).join(', ')
    const meteringPointErrors = getMeteringPointErrors(createForm.metering_points)
    const reviewBillingInterval = BILLING_INTERVAL_OPTIONS.find((option) => option.value === createForm.billing_interval)

    return (
        <div className="page-stack">
            {header}

            <div className="actions-row actions-row-gap-lg mb-1">
                {isAdmin ? (
                    <>
                        <button className="button button-primary" onClick={openCreateModal}>
                            <FontAwesomeIcon icon={faPlus} fixedWidth />
                            {t('pages.zevs.newZev')}
                        </button>
                        {/* Import lives next to "new ZEV" because that is what it
                            does: it always creates one, never updates an existing. */}
                        <button className="button button-secondary" onClick={() => setShowImportModal(true)}>
                            <FontAwesomeIcon icon={faUpload} fixedWidth />
                            {t('zevTransfer.importAction')}
                        </button>
                    </>
                ) : (
                    <p className="muted" style={{ margin: 0 }}>{t('pages.zevs.adminOnly')}</p>
                )}
            </div>

            <ZevImportModal
                isOpen={showImportModal}
                onClose={() => setShowImportModal(false)}
                onImported={() => {
                    setShowImportModal(false)
                    void queryClient.invalidateQueries({ queryKey: queryKeys.zev.list() })
                }}
            />

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
                                <input name="name" value={createForm.name} onChange={(event) => setCreateForm((previous) => ({ ...previous, name: event.target.value }))} required />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.startDate')}</span>
                                <input name="start_date" type="date" value={createForm.start_date} onChange={(event) => setCreateForm((previous) => ({ ...previous, start_date: event.target.value }))} required />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.zevType')}</span>
                                <select value={createForm.zev_type} onChange={(event) => setCreateForm((previous) => ({ ...previous, zev_type: event.target.value as ZevInput['zev_type'] }))}>
                                    {ZEV_TYPE_OPTIONS.map((option) => (
                                        <option key={option.value} value={option.value}>
                                            {t(option.labelKey)}
                                        </option>
                                    ))}
                                </select>
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.billingInterval')}</span>
                                <select value={createForm.billing_interval} onChange={(event) => setCreateForm((previous) => ({ ...previous, billing_interval: event.target.value as ZevInput['billing_interval'] }))}>
                                    {BILLING_INTERVAL_OPTIONS.map((option) => (
                                        <option key={option.value} value={option.value}>
                                            {t(option.labelKey)}
                                        </option>
                                    ))}
                                </select>
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.zevPostalCode')}</span>
                                <input
                                    value={createForm.postal_code ?? ''}
                                    onChange={(event) => setCreateForm((previous) => ({ ...previous, postal_code: event.target.value }))}
                                />
                                <small className="muted">{t('pages.zevs.form.zevPostalCodeHint')}</small>
                            </label>
                            <div className="grid-span-full">
                                <GridOperatorField
                                    label={t('pages.zevs.form.gridOperator')}
                                    value={createForm.grid_operator ?? ''}
                                    elcomId={createForm.grid_operator_elcom_id ?? null}
                                    onChange={(next) => setCreateForm((previous) => ({ ...previous, ...next }))}
                                />
                            </div>
                            {(createForm.postal_code ?? '').trim() && (
                                <div className="grid-span-full">
                                    <GridOperatorSuggestion
                                        postalCode={createForm.postal_code ?? ''}
                                        currentElcomId={createForm.grid_operator_elcom_id}
                                        currentTariffUrl={createForm.tariff_source_url}
                                        onApplyOperator={(operator) =>
                                            setCreateForm((previous) => ({
                                                ...previous,
                                                grid_operator: operator.name,
                                                grid_operator_elcom_id: operator.id,
                                            }))
                                        }
                                        onApplyTariffUrl={(url) =>
                                            setCreateForm((previous) => ({ ...previous, tariff_source_url: url }))
                                        }
                                    />
                                </div>
                            )}
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
                                    {TITLE_KEYS.map((k) => (
                                        <option key={k} value={k}>{t(`pages.zevs.titles.${k}` as Parameters<typeof t>[0])}</option>
                                    ))}
                                </select>
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.usernameOptional')}</span>
                                <input value={createForm.owner.username ?? ''} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, username: event.target.value } }))} />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.firstName')}</span>
                                <input name="first_name" value={createForm.owner.first_name} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, first_name: event.target.value } }))} required />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.lastName')}</span>
                                <input name="last_name" value={createForm.owner.last_name} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, last_name: event.target.value } }))} required />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.email')}</span>
                                <input name="email" type="email" value={createForm.owner.email} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, email: event.target.value } }))} required />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.phone')}</span>
                                <input value={createForm.owner.phone ?? ''} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, phone: event.target.value } }))} />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.addressLine1')}</span>
                                <input name="address_line1" value={createForm.owner.address_line1 ?? ''} maxLength={200} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, address_line1: event.target.value } }))} />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.addressLine2')}</span>
                                <input name="address_line2" value={createForm.owner.address_line2 ?? ''} maxLength={200} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, address_line2: event.target.value } }))} />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.postalCode')}</span>
                                <input name="postal_code" value={createForm.owner.postal_code ?? ''} maxLength={10} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, postal_code: event.target.value } }))} />
                            </label>
                            <label>
                                <span>{t('pages.zevs.form.city')}</span>
                                <input name="city" value={createForm.owner.city ?? ''} maxLength={100} onChange={(event) => setCreateForm((previous) => ({ ...previous, owner: { ...previous.owner, city: event.target.value } }))} />
                            </label>
                            <div className="grid-span-full payment-recipient-section">
                                <strong>{t('pages.zevs.form.paymentRecipientHeader')}</strong>
                                <p className="muted">{t('pages.zevs.form.paymentRecipientHint')}</p>
                                <div className="payment-fields-grid">
                                    <label>
                                        <span>{t('pages.zevs.form.bankName')}</span>
                                        <input
                                            name="bank_name"
                                            value={createForm.bank_name ?? ''}
                                            maxLength={200}
                                            onChange={(event) => setCreateForm((previous) => ({ ...previous, bank_name: event.target.value }))}
                                        />
                                    </label>
                                    <label>
                                        <span>{t('pages.zevs.form.bankIban')}</span>
                                        <input
                                            name="bank_iban"
                                            value={createForm.bank_iban ?? ''}
                                            maxLength={34}
                                            onChange={(event) => setCreateForm((previous) => ({ ...previous, bank_iban: event.target.value }))}
                                            onBlur={(event) => setCreateForm((previous) => ({ ...previous, bank_iban: normalizeIban(event.target.value) }))}
                                        />
                                    </label>
                                </div>
                                <small className="muted">{t('pages.zevs.form.bankIbanHint')}</small>
                            </div>
                        </>
                    )}

                    {wizardStep === 3 && (
                        <div className="grid-span-full page-stack">
                            <div className="card" style={{ padding: '0.85rem 1rem' }}>
                                <strong>{t('pages.zevs.wizard.step3Header')}</strong>
                                <p className="muted" style={{ margin: '0.35rem 0 0' }}>{t('pages.zevs.wizard.step3Description')}</p>
                            </div>

                            <ol className="wizard-metering-points" data-testid="wizard-metering-points">
                                {meteringPointKeys.map((key, index) => {
                                    const meteringPoint = createForm.metering_points[index]
                                    if (!meteringPoint) return null
                                    const rowError = showMeteringPointErrors ? meteringPointErrors[index] : undefined
                                    const errorId = `wizard-meter-id-${key}-error`
                                    return (
                                        <li key={key} className="wizard-metering-point" data-testid="wizard-metering-point-row">
                                            <div className="wizard-metering-point-header">
                                                <strong>{t('pages.zevs.wizard.meteringPointNumber', { number: index + 1 })}</strong>
                                                <button
                                                    className="button button-ghost button-compact"
                                                    type="button"
                                                    onClick={() => removeMeteringPoint(key)}
                                                    disabled={createForm.metering_points.length === 1}
                                                    aria-label={t('pages.zevs.wizard.removeMeteringPoint', { number: index + 1 })}
                                                    title={t('pages.zevs.wizard.removeMeteringPoint', { number: index + 1 })}
                                                >
                                                    <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                    {t('common.delete')}
                                                </button>
                                            </div>
                                            <div className="wizard-metering-point-fields">
                                                <label>
                                                    <span>{t('pages.zevs.form.meterId')}</span>
                                                    <input
                                                        id={`wizard-meter-id-${key}`}
                                                        name="meter_id"
                                                        value={meteringPoint.meter_id}
                                                        onChange={(event) => updateMeteringPoint(key, { meter_id: event.target.value })}
                                                        aria-invalid={rowError ? true : undefined}
                                                        aria-describedby={rowError ? errorId : undefined}
                                                        required
                                                    />
                                                    {rowError && (
                                                        <small className="field-error" id={errorId} role="alert">
                                                            {t(rowError === 'missing' ? 'pages.zevs.wizard.meterIdMissing' : 'pages.zevs.wizard.meterIdDuplicate')}
                                                        </small>
                                                    )}
                                                </label>
                                                <label>
                                                    <span>{t('pages.zevs.form.meterType')}</span>
                                                    <select
                                                        name="meter_type"
                                                        value={meteringPoint.meter_type}
                                                        onChange={(event) => updateMeteringPoint(key, { meter_type: event.target.value as OwnerMeteringPointInput['meter_type'] })}
                                                    >
                                                        {METER_TYPE_OPTIONS.map((option) => (
                                                            <option key={option.value} value={option.value}>
                                                                {t(option.labelKey)}
                                                            </option>
                                                        ))}
                                                    </select>
                                                </label>
                                                <label>
                                                    <span>{t('pages.zevs.form.locationDescription')}</span>
                                                    <input
                                                        name="location_description"
                                                        value={meteringPoint.location_description ?? ''}
                                                        onChange={(event) => updateMeteringPoint(key, { location_description: event.target.value })}
                                                    />
                                                </label>
                                            </div>
                                        </li>
                                    )
                                })}
                            </ol>

                            <div>
                                <button className="button button-secondary" type="button" onClick={addMeteringPoint}>
                                    <FontAwesomeIcon icon={faPlus} fixedWidth />
                                    {t('pages.zevs.wizard.addMeteringPoint')}
                                </button>
                            </div>
                        </div>
                    )}

                    {wizardStep === 4 && (
                        <div className="card grid-span-full">
                            <h3 style={{ marginTop: 0 }}>{t('pages.zevs.wizard.review')}</h3>
                            <p><strong>{t('pages.zevs.wizard.reviewZev')}</strong> {createForm.name} ({t(`pages.zevs.zevTypes.${createForm.zev_type}` as Parameters<typeof t>[0])}) · {t('pages.zevs.wizard.reviewStarting', { date: formatShortDate(createForm.start_date, settings) })}</p>
                            <p><strong>{t('pages.zevs.wizard.reviewOwner')}</strong> {createForm.owner.first_name} {createForm.owner.last_name} ({createForm.owner.email})</p>
                            <p><strong>{t('pages.zevs.wizard.reviewPaymentRecipient')}</strong> {createForm.owner.first_name} {createForm.owner.last_name}{reviewRecipientAddress ? ` · ${reviewRecipientAddress}` : ''}</p>
                            <p><strong>{t('pages.zevs.wizard.reviewBillingInterval')}</strong> {t(reviewBillingInterval?.labelKey ?? 'pages.zevs.billingIntervals.monthly')}</p>
                            <p><strong>{t('pages.zevs.wizard.reviewMeteringPoints')}</strong> {createForm.metering_points.length}</p>
                            <ul>
                                {createForm.metering_points.map((point, index) => (
                                    <li key={meteringPointKeys[index] ?? `${index}-${point.meter_id}`}>
                                        {point.meter_id} · {t(METER_TYPE_OPTIONS.find((option) => option.value === point.meter_type)?.labelKey ?? point.meter_type)}
                                    </li>
                                ))}
                            </ul>
                            <p><strong>{t('pages.zevs.wizard.reviewIban')}</strong> {reviewIban}{reviewBankName ? ` (${reviewBankName})` : ''}</p>
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
                                        onClick={() => copyToClipboardWithFeedback(createdCredentials.username, t('pages.zevs.wizard.usernameLabel'))}
                                    >
                                        <FontAwesomeIcon icon={faCopy} fixedWidth />
                                        {t('pages.zevs.wizard.copyUsername')}
                                    </button>
                                </div>

                                <p style={{ margin: '1rem 0 0.5rem' }}><strong>{t('pages.zevs.wizard.passwordLabel')}</strong></p>
                                <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                    <code>{createdCredentials.temporary_password}</code>
                                    <button
                                        className="button button-secondary"
                                        type="button"
                                        onClick={() => copyToClipboardWithFeedback(createdCredentials.temporary_password, t('pages.zevs.wizard.passwordLabel'))}
                                    >
                                        <FontAwesomeIcon icon={faCopy} fixedWidth />
                                        {t('pages.zevs.wizard.copyPassword')}
                                    </button>
                                </div>
                            </div>

                            {copyFeedback && <div className="muted">{copyFeedback}</div>}
                        </div>
                    )}

                    {createError && <div className="error-banner grid-span-full">{createError}</div>}

                    <div className="actions-row actions-row-end actions-row-gap-lg grid-span-full mt-1">
                        {wizardStep < 5 && (
                            <button className="button button-secondary" type="button" onClick={closeCreateModal}>
                                <FontAwesomeIcon icon={faXmark} fixedWidth />
                                {t('common.cancel')}
                            </button>
                        )}
                        {wizardStep > 1 && wizardStep < 5 && (
                            <button className="button button-secondary" type="button" onClick={goToPreviousStep}>
                                <FontAwesomeIcon icon={faArrowLeft} fixedWidth />
                                {t('pages.zevs.wizard.back')}
                            </button>
                        )}
                        {wizardStep < 4 && (
                            <button key="next" className="button button-primary" type="button" onClick={goToNextStep}>
                                <FontAwesomeIcon icon={faArrowRight} fixedWidth />
                                {t('pages.zevs.wizard.next')}
                            </button>
                        )}
                        {wizardStep === 4 && (
                            <button key="create" className="button button-primary" type="button" onClick={handleCreateZev} disabled={createMutation.isPending}>
                                <FontAwesomeIcon icon={faCheck} fixedWidth />
                                {createMutation.isPending ? t('pages.zevs.wizard.creating') : t('pages.zevs.wizard.createZev')}
                            </button>
                        )}
                        {wizardStep === 5 && (
                            <button key="done" className="button button-primary" type="button" onClick={closeCreateModal}>
                                <FontAwesomeIcon icon={faCheck} fixedWidth />
                                {t('pages.zevs.wizard.done')}
                            </button>
                        )}
                    </div>
                </form>
            </FormModal>

            <FormModal isOpen={showEditModal} title={t('pages.zevs.editModalTitle')} onClose={closeEditModal} maxWidth="960px">
                <form onSubmit={submitEdit} className="page-stack">
                    <section className="card page-stack">
                        <ZevGeneralSettingsFields
                            form={editForm}
                            zevId={editingId ?? undefined}
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
                        <button className="button button-secondary" type="button" onClick={closeEditModal}>
                            <FontAwesomeIcon icon={faXmark} fixedWidth />
                            {t('common.cancel')}
                        </button>
                        <button className="button button-primary" type="submit" disabled={updateMutation.isPending}>
                            <FontAwesomeIcon icon={faCheck} fixedWidth />
                            {t('pages.zevs.saveZev')}
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

            {purgeDialog && purgeTarget && (
                <ConfirmDialog
                    {...purgeDialog}
                    isLoading={purgeMutation.isPending}
                    confirmDisabled={purgeConfirmation.trim() !== purgeTarget.name.trim()}
                    onCancel={handlePurgeCancel}
                    onConfirm={handlePurgeConfirm}
                >
                    <label style={{ gridColumn: '1 / -1' }}>
                        <span>{t('pages.zevs.purgeConfirmLabel', { name: purgeTarget.name })}</span>
                        <input
                            value={purgeConfirmation}
                            onChange={(event) => {
                                purgeConfirmationRef.current = event.target.value
                                setPurgeConfirmation(event.target.value)
                            }}
                            required
                        />
                    </label>
                </ConfirmDialog>
            )}

            {!data || data.length === 0 ? (
                <EmptyState
                    titleKey="pages.zevs.emptyState.title"
                    descriptionKey="pages.zevs.emptyState.description"
                    actions={
                        isAdmin
                            ? [{ labelKey: 'pages.zevs.emptyState.createAction', onClick: openCreateModal, variant: 'primary', icon: faPlus }]
                            : []
                    }
                />
            ) : (
                <div className="table-card">
                <table>
                    <thead>
                        <tr>
                            <th>{t('pages.zevs.col.name')}</th>
                            <th>{t('pages.zevs.col.issuer')}</th>
                            <th>{t('pages.zevs.col.startDate')}</th>
                            <th>{t('pages.zevs.col.gridOperator')}</th>
                            <th>{t('pages.zevs.col.billingInterval')}</th>
                            <th>{t('pages.zevs.col.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {data.map((zev) => (
                            <tr key={zev.id}>
                                <td>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <span>{zev.name}</span>
                                        <span className="badge badge-tag">
                                            {zev.zev_type.toUpperCase()}
                                        </span>
                                        {!isValidIban(zev.bank_iban ?? '') && (
                                            <span className="badge badge-warning" title={t('pages.zevs.ibanWarningHint')}>
                                                {t('pages.zevs.ibanWarning')}
                                            </span>
                                        )}
                                        {zev.disabled_at && (
                                            <span
                                                className="badge badge-danger"
                                                title={t('pages.zevs.disabledSince', { date: formatShortDate(zev.disabled_at, settings) })}
                                            >
                                                {t('pages.zevs.disabledBadge')}
                                            </span>
                                        )}
                                    </div>
                                </td>
                                <td>{zev.issuer?.display_name ?? '–'}</td>
                                <td>{formatShortDate(zev.start_date, settings)}</td>
                                <td>{zev.grid_operator || '-'}</td>
                                <td>{t(`pages.zevs.billingIntervals.${zev.billing_interval}` as Parameters<typeof t>[0], { defaultValue: zev.billing_interval })}</td>
                                <td className="actions-cell">
                                    <div className="actions-cell-content">
                                        <button
                                            className="button button-secondary button-compact"
                                            type="button"
                                            onClick={() => {
                                                setSelectedZevId(zev.id)
                                                navigate('/')
                                            }}
                                        >
                                            <FontAwesomeIcon icon={faArrowRight} fixedWidth />
                                            {t('pages.zevs.manage')}
                                        </button>
                                        <button className="button button-primary button-compact" type="button" onClick={() => startEdit(zev)}>
                                            <FontAwesomeIcon icon={faPen} fixedWidth />
                                            {t('common.edit')}
                                        </button>
                                        {zev.disabled_at && (
                                            <button
                                                className="button button-secondary button-compact"
                                                type="button"
                                                disabled={enableMutation.isPending || dialogLoading}
                                                onClick={() => confirm({
                                                    title: t('pages.zevs.enableTitle'),
                                                    message: t('pages.zevs.enableMessage', { name: zev.name }),
                                                    confirmText: t('pages.zevs.enableConfirm'),
                                                    onConfirm: () => consumeReportedError(enableMutation.mutateAsync(zev.id)),
                                                })}
                                            >
                                                <FontAwesomeIcon icon={faPlay} fixedWidth />
                                                {t('pages.zevs.enable')}
                                            </button>
                                        )}
                                        {zev.disabled_at && (
                                            <button
                                                className="button button-danger button-compact"
                                                type="button"
                                                disabled={purgeMutation.isPending}
                                                onClick={() => openPurgeDialog(zev)}
                                            >
                                                <FontAwesomeIcon icon={faSkullCrossbones} fixedWidth />
                                                {t('pages.zevs.purge')}
                                            </button>
                                        )}
                                        {!zev.disabled_at && (
                                            <button
                                                className="button button-secondary button-compact"
                                                type="button"
                                                disabled={disableMutation.isPending || dialogLoading}
                                                onClick={() => confirm({
                                                    title: t('pages.zevs.disableTitle'),
                                                    message: t('pages.zevs.disableMessage', { name: zev.name }),
                                                    confirmText: t('pages.zevs.disableConfirm'),
                                                    isDangerous: true,
                                                    onConfirm: () => consumeReportedError(disableMutation.mutateAsync(zev.id)),
                                                })}
                                            >
                                                <FontAwesomeIcon icon={faBan} fixedWidth />
                                                {t('pages.zevs.disable')}
                                            </button>
                                        )}
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                </div>
            )}
        </div>
    )
}
