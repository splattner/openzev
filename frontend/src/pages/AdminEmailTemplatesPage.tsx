import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { PageSkeleton } from '../components/PageSkeleton'
import { useTranslation } from 'react-i18next'
import { PageHeader } from '../components/PageHeader'
import {
    fetchEmailTemplate,
    resetEmailTemplate,
    updateEmailTemplate,
} from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'
import { formatApiError } from '../lib/api/errors'
import { useToast } from '../lib/toast'
import { FieldReference, useTemplateTokenInsertion } from '../components/FieldReference'
import type { EmailTemplateKey } from '../lib/emailTemplateFields'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { TemplateSourceStatus } from '../components/TemplateSourceStatus'
import { useTemplateDraft } from '../lib/useTemplateDraft'
import type { EmailTemplateResponse } from '../types/api'

const EMAIL_TEMPLATE_LABEL_KEYS: Record<EmailTemplateKey, string> = {
    invoice_email: 'admin.emailTemplates.invoiceEmail',
    participant_onboarding: 'admin.emailTemplates.onboardingEmail',
    email_verification: 'admin.emailTemplates.verificationEmail',
    participant_magic_link: 'admin.emailTemplates.magicLinkEmail',
    zev_access_invitation: 'admin.emailTemplates.zevAccessInvitationEmail',
    zev_access_granted: 'admin.emailTemplates.zevAccessGrantedEmail',
}

/** Templates shipped in the ZEV's invoice language until an operator overrides them. */
const TRANSLATED_TEMPLATE_KEYS = new Set<EmailTemplateKey>(['participant_magic_link', 'zev_access_invitation', 'zev_access_granted'])

type EmailDraft = Pick<EmailTemplateResponse, 'subject' | 'body'>
const selectEmailDraft = ({ subject, body }: EmailDraft): EmailDraft => ({ subject, body })
const equalEmailDraft = (left: EmailDraft, right: EmailDraft) => left.subject === right.subject && left.body === right.body

function EmailTemplateEditor({ templateKey }: { templateKey: EmailTemplateKey }) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const subjectRef = useRef<HTMLInputElement>(null)
    const bodyRef = useRef<HTMLTextAreaElement>(null)
    const lastFocusedRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null)
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const query = useQuery({
        queryKey: queryKeys.admin.emailTemplate(templateKey),
        queryFn: () => fetchEmailTemplate(templateKey),
    })

    const [mutationError, setMutationError] = useState<string | null>(null)

    const saveMutation = useMutation({
        mutationFn: ({ subject, body }: EmailDraft) => updateEmailTemplate(templateKey, subject, body),
        onSuccess: async (result) => {
            await queryClient.cancelQueries({ queryKey: queryKeys.admin.emailTemplate(templateKey) })
            queryClient.setQueryData<EmailTemplateResponse>(queryKeys.admin.emailTemplate(templateKey), (previous) =>
                previous ? { ...previous, ...result } : previous)
            pushToast(result.detail ?? t('common.save'), 'success')
        },
    })

    const resetMutation = useMutation({
        mutationFn: () => resetEmailTemplate(templateKey),
        onSuccess: async (result) => {
            await queryClient.cancelQueries({ queryKey: queryKeys.admin.emailTemplate(templateKey) })
            queryClient.setQueryData<EmailTemplateResponse>(queryKeys.admin.emailTemplate(templateKey), (previous) =>
                previous ? { ...previous, ...result } : previous)
            pushToast(result.detail ?? t('admin.resetToDefault'), 'success')
        },
    })

    const busy = saveMutation.isPending || resetMutation.isPending || dialogLoading
    const { draft, setDraft, saved, accept } = useTemplateDraft(query.data, busy, selectEmailDraft, equalEmailDraft)
    const subject = draft?.subject ?? ''
    const body = draft?.body ?? ''
    const setSubject = (value: string) => setDraft((previous) => previous && { ...previous, subject: value })
    const setBody = (value: string) => setDraft((previous) => previous && { ...previous, body: value })

    const handleInsert = useTemplateTokenInsertion(
        subjectRef,
        bodyRef,
        lastFocusedRef,
        setSubject,
        setBody,
    )

    async function save() {
        if (busy) return
        setMutationError(null)
        try {
            const result = await saveMutation.mutateAsync({ subject, body })
            accept(selectEmailDraft(result))
        } catch (error) {
            setMutationError(formatApiError(error, t('common.error')))
        }
    }

    function askReset() {
        if (busy || !query.data?.is_customized) return
        confirm({
            title: t('admin.resetBuiltInConfirmTitle', {
                template: t(EMAIL_TEMPLATE_LABEL_KEYS[templateKey]),
            }),
            message: t('admin.resetBuiltInConfirmMessage'),
            confirmText: t('admin.resetBuiltIn'),
            onConfirm: async () => {
                setMutationError(null)
                try {
                    const result = await resetMutation.mutateAsync()
                    accept(selectEmailDraft(result))
                } catch (error) {
                    setMutationError(formatApiError(error, t('common.error')))
                }
            },
        })
    }

    return (
        <>
        <div className="content-with-aside">
            <section className="card page-stack">
                {/* One override replaces all four translated defaults. */}
                {TRANSLATED_TEMPLATE_KEYS.has(templateKey) && (
                    <p className="muted">{t('admin.emailTemplates.magicLinkLanguageNote')}</p>
                )}
                {query.isLoading && <PageSkeleton variant="card" />}
                {query.isError && <p className="error-banner">{t('common.error')}</p>}
                {query.data && (
                    <>
                        <TemplateSourceStatus
                            source={query.data.is_customized ? 'customized' : 'builtIn'}
                            changed={saved !== null && !equalEmailDraft({ subject, body }, saved)}
                            description={t(templateKey === 'invoice_email' ? 'admin.platformInvoiceEmailScope' : 'admin.platformTemplateScope')}
                        />
                        {mutationError && <p className="error-banner" role="alert">{mutationError}</p>}
                        <label>
                            <span>{t('admin.emailTemplates.subject')}</span>
                            <input
                                ref={subjectRef}
                                onFocus={() => { lastFocusedRef.current = subjectRef.current }}
                                type="text"
                                value={subject}
                                disabled={busy}
                                onChange={(e) => setSubject(e.target.value)}
                            />
                        </label>
                        <label>
                            <span>{t('admin.emailTemplates.body')}</span>
                            <textarea
                                ref={bodyRef}
                                onFocus={() => { lastFocusedRef.current = bodyRef.current }}
                                className="mono-editor"
                                rows={24}
                                value={body}
                                disabled={busy}
                                onChange={(e) => setBody(e.target.value)}
                            />
                        </label>
                        <div className="actions-row actions-row-wrap">
                            <button
                                className="button"
                                type="button"
                                disabled={busy}
                                onClick={() => void save()}
                            >
                                {saveMutation.isPending ? t('common.saving') : t('common.save')}
                            </button>
                            {query.data.is_customized && (
                                <button
                                    className="button button-secondary"
                                    type="button"
                                    disabled={busy}
                                    onClick={askReset}
                                >
                                    {resetMutation.isPending ? t('common.loading') : t('admin.resetBuiltIn')}
                                </button>
                            )}
                        </div>
                    </>
                )}
            </section>
            {query.data ? (
                <FieldReference
                    groups={query.data.fields ?? []}
                    content={`${subject}\n${body}`}
                    onInsert={busy ? undefined : handleInsert}
                />
            ) : query.isError ? (
                <p className="error-banner" role="alert">{t('common.error')}</p>
            ) : (
                <p className="muted" role="status">{t('common.loading')}</p>
            )}
        </div>
        {dialog && <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />}
        </>
    )
}

/**
 * `embedded` drops the page header and picker (mounted inside the admin Templates hub
 * since phase 3; /admin/email-templates stays as a deep-link alias).
 */
export function AdminEmailTemplatesPage({ embedded = false, template }: {
    embedded?: boolean
    template?: EmailTemplateKey
}) {
    const { t } = useTranslation()
    const [selectedTemplate, setSelectedTemplate] = useState<EmailTemplateKey>('invoice_email')
    const activeTab = template ?? selectedTemplate

    const tabs: { key: EmailTemplateKey; label: string }[] = [
        { key: 'invoice_email', label: t(EMAIL_TEMPLATE_LABEL_KEYS.invoice_email) },
        { key: 'participant_onboarding', label: t(EMAIL_TEMPLATE_LABEL_KEYS.participant_onboarding) },
        { key: 'email_verification', label: t(EMAIL_TEMPLATE_LABEL_KEYS.email_verification) },
        { key: 'participant_magic_link', label: t(EMAIL_TEMPLATE_LABEL_KEYS.participant_magic_link) },
        { key: 'zev_access_invitation', label: t(EMAIL_TEMPLATE_LABEL_KEYS.zev_access_invitation) },
        { key: 'zev_access_granted', label: t(EMAIL_TEMPLATE_LABEL_KEYS.zev_access_granted) },
    ]

    return (
        <div className="page-stack">
            {!embedded && (
            <PageHeader
                eyebrow={t('nav.platformScope')}
                title={t('admin.emailTemplates.title')}
                description={t('admin.emailTemplates.description')}
            />
            )}

            {!embedded && (
                <label>
                    <span>{t('pages.adminTemplates.selectTemplate')}</span>
                    <select value={activeTab} onChange={(event) => setSelectedTemplate(event.target.value as EmailTemplateKey)}>
                        {tabs.map((tab) => <option key={tab.key} value={tab.key}>{tab.label}</option>)}
                    </select>
                </label>
            )}
            <EmailTemplateEditor
                key={activeTab}
                templateKey={activeTab}
            />
        </div>
    )
}
