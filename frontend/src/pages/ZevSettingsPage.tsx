import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload } from '@fortawesome/free-solid-svg-icons'
import { ZevEmailTemplateFields } from '../components/ZevEmailTemplateFields'
import { ZevGeneralSettingsFields } from '../components/ZevGeneralSettingsFields'
import { ZevExportModal } from '../features/zev/ZevExportModal'
import { updateZev } from '../lib/api/zev'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { useManagedZev } from '../lib/managedZev'
import { getDefaultZevForm, mapZevToForm } from '../lib/zevForm'
import { useToast } from '../lib/toast'
import type { ZevInput } from '../types/api'

export function ZevSettingsPage() {
    const { t } = useTranslation()
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

    if (isLoading) {
        return <div className="card">{t('pages.zevSettings.loading')}</div>
    }

    if (!selectedZevId || !selectedZev) {
        return <div className="card">{t('pages.zevSettings.selectZev')}</div>
    }

    return (
        <div className="page-stack">
            <header>
                <h2>{t('pages.zevSettings.title')}</h2>
                <p className="muted">{t('pages.zevSettings.description')}</p>
            </header>

            <section className="card page-stack">
                <form className="page-stack" onSubmit={submit}>
                    <ZevGeneralSettingsFields
                        form={form}
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

                    {error && <div className="error-banner">{error}</div>}

                    <div className="actions-row">
                        <button className="button button-primary" type="submit" disabled={updateMutation.isPending}>
                            {t('pages.zevSettings.saveEmailTemplate')}
                        </button>
                    </div>
                </form>
            </section>

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

            <ZevExportModal
                isOpen={showExportModal}
                zevId={selectedZevId}
                zevName={selectedZev.name}
                onClose={() => setShowExportModal(false)}
            />
        </div>
    )
}
