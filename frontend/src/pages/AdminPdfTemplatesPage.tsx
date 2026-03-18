import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchInvoicePdfTemplate, updateInvoicePdfTemplate } from '../lib/api'
import { useToast } from '../lib/toast'

export function AdminPdfTemplatesPage() {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const templateQuery = useQuery({
        queryKey: ['admin-pdf-template'],
        queryFn: fetchInvoicePdfTemplate,
    })
    const [content, setContent] = useState('')

    useEffect(() => {
        if (templateQuery.data?.content != null) {
            setContent(templateQuery.data.content)
        }
    }, [templateQuery.data])

    const saveMutation = useMutation({
        mutationFn: updateInvoicePdfTemplate,
        onSuccess: (result) => {
            pushToast(result.detail ?? t('common.save'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['admin-pdf-template'] })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    if (templateQuery.isLoading) {
        return <div className="card">{t('common.loading')}</div>
    }

    if (templateQuery.isError || !templateQuery.data) {
        return <div className="card error-banner">{t('common.error')}</div>
    }

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('nav.adminConsole')}</p>
                <h2>{t('admin.pdfTemplates')}</h2>
                <p className="muted">
                    {t('admin.pdfTemplatesDescription')}
                </p>
            </header>

            <section className="card page-stack">
                <div>
                    <strong>{templateQuery.data.template_name}</strong>
                </div>
                <label>
                    <span>{t('admin.templateContent')}</span>
                    <textarea
                        value={content}
                        onChange={(event) => setContent(event.target.value)}
                        rows={24}
                        className="template-editor"
                        spellCheck={false}
                    />
                </label>
                <div className="actions-row">
                    <button
                        className="button"
                        type="button"
                        disabled={saveMutation.isPending}
                        onClick={() => saveMutation.mutate(content)}
                    >
                        {saveMutation.isPending ? t('common.saving') : t('common.save')}
                    </button>
                </div>
            </section>
        </div>
    )
}
