import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchEmailTemplate } from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'

type ZevEmailTemplateFieldsProps = {
    subjectTemplate: string
    bodyTemplate: string
    onSubjectTemplateChange: (value: string) => void
    onBodyTemplateChange: (value: string) => void
    showHeader?: boolean
}

const TEMPLATE_VARIABLES: { variable: string; descriptionKey: string }[] = [
    { variable: '{participant_name}', descriptionKey: 'admin.emailTemplates.fields.participantName' },
    { variable: '{invoice_number}', descriptionKey: 'admin.emailTemplates.fields.invoiceNumber' },
    { variable: '{period_start}', descriptionKey: 'admin.emailTemplates.fields.periodStart' },
    { variable: '{period_end}', descriptionKey: 'admin.emailTemplates.fields.periodEnd' },
    { variable: '{due_date}', descriptionKey: 'admin.emailTemplates.fields.dueDate' },
    { variable: '{total_chf}', descriptionKey: 'admin.emailTemplates.fields.totalChf' },
    { variable: '{zev_name}', descriptionKey: 'admin.emailTemplates.fields.zevName' },
]

export function ZevEmailTemplateFields({
    subjectTemplate,
    bodyTemplate,
    onSubjectTemplateChange,
    onBodyTemplateChange,
    showHeader = true,
}: ZevEmailTemplateFieldsProps) {
    const { t } = useTranslation()

    const globalTemplateQuery = useQuery({
        queryKey: queryKeys.admin.emailTemplate('invoice_email'),
        queryFn: () => fetchEmailTemplate('invoice_email'),
    })

    const globalSubject = globalTemplateQuery.data?.subject ?? ''
    const globalBody = globalTemplateQuery.data?.body ?? ''

    return (
        <>
            {showHeader && (
                <header>
                    <h3>{t('pages.zevSettings.emailTemplateTitle')}</h3>
                    <p className="muted">
                        {t('pages.zevSettings.emailTemplateDescription')}
                    </p>
                </header>
            )}

            <div className="inline-form page-stack">
                <label>
                    <span>{t('admin.emailTemplates.subject')}</span>
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        <input
                            style={{ flex: 1 }}
                            value={subjectTemplate}
                            placeholder={globalSubject}
                            onChange={(event) => onSubjectTemplateChange(event.target.value)}
                        />
                        {/* Empty field = already at the global default, so
                            the reset action is meaningless and stays hidden. */}
                        {subjectTemplate !== '' && (
                            <button
                                type="button"
                                className="button button-secondary"
                                onClick={() => onSubjectTemplateChange('')}
                                title={t('pages.zevSettings.resetToGlobalDefault')}
                            >
                                {t('admin.resetToDefault')}
                            </button>
                        )}
                    </div>
                </label>

                <label>
                    <span>{t('admin.emailTemplates.body')}</span>
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start' }}>
                        <textarea
                            style={{ flex: 1 }}
                            rows={10}
                            value={bodyTemplate}
                            placeholder={globalBody}
                            onChange={(event) => onBodyTemplateChange(event.target.value)}
                        />
                        {bodyTemplate !== '' && (
                            <button
                                type="button"
                                className="button button-secondary"
                                onClick={() => onBodyTemplateChange('')}
                                title={t('pages.zevSettings.resetToGlobalDefault')}
                            >
                                {t('admin.resetToDefault')}
                            </button>
                        )}
                    </div>
                </label>

                <details open>
                    <summary style={{ cursor: 'pointer' }}>{t('admin.availableFields')}</summary>
                    <table style={{ marginTop: '0.75rem', width: '100%', fontSize: '0.78rem', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
                        <thead>
                            <tr>
                                <th style={{ textAlign: 'left', padding: '0.4rem 0.4rem 0.4rem 0' }}>{t('admin.emailTemplates.variable')}</th>
                                <th style={{ textAlign: 'left', padding: '0.4rem 0', overflowWrap: 'anywhere' }}>{t('admin.emailTemplates.fieldDescription')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {TEMPLATE_VARIABLES.map(({ variable, descriptionKey }) => (
                                <tr key={variable} style={{ borderBottom: '1px solid var(--border-default)' }}>
                                    <td style={{ padding: '0.3rem 0.4rem 0.3rem 0', fontFamily: 'monospace', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={variable}>
                                        {variable}
                                    </td>
                                    <td className="muted" style={{ padding: '0.3rem 0', overflowWrap: 'anywhere', lineHeight: 1.35 }}>
                                        {t(descriptionKey)}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </details>
            </div>
        </>
    )
}
