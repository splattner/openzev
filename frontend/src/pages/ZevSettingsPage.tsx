import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faBan, faDownload, faPlay, faTriangleExclamation } from '@fortawesome/free-solid-svg-icons'
import { Tabs } from '@mantine/core'
import { useBlocker, useNavigate, useParams } from 'react-router-dom'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { PageSkeleton } from '../components/PageSkeleton'
import { ZevEmailTemplateFields } from '../components/ZevEmailTemplateFields'
import { ZevGeneralSettingsFields } from '../components/ZevGeneralSettingsFields'
import { ZevExportModal } from '../features/zev/ZevExportModal'
import { apiErrorPayload, formatApiError } from '../lib/api/errors'
import { disableZev, enableZev, updateZev } from '../lib/api/zev'
import { queryKeys } from '../lib/api/queryKeys'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useCommunityAccess } from '../lib/communityAccess'
import { ZevAccessSection } from '../features/zev/ZevAccessSection'
import { ZevPartiesSection } from '../features/zev/ZevPartiesSection'
import {
    ZEV_FIELD_TABS,
    focusZevField,
    getDefaultZevForm,
    isZevFormDirty,
    mapZevToForm,
    parseZevFieldErrors,
    validateZevForm,
    type ZevSettingsTab,
} from '../lib/zevForm'
import { setZevUnsavedDraftGuard } from '../lib/zevUnsavedGuard'
import { useToast } from '../lib/toast'
import { AuditLogsPage } from './AdminAuditLogsPage'
import { NotFoundPage } from './NotFoundPage'
import type { Zev, ZevInput } from '../types/api'

/**
 * ZEV settings hub (nav-regroup phase 3, spec §5): one draft feeds the three
 * editing tabs and a single sticky save bar persists the whole form (one PATCH).
 */

const TABS: ZevSettingsTab[] = ['general', 'parties', 'billing', 'documents', 'access', 'audit', 'export']
// Tabs that save on their own: the sticky bar saves the draft without submitting a form there.
const OUTSIDE_THE_FORM = new Set<ZevSettingsTab>(['parties', 'access', 'audit', 'export'])

type ZevDraft = {
    zevId: string | null
    epoch: number
    form: ZevInput
    baseline: ZevInput
}

/** Focus a draft field, including the controls for hidden dependent values. */
function focusDraftField(field: string) {
    if (focusZevField(field)) {
        return
    }
    if (field === 'vat_number') {
        focusZevField('vat_mode')
    }
    if (field === 'grid_operator_elcom_id') {
        focusZevField('grid_operator')
    }
}

/** /zev-settings/:tab — renders the hub with the routed tab (404s unknown). */
export function ZevSettingsTabRoute() {
    const { tab = 'general' } = useParams<{ tab: string }>()
    const active = TABS.includes(tab as ZevSettingsTab) ? (tab as ZevSettingsTab) : null
    if (!active) {
        return <NotFoundPage />
    }
    return <ZevSettingsPage tab={active} />
}

export function ZevSettingsPage({ tab = 'general' }: { tab?: ZevSettingsTab }) {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { selectedZev, selectedZevId, isLoading } = useManagedZev()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const [draft, setDraft] = useState<ZevDraft>(() => {
        const initial = getDefaultZevForm()
        return { zevId: null, epoch: 0, form: initial, baseline: initial }
    })
    const { form, baseline } = draft
    const [emailEditorRevision, setEmailEditorRevision] = useState(0)
    const [error, setError] = useState<string | null>(null)
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
    const [showExportModal, setShowExportModal] = useState(false)

    const isAdmin = user?.role === 'admin'
    const isDisabled = Boolean(selectedZev?.disabled_at)
    const { canManage } = useCommunityAccess()
    // A manager keeps read access to a disabled ZEV but loses write access
    // (backend: BaseZevScopedPermission.has_object_permission) — an admin
    // can still edit. A viewer never writes (#761). Mirrored here across every
    // control; the backend enforces it regardless.
    const disabledForMe = isDisabled && !isAdmin
    const readOnly = disabledForMe || !canManage

    const selectedZevIdRef = useRef(selectedZevId)
    const draftRef = useRef(draft)
    const pendingFocusRef = useRef<keyof typeof ZEV_FIELD_TABS | null>(null)
    const acceptedSaveRef = useRef(new Map<string, { updatedAt: string; form: ZevInput }>())
    useLayoutEffect(() => {
        selectedZevIdRef.current = selectedZevId
    }, [selectedZevId])
    useLayoutEffect(() => {
        draftRef.current = draft
    }, [draft])

    const draftIsSelected = draft.zevId === selectedZevId && selectedZev?.id === selectedZevId
    const isDirty = draftIsSelected && isZevFormDirty(draft.form, draft.baseline)
    const leaveBlocker = useBlocker(({ nextLocation }) =>
        isDirty && !/^\/zev-settings(?:\/|$)/.test(nextLocation.pathname),
    )

    useEffect(() => {
        if (!selectedZev || selectedZev.id !== selectedZevId) {
            return
        }
        const incoming = mapZevToForm(selectedZev)
        const accepted = acceptedSaveRef.current.get(selectedZevId)
        const isStale = Boolean(accepted && selectedZev.updated_at
            && Date.parse(selectedZev.updated_at) <= Date.parse(accepted.updatedAt)
            && isZevFormDirty(incoming, accepted.form))
        const target = isStale ? accepted!.form : incoming
        if (draft.zevId !== selectedZevId) {
            pendingFocusRef.current = null
            setError(null)
            setFieldErrors({})
            setDraft((previous) => ({ zevId: selectedZevId, epoch: previous.epoch + 1, form: target, baseline: target }))
            return
        }
        if (isDirty) {
            return
        }
        setDraft((previous) => previous.zevId === selectedZevId
            && !isZevFormDirty(previous.form, previous.baseline)
            && isZevFormDirty(previous.baseline, target)
            ? { ...previous, form: target, baseline: target }
            : previous)
    }, [selectedZev, selectedZevId, draft.zevId, isDirty])

    // Publish dirty state for the community switcher in Layout, which lives
    // outside this page and must confirm before dropping the draft.
    useEffect(() => {
        setZevUnsavedDraftGuard(isDirty)
        return () => setZevUnsavedDraftGuard(false)
    }, [isDirty])

    // Browser reload and close use the native prompt; the community switcher
    // separately confirms before changing the selected ZEV.
    useEffect(() => {
        if (!isDirty) {
            return
        }
        const onBeforeUnload = (event: BeforeUnloadEvent) => {
            event.preventDefault()
        }
        window.addEventListener('beforeunload', onBeforeUnload)
        return () => window.removeEventListener('beforeunload', onBeforeUnload)
    }, [isDirty])

    const updateMutation = useMutation({
        mutationFn: ({ id, payload }: { id: string; payload: ZevInput; epoch: number }) => updateZev(id, payload),
        onSuccess: (saved: Zev, variables) => {
            const accepted = acceptedSaveRef.current.get(variables.id)
            const isOlder = Boolean(accepted && saved.updated_at
                && Date.parse(saved.updated_at) < Date.parse(accepted.updatedAt))
            if (!isOlder) {
                const mapped = mapZevToForm(saved)
                if (saved.updated_at) {
                    acceptedSaveRef.current.set(variables.id, { updatedAt: saved.updated_at, form: mapped })
                }
                queryClient.setQueryData<Zev[]>(queryKeys.zev.list(), (previous) =>
                    previous?.map((zev) => (zev.id === variables.id ? saved : zev)) ?? previous,
                )
            }
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.list() })
            void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.readiness(variables.id) })
            void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.readinessList(variables.id) })
            if (isOlder || variables.id !== selectedZevIdRef.current
                || draftRef.current.epoch !== variables.epoch) {
                return
            }
            const mapped = mapZevToForm(saved)
            setDraft((previous) => previous.zevId === variables.id && previous.epoch === variables.epoch
                ? { ...previous, form: mapped, baseline: mapped }
                : previous)
            setEmailEditorRevision((previous) => previous + 1)
            pendingFocusRef.current = null
            setError(null)
            setFieldErrors({})
            pushToast(t('pages.zevSettings.updateSuccess'), 'success')
        },
        onError: (mutationError, variables) => {
            if (variables.id !== selectedZevIdRef.current
                || draftRef.current.epoch !== variables.epoch) {
                return
            }
            setError(formatApiError(mutationError, t('pages.zevSettings.updateFailed')))
            // Route server-side field errors to their tab and focus the first.
            const parsed = parseZevFieldErrors(apiErrorPayload(mutationError))
            if (parsed.length > 0) {
                setFieldErrors(Object.fromEntries(parsed.map(({ field, message }) => [field, message])))
                const first = parsed[0].field
                const targetTab = ZEV_FIELD_TABS[first]
                pendingFocusRef.current = first
                if (targetTab !== tab) {
                    navigate(`/zev-settings/${targetTab}`, { replace: true })
                }
            }
        },
    })

    const isPending = updateMutation.isPending
        && updateMutation.variables?.id === selectedZevId
        && updateMutation.variables.epoch === draft.epoch
    // A pending save freezes the draft; success would otherwise drop edits.
    const controlsReadOnly = readOnly || isPending
    // The bar stays mounted while an error shows so a failed save keeps its
    // retry action next to the message on every tab.
    const showSaveBar = isDirty || isPending || error !== null

    useEffect(() => {
        if (!isDirty && error !== null) {
            setError(null)
            setFieldErrors({})
        }
    }, [isDirty, error])

    // Errors and navigation must render, and the save must release disabled
    // controls, before focus can reach the invalid editor.
    useEffect(() => {
        const field = pendingFocusRef.current
        if (!field || !draftIsSelected || controlsReadOnly || ZEV_FIELD_TABS[field] !== tab) {
            return
        }
        pendingFocusRef.current = null
        focusDraftField(field)
    }, [tab, controlsReadOnly, draftIsSelected, fieldErrors])

    const disableMutation = useMutation({
        mutationFn: () => disableZev(selectedZevId),
        onSuccess: () => {
            pushToast(t('pages.zevSettings.lifecycle.disableSuccess'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.list() })
        },
        onError: (mutationError) =>
            pushToast(formatApiError(mutationError, t('pages.zevSettings.lifecycle.disableFailed')), 'error'),
    })

    const enableMutation = useMutation({
        mutationFn: () => enableZev(selectedZevId),
        onSuccess: () => {
            pushToast(t('pages.zevSettings.lifecycle.enableSuccess'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.list() })
        },
        onError: (mutationError) =>
            pushToast(formatApiError(mutationError, t('pages.zevSettings.lifecycle.enableFailed')), 'error'),
    })

    /** Validate the whole draft, jump to the first invalid field, else save. */
    function attemptSave() {
        if (!selectedZevId || !draftIsSelected || readOnly || isPending) {
            return
        }
        if (!isZevFormDirty(form, baseline)) {
            return
        }
        const violations = validateZevForm(form)
        if (violations.length > 0) {
            setFieldErrors(Object.fromEntries(
                violations.map(({ field, messageKey }) => [field, t(`pages.zevSettings.validation.${messageKey}`)]),
            ))
            const first = violations[0].field
            const targetTab = ZEV_FIELD_TABS[first]
            pendingFocusRef.current = first
            if (targetTab !== tab) {
                navigate(`/zev-settings/${targetTab}`, { replace: true })
            }
            return
        }
        updateMutation.mutate({ id: selectedZevId, payload: form, epoch: draft.epoch })
    }

    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        attemptSave()
    }

    function discard() {
        pendingFocusRef.current = null
        setDraft((previous) => ({ ...previous, form: previous.baseline }))
        setEmailEditorRevision((previous) => previous + 1)
        setError(null)
        setFieldErrors({})
    }

    function handleTabChange(value: string | null) {
        navigate(`/zev-settings/${value ?? 'general'}`, { replace: true })
    }

    function updateForm(patch: Partial<ZevInput>) {
        if (controlsReadOnly || !draftIsSelected) {
            return
        }
        setDraft((previous) => previous.zevId === selectedZevId
            ? { ...previous, form: { ...previous.form, ...patch } }
            : previous)
        // A field edited after a failed validation revalidates on next save;
        // drop its stale message immediately so it doesn't linger.
        const changed = Object.keys(patch)
        setFieldErrors((previous) => {
            if (!changed.some((key) => previous[key] !== undefined)) {
                return previous
            }
            const next = { ...previous }
            for (const key of changed) {
                delete next[key]
            }
            return next
        })
    }

    if (isLoading) {
        return <PageSkeleton variant="page" />
    }

    if (!selectedZevId || !selectedZev) {
        return <div className="card">{t('pages.zevSettings.selectZev')}</div>
    }

    if (!draftIsSelected) {
        return <PageSkeleton variant="page" />
    }

    return (
        <div className="page-stack zev-settings-page">
            <header>
                {selectedZev?.name ? <p className="eyebrow">{selectedZev.name}</p> : null}
                <h2>{t('pages.zevSettings.title')}</h2>
                <p className="muted">{t('pages.zevSettings.description')}</p>
            </header>

            {isDisabled && (
                <div className="warning-banner" role="alert" style={{ display: 'grid', gap: '0.35rem', maxWidth: '1000px' }}>
                    <strong>
                        <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth style={{ marginRight: '0.4rem' }} />
                        {t('pages.zevSettings.lifecycle.bannerTitle')}
                    </strong>
                    <p style={{ margin: 0 }}>
                        {t('pages.zevSettings.lifecycle.bannerBody', {
                            date: selectedZev?.disabled_at ? formatShortDate(selectedZev.disabled_at, settings) : '',
                        })}
                        {selectedZev?.disabled_reason ? ` ${t('pages.zevSettings.lifecycle.bannerReason', { reason: selectedZev.disabled_reason })}` : ''}
                        {' '}
                        {isAdmin ? t('pages.zevSettings.lifecycle.bannerAdminHint') : t('pages.zevSettings.lifecycle.bannerReadOnly')}
                    </p>
                    {isAdmin && (
                        <div className="actions-row" style={{ marginTop: '0.15rem' }}>
                            <button
                                className="button button-secondary button-compact"
                                type="button"
                                disabled={enableMutation.isPending}
                                onClick={() => enableMutation.mutate()}
                            >
                                <FontAwesomeIcon icon={faPlay} fixedWidth />
                                {t('pages.zevSettings.lifecycle.enableAction')}
                            </button>
                        </div>
                    )}
                </div>
            )}

            <Tabs
                classNames={{ root: 'app-tabs', list: 'app-tabs-list', tab: 'app-tabs-tab' }}
                value={tab}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <Tabs.List aria-label={t('pages.zevSettings.title')}>
                    <Tabs.Tab value="general">{t('pages.zevSettings.tabs.general')}</Tabs.Tab>
                    <Tabs.Tab value="parties">{t('pages.zevSettings.tabs.parties')}</Tabs.Tab>
                    <Tabs.Tab value="billing">{t('pages.zevSettings.tabs.billingPayment')}</Tabs.Tab>
                    <Tabs.Tab value="documents">{t('pages.zevSettings.tabs.documentsEmails')}</Tabs.Tab>
                    <Tabs.Tab value="access">{t('pages.zevSettings.tabs.access')}</Tabs.Tab>
                    <Tabs.Tab value="audit">{t('pages.zevSettings.tabs.auditLog')}</Tabs.Tab>
                    <Tabs.Tab value="export">{t('pages.zevSettings.tabs.exportTransfer')}</Tabs.Tab>
                </Tabs.List>

                <Tabs.Panel value="general">
                    <section className="card page-stack">
                        <form id="zev-settings-form" className="page-stack" noValidate onSubmit={submit}>
                            <ZevGeneralSettingsFields
                                form={form}
                                group="general"
                                zevId={selectedZevId}
                                readOnly={controlsReadOnly}
                                fieldErrors={fieldErrors}
                                onChange={updateForm}
                            />
                        </form>
                    </section>
                </Tabs.Panel>

                <Tabs.Panel value="billing">
                    <section className="card page-stack">
                        <form id="zev-settings-form" className="page-stack" noValidate onSubmit={submit}>
                            <ZevGeneralSettingsFields
                                form={form}
                                group="billing"
                                zevId={selectedZevId}
                                readOnly={controlsReadOnly}
                                fieldErrors={fieldErrors}
                                onChange={updateForm}
                            />
                        </form>
                    </section>
                </Tabs.Panel>

                <Tabs.Panel value="documents">
                    <section className="card page-stack">
                        <form id="zev-settings-form" className="inline-form page-stack" noValidate onSubmit={submit}>
                            <ZevEmailTemplateFields
                                key={`${selectedZevId}:${draft.epoch}`}
                                subjectTemplate={form.email_subject_template ?? ''}
                                bodyTemplate={form.email_body_template ?? ''}
                                savedSubjectTemplate={baseline.email_subject_template ?? ''}
                                savedBodyTemplate={baseline.email_body_template ?? ''}
                                resetRevision={emailEditorRevision}
                                fieldErrors={fieldErrors}
                                readOnly={controlsReadOnly}
                                onSubjectTemplateChange={(value) =>
                                    updateForm({ email_subject_template: value })
                                }
                                onBodyTemplateChange={(value) =>
                                    updateForm({ email_body_template: value })
                                }
                            />

                            <ZevGeneralSettingsFields
                                form={form}
                                group="documents"
                                zevId={selectedZevId}
                                readOnly={controlsReadOnly}
                                fieldErrors={fieldErrors}
                                onChange={updateForm}
                            />
                        </form>
                    </section>
                </Tabs.Panel>

                <Tabs.Panel value="parties">
                    <ZevPartiesSection zevId={selectedZevId} canManage={canManage && !disabledForMe} />
                </Tabs.Panel>

                <Tabs.Panel value="access">
                    <ZevAccessSection zevId={selectedZevId} canManage={canManage && !disabledForMe} />
                </Tabs.Panel>

                <Tabs.Panel value="audit">
                    {/* Owner-scoped audit log as a tab of its ZEV (spec §5): the
                        component locks scope to 'owner' — the platform log never
                        merges here. */}
                    <AuditLogsPage scope="owner" embedded />
                </Tabs.Panel>

                <Tabs.Panel value="export">
                    <section className="card page-stack">
                        <div>
                            <h3 style={{ marginTop: 0 }}>{t('zevTransfer.exportTitle')}</h3>
                            <p className="muted" style={{ margin: 0 }}>
                                {t('zevTransfer.exportSectionDescription')}
                            </p>
                        </div>
                        <div className="actions-row">
                            <button
                                className="button button-secondary"
                                type="button"
                                onClick={() => setShowExportModal(true)}
                            >
                                <FontAwesomeIcon icon={faDownload} fixedWidth />
                                {t('zevTransfer.exportAction')}
                            </button>
                        </div>
                    </section>

                    {!isDisabled && canManage && (
                        <section className="card page-stack">
                            <div>
                                <h3 style={{ marginTop: 0 }}>{t('pages.zevSettings.lifecycle.disableSectionTitle')}</h3>
                                <p className="muted" style={{ margin: 0 }}>
                                    {t('pages.zevSettings.lifecycle.disableSectionDescription')}
                                </p>
                            </div>
                            <div className="actions-row">
                                <button
                                    className="button button-danger"
                                    type="button"
                                    disabled={disableMutation.isPending || dialogLoading}
                                    onClick={() => confirm({
                                        title: t('pages.zevSettings.lifecycle.disableTitle'),
                                        message: t('pages.zevSettings.lifecycle.disableMessage', { name: selectedZev.name }),
                                        confirmText: t('pages.zevSettings.lifecycle.disableConfirm'),
                                        isDangerous: true,
                                        onConfirm: () => disableMutation.mutate(),
                                    })}
                                >
                                    <FontAwesomeIcon icon={faBan} fixedWidth />
                                    {t('pages.zevSettings.lifecycle.disableAction')}
                                </button>
                            </div>
                        </section>
                    )}
                </Tabs.Panel>
            </Tabs>

            {showSaveBar && (
                <div className="zev-settings-save-bar" role="region" aria-label={t('pages.zevSettings.saveBarLabel')}>
                    <span className="zev-settings-save-bar-text" role="status">
                        {isPending
                            ? t('pages.zevSettings.saving')
                            : t('pages.zevSettings.unsavedChanges')}
                    </span>
                    <div className="actions-row actions-row-wrap">
                        <button
                            className="button button-secondary"
                            type="button"
                            disabled={isPending}
                            onClick={discard}
                        >
                            {t('pages.zevSettings.discardChanges')}
                        </button>
                        <button
                            className="button button-primary"
                            type={OUTSIDE_THE_FORM.has(tab) ? 'button' : 'submit'}
                            form={OUTSIDE_THE_FORM.has(tab) ? undefined : 'zev-settings-form'}
                            disabled={readOnly || isPending || !isDirty}
                            onClick={OUTSIDE_THE_FORM.has(tab) ? attemptSave : undefined}
                        >
                            {t('pages.zevSettings.saveChanges')}
                        </button>
                    </div>
                    {error && <div className="error-banner zev-settings-save-bar-error" role="alert">{error}</div>}
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

            {leaveBlocker.state === 'blocked' && (
                <ConfirmDialog
                    title={t('pages.zevSettings.unsavedGuardTitle')}
                    message={t('pages.zevSettings.unsavedGuardLeaveMessage')}
                    confirmText={t('pages.zevSettings.leaveWithoutSaving')}
                    onConfirm={() => leaveBlocker.proceed()}
                    onCancel={() => leaveBlocker.reset()}
                />
            )}

            <ZevExportModal
                isOpen={showExportModal}
                zevId={selectedZevId}
                zevName={selectedZev.name}
                onClose={() => setShowExportModal(false)}
            />
        </div>
    )
}
