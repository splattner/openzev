import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Tabs } from '@mantine/core'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
    fetchEmailTemplate,
    resetEmailTemplate,
    updateEmailTemplate,
} from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'
import { useToast } from '../lib/toast'

type TemplateKey = 'invoice_email' | 'participant_invitation' | 'email_verification'

interface FieldInfo {
    variable: string
    description: string
}

function FieldReference({ fields }: { fields: FieldInfo[] }) {
    const { t } = useTranslation()
    return (
        <aside
            className="card page-stack"
            style={{ maxHeight: '80vh', overflowY: 'auto', width: '100%' }}
            tabIndex={0}
            aria-label={t('admin.fieldReference')}
        >
            <h4 style={{ margin: 0 }}>{t('admin.availableFields')}</h4>
            <p className="muted" style={{ fontSize: '0.78rem', margin: 0, lineHeight: 1.35 }}>
                {t('admin.emailTemplates.variableHint')}
            </p>
            <table style={{ width: '100%', fontSize: '0.78rem', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
                <tbody>
                    {fields.map((f) => (
                        <tr key={f.variable} style={{ borderBottom: '1px solid var(--border-default)' }}>
                            <td style={{ padding: '0.3rem 0.35rem 0.3rem 0', fontFamily: 'monospace', overflowWrap: 'anywhere', width: '50%', fontSize: '0.72rem' }} title={f.variable}>
                                {f.variable}
                            </td>
                            <td className="muted" style={{ padding: '0.3rem 0', overflowWrap: 'anywhere', lineHeight: 1.3, fontSize: '0.74rem' }}>
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
        queryKey: queryKeys.admin.emailTemplate(templateKey),
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
            void queryClient.invalidateQueries({ queryKey: queryKeys.admin.emailTemplate(templateKey) })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    const resetMutation = useMutation({
        mutationFn: () => resetEmailTemplate(templateKey),
        onSuccess: (result) => {
            pushToast(result.detail ?? t('admin.resetToDefault'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.admin.emailTemplate(templateKey) })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    return (
        <div className="content-with-aside">
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
                                rows={24}
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
        { variable: '{due_date}', description: t('admin.emailTemplates.fields.dueDate') },
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

            <Tabs
                classNames={{ root: 'app-tabs', list: 'app-tabs-list', tab: 'app-tabs-tab' }}
                value={activeTab}
                keepMounted={false}
                onChange={(value) => {
                    if (value) setActiveTab(value as TemplateKey)
                }}
            >
                <Tabs.List aria-label={t('admin.emailTemplates.title')}>
                    {tabs.map((tab) => (
                        <Tabs.Tab key={tab.key} value={tab.key}>
                            {tab.label}
                        </Tabs.Tab>
                    ))}
                </Tabs.List>

                {tabs.map((tab) => (
                    <Tabs.Panel key={tab.key} value={tab.key}>
                        <EmailTemplateEditor
                            templateKey={tab.key}
                            title={tab.label}
                            fields={tab.fields}
                        />
                    </Tabs.Panel>
                ))}
            </Tabs>
        </div>
    )
}
