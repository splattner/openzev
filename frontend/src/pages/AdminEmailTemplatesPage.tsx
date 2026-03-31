import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
    fetchEmailTemplate,
    resetEmailTemplate,
    updateEmailTemplate,
} from '../lib/api'
import { useToast } from '../lib/toast'

type TemplateKey = 'invoice_email' | 'participant_invitation' | 'email_verification'

interface FieldInfo {
    variable: string
    description: string
}

function FieldReference({ fields }: { fields: FieldInfo[] }) {
    const { t } = useTranslation()
    return (
        <aside className="card page-stack" style={{ minWidth: 340, maxHeight: '80vh', overflowY: 'auto' }}>
            <h4 style={{ margin: 0 }}>{t('admin.availableFields')}</h4>
            <p className="muted" style={{ fontSize: '0.85rem', margin: 0 }}>
                {t('admin.emailTemplates.variableHint')}
            </p>
            <table style={{ width: '100%', fontSize: '0.85rem', borderCollapse: 'collapse' }}>
                <tbody>
                    {fields.map((f) => (
                        <tr key={f.variable} style={{ borderBottom: '1px solid var(--color-border, #e5e7eb)' }}>
                            <td style={{ padding: '0.35rem 0.5rem 0.35rem 0', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                                {f.variable}
                            </td>
                            <td className="muted" style={{ padding: '0.35rem 0' }}>
                                {f.description}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </aside>
    )
}

function EmailTemplateEditor({
    templateKey,
    title,
    fields,
}: {
    templateKey: TemplateKey
    title: string
    fields: FieldInfo[]
}) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()

    const query = useQuery({
        queryKey: ['admin-email-template', templateKey],
        queryFn: () => fetchEmailTemplate(templateKey),
    })

    const [subject, setSubject] = useState('')
    const [body, setBody] = useState('')

    useEffect(() => {
        if (query.data) {
            setSubject(query.data.subject)
            setBody(query.data.body)
        }
    }, [query.data])

    const saveMutation = useMutation({
        mutationFn: () => updateEmailTemplate(templateKey, subject, body),
        onSuccess: (result) => {
            pushToast(result.detail ?? t('common.save'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['admin-email-template', templateKey] })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    const resetMutation = useMutation({
        mutationFn: () => resetEmailTemplate(templateKey),
        onSuccess: (result) => {
            pushToast(result.detail ?? t('admin.resetToDefault'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['admin-email-template', templateKey] })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    return (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 360px', gap: '1.5rem', alignItems: 'start' }}>
            <section className="card page-stack">
                <div className="actions-row">
                    <h3 style={{ margin: 0 }}>{title}</h3>
                    {query.data?.is_customized && (
                        <span className="badge badge-info">{t('admin.customized')}</span>
                    )}
                </div>
                {query.isLoading && <p>{t('common.loading')}</p>}
                {query.isError && <p className="error-banner">{t('common.error')}</p>}
                {query.data && (
                    <>
                        <label>
                            <span>{t('admin.emailTemplates.subject')}</span>
                            <input
                                type="text"
                                value={subject}
                                onChange={(e) => setSubject(e.target.value)}
                            />
                        </label>
                        <label>
                            <span>{t('admin.emailTemplates.body')}</span>
                            <textarea
                                rows={14}
                                value={body}
                                onChange={(e) => setBody(e.target.value)}
                                style={{ fontFamily: "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace", fontSize: '0.9rem' }}
                            />
                        </label>
                        <div className="actions-row">
                            <button
                                className="button"
                                type="button"
                                disabled={saveMutation.isPending || resetMutation.isPending}
                                onClick={() => saveMutation.mutate()}
                            >
                                {saveMutation.isPending ? t('common.saving') : t('common.save')}
                            </button>
                            {query.data.is_customized && (
                                <button
                                    className="button button-secondary"
                                    type="button"
                                    disabled={saveMutation.isPending || resetMutation.isPending}
                                    onClick={() => resetMutation.mutate()}
                                >
                                    {resetMutation.isPending ? t('common.loading') : t('admin.resetToDefault')}
                                </button>
                            )}
                        </div>
                    </>
                )}
            </section>
            <FieldReference fields={fields} />
        </div>
    )
}

export function AdminEmailTemplatesPage() {
    const { t } = useTranslation()
    const [activeTab, setActiveTab] = useState<TemplateKey>('invoice_email')

    const invoiceFields: FieldInfo[] = [
        { variable: '{invoice_number}', description: t('admin.emailTemplates.fields.invoiceNumber') },
        { variable: '{zev_name}', description: t('admin.emailTemplates.fields.zevName') },
        { variable: '{participant_name}', description: t('admin.emailTemplates.fields.participantName') },
        { variable: '{period_start}', description: t('admin.emailTemplates.fields.periodStart') },
        { variable: '{period_end}', description: t('admin.emailTemplates.fields.periodEnd') },
        { variable: '{total_chf}', description: t('admin.emailTemplates.fields.totalChf') },
    ]

    const invitationFields: FieldInfo[] = [
        { variable: '{participant_name}', description: t('admin.emailTemplates.fields.participantName') },
        { variable: '{inviter_name}', description: t('admin.emailTemplates.fields.inviterName') },
        { variable: '{zev_name}', description: t('admin.emailTemplates.fields.zevName') },
        { variable: '{username}', description: t('admin.emailTemplates.fields.username') },
        { variable: '{temporary_password}', description: t('admin.emailTemplates.fields.temporaryPassword') },
    ]

    const verificationFields: FieldInfo[] = [
        { variable: '{verify_url}', description: t('admin.emailTemplates.fields.verifyUrl') },
    ]

    const tabs: { key: TemplateKey; label: string; fields: FieldInfo[] }[] = [
        { key: 'invoice_email', label: t('admin.emailTemplates.invoiceEmail'), fields: invoiceFields },
        { key: 'participant_invitation', label: t('admin.emailTemplates.invitationEmail'), fields: invitationFields },
        { key: 'email_verification', label: t('admin.emailTemplates.verificationEmail'), fields: verificationFields },
    ]

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('nav.adminConsole')}</p>
                <h2>{t('admin.emailTemplates.title')}</h2>
                <p className="muted">
                    {t('admin.emailTemplates.description')}
                </p>
            </header>

            <div style={{ display: 'flex', gap: '1rem', borderBottom: '1px solid var(--color-border, #e5e7eb)', marginBottom: '1.5rem' }}>
                {tabs.map((tab) => (
                    <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key)}
                        style={{
                            background: 'transparent',
                            color: activeTab === tab.key ? 'var(--color-text, #000)' : 'var(--color-text-muted, #888)',
                            padding: '0.75rem 1rem',
                            fontSize: '1rem',
                            fontWeight: activeTab === tab.key ? 600 : 400,
                            cursor: 'pointer',
                            border: 'none',
                            borderBlockEnd: activeTab === tab.key ? '2px solid var(--color-primary, #0066cc)' : 'none',
                        }}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {tabs.map((tab) =>
                activeTab === tab.key ? (
                    <EmailTemplateEditor
                        key={tab.key}
                        templateKey={tab.key}
                        title={tab.label}
                        fields={tab.fields}
                    />
                ) : null,
            )}
        </div>
    )
}
