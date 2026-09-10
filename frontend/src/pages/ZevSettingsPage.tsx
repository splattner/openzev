import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload } from '@fortawesome/free-solid-svg-icons'
import { Tabs } from '@mantine/core'
import { useNavigate, useParams } from 'react-router-dom'
import { PageSkeleton } from '../components/PageSkeleton'
import { ZevEmailTemplateFields } from '../components/ZevEmailTemplateFields'
import { ZevGeneralSettingsFields } from '../components/ZevGeneralSettingsFields'
import { ZevExportModal } from '../features/zev/ZevExportModal'
import { updateZev } from '../lib/api/zev'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { useManagedZev } from '../lib/managedZev'
import { getDefaultZevForm, mapZevToForm } from '../lib/zevForm'
import { useToast } from '../lib/toast'
import { AuditLogsPage } from './AdminAuditLogsPage'
import { NotFoundPage } from './NotFoundPage'
import type { ZevInput } from '../types/api'

/**
 * ZEV settings hub (nav-regroup phase 3, spec §5): tabs General · Billing &
 * payment · Documents & emails · Audit log · Export/transfer. One form state
 * feeds every tab's fields (a save on any tab persists the whole form — the
 * backend takes one PATCH); the audit-log tab reuses the owner-scoped
 * AuditLogsPage component, and export/transfer keeps the danger-zone-like
 * separation at the bottom of its own tab.
 */

export type ZevSettingsTab = 'general' | 'billing' | 'documents' | 'audit' | 'export'

const TABS: ZevSettingsTab[] = ['general', 'billing', 'documents', 'audit', 'export']

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
    const { selectedZev, selectedZevId, isLoading } = useManagedZev()

    const [form, setForm] = useState<ZevInput>(getDefaultZevForm())
    const [error, setError] = useState<string | null>(null)
    const [showExportModal, setShowExportModal] = useState(false)

    useEffect(() => {
        if (!selectedZev) {
            setForm(getDefaultZevForm())
            return
        }

        setForm(mapZevToForm(selectedZev))
    }, [selectedZev])

    const updateMutation = useMutation({
        mutationFn: (payload: ZevInput) => updateZev(selectedZevId, payload),
        onSuccess: () => {
            setError(null)
            pushToast(t('pages.zevSettings.updateSuccess'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.list() })
            void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.readiness(selectedZevId) })
            void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.readinessList(selectedZevId) })
        },
        onError: (mutationError) =>
            setError(formatApiError(mutationError, t('pages.zevSettings.updateFailed'))),
    })

    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!selectedZevId) {
            return
        }
        updateMutation.mutate(form)
    }

    function handleTabChange(value: string | null) {
        navigate(`/zev-settings/${value ?? 'general'}`, { replace: true })
    }

    if (isLoading) {
        return <PageSkeleton variant="page" />
    }

    if (!selectedZevId || !selectedZev) {
        return <div className="card">{t('pages.zevSettings.selectZev')}</div>
    }

    return (
        <div className="page-stack">
            <header>
                {selectedZev?.name ? <p className="eyebrow">{selectedZev.name}</p> : null}
                <h2>{t('pages.zevSettings.title')}</h2>
                <p className="muted">{t('pages.zevSettings.description')}</p>
            </header>

            <Tabs
                classNames={{ root: 'app-tabs', list: 'app-tabs-list', tab: 'app-tabs-tab' }}
                value={tab}
                keepMounted={false}
                onChange={handleTabChange}
            >
                <Tabs.List aria-label={t('pages.zevSettings.title')}>
                    <Tabs.Tab value="general">{t('pages.zevSettings.tabs.general')}</Tabs.Tab>
                    <Tabs.Tab value="billing">{t('pages.zevSettings.tabs.billingPayment')}</Tabs.Tab>
                    <Tabs.Tab value="documents">{t('pages.zevSettings.tabs.documentsEmails')}</Tabs.Tab>
                    <Tabs.Tab value="audit">{t('pages.zevSettings.tabs.auditLog')}</Tabs.Tab>
                    <Tabs.Tab value="export">{t('pages.zevSettings.tabs.exportTransfer')}</Tabs.Tab>
                </Tabs.List>

                <Tabs.Panel value="general">
                    <section className="card page-stack">
                        <form className="page-stack" onSubmit={submit}>
                            <ZevGeneralSettingsFields
                                form={form}
                                group="general"
                                onChange={(patch) => setForm((previous) => ({ ...previous, ...patch }))}
                            />

                            {error && <div className="error-banner grid-span-full">{error}</div>}

                            <div className="actions-row grid-span-full">
                                <button className="button button-primary" type="submit" disabled={updateMutation.isPending}>
                                    {t('pages.zevSettings.saveSettings')}
                                </button>
                            </div>
                        </form>
                    </section>
                </Tabs.Panel>

                <Tabs.Panel value="billing">
                    <section className="card page-stack">
                        <form className="page-stack" onSubmit={submit}>
                            <ZevGeneralSettingsFields
                                form={form}
                                group="billing"
                                onChange={(patch) => setForm((previous) => ({ ...previous, ...patch }))}
                            />

                            {error && <div className="error-banner grid-span-full">{error}</div>}

                            <div className="actions-row grid-span-full">
                                <button className="button button-primary" type="submit" disabled={updateMutation.isPending}>
                                    {t('pages.zevSettings.saveSettings')}
                                </button>
                            </div>
                        </form>
                    </section>
                </Tabs.Panel>

                <Tabs.Panel value="documents">
                    <section className="card page-stack">
                        <form className="inline-form page-stack" onSubmit={submit}>
                            <ZevEmailTemplateFields
                                subjectTemplate={form.email_subject_template ?? ''}
                                bodyTemplate={form.email_body_template ?? ''}
                                onSubjectTemplateChange={(value) =>
                                    setForm((previous) => ({ ...previous, email_subject_template: value }))
                                }
                                onBodyTemplateChange={(value) =>
                                    setForm((previous) => ({ ...previous, email_body_template: value }))
                                }
                            />

                            <ZevGeneralSettingsFields
                                form={form}
                                group="documents"
                                onChange={(patch) => setForm((previous) => ({ ...previous, ...patch }))}
                            />

                            {error && <div className="error-banner">{error}</div>}

                            <div className="actions-row">
                                <button className="button button-primary" type="submit" disabled={updateMutation.isPending}>
                                    {t('pages.zevSettings.saveEmailTemplate')}
                                </button>
                            </div>
                        </form>
                    </section>
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
                </Tabs.Panel>
            </Tabs>

            <ZevExportModal
                isOpen={showExportModal}
                zevId={selectedZevId}
                zevName={selectedZev.name}
                onClose={() => setShowExportModal(false)}
            />
        </div>
    )
}
