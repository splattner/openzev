import { useQuery } from '@tanstack/react-query'
import { faChevronDown } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchEmailTemplate } from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'
import { FieldReference, useTemplateTokenInsertion } from './FieldReference'
import { TemplateSourceStatus } from './TemplateSourceStatus'

type ZevEmailTemplateFieldsProps = {
    subjectTemplate: string
    bodyTemplate: string
    savedSubjectTemplate?: string
    savedBodyTemplate?: string
    /** A completed save or discard resets editor mode, independently of typing. */
    resetRevision?: number
    onSubjectTemplateChange: (value: string) => void
    onBodyTemplateChange: (value: string) => void
    fieldErrors?: Record<string, string>
    /** Disabled-ZEV owner view: values stay visible but nothing is editable. */
    readOnly?: boolean
}

export function ZevEmailTemplateFields({
    subjectTemplate,
    bodyTemplate,
    savedSubjectTemplate = subjectTemplate,
    savedBodyTemplate = bodyTemplate,
    resetRevision = 0,
    onSubjectTemplateChange,
    onBodyTemplateChange,
    fieldErrors = {},
    readOnly = false,
}: ZevEmailTemplateFieldsProps) {
    const { t } = useTranslation()
    const subjectRef = useRef<HTMLInputElement>(null)
    const bodyRef = useRef<HTMLTextAreaElement>(null)
    const lastFocusedRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null)
    const [fieldsOpen, setFieldsOpen] = useState(false)
    const [editingDefaultSubject, setEditingDefaultSubject] = useState(false)
    const [editingDefaultBody, setEditingDefaultBody] = useState(false)

    useEffect(() => {
        setEditingDefaultSubject(false)
        setEditingDefaultBody(false)
    }, [resetRevision])

    // Owner-readable fallback; a failed fetch never blocks editing or saving.
    const globalTemplateQuery = useQuery({
        queryKey: queryKeys.admin.emailTemplate('invoice_email'),
        queryFn: () => fetchEmailTemplate('invoice_email'),
    })

    const globalSubject = globalTemplateQuery.data?.subject ?? ''
    const globalBody = globalTemplateQuery.data?.body ?? ''
    const hasGlobal = globalTemplateQuery.data != null

    const handleInsert = useTemplateTokenInsertion(
        subjectRef,
        bodyRef,
        lastFocusedRef,
        onSubjectTemplateChange,
        onBodyTemplateChange,
    )

    function handleInsertWithCustomize(variable: string, keepFocus: boolean) {
        if (lastFocusedRef.current && !lastFocusedRef.current.isConnected) {
            lastFocusedRef.current = null
        }
        if (!lastFocusedRef.current && !bodyRef.current && !readOnly && hasGlobal) {
            const separator = globalBody && !/\s$/.test(globalBody) ? '\n' : ''
            setEditingDefaultBody(true)
            onBodyTemplateChange(`${globalBody}${separator}${variable}`)
            return
        }
        handleInsert(variable, keepFocus)
    }

    function renderField(field: 'subject' | 'body') {
        const isSubject = field === 'subject'
        const value = isSubject ? subjectTemplate : bodyTemplate
        const globalValue = isSubject ? globalSubject : globalBody
        const usesDefault = value === '' && !(isSubject ? editingDefaultSubject : editingDefaultBody)
        const inheritsDefault = value === ''
        const savedValue = isSubject ? savedSubjectTemplate : savedBodyTemplate
        const changed = value !== savedValue
        const error = fieldErrors[isSubject ? 'email_subject_template' : 'email_body_template']
        const labelId = `zev-settings-email-${field}-label`
        const errorId = `zev-settings-email-${field}-error`
        const change = isSubject ? onSubjectTemplateChange : onBodyTemplateChange
        const setEditing = isSubject ? setEditingDefaultSubject : setEditingDefaultBody

        return (
            <div className="zev-email-field" data-zev-field={`email_${field}_template`}>
                <div className="zev-email-label-row">
                    <span id={labelId}>{t(isSubject ? 'admin.emailTemplates.subject' : 'admin.emailTemplates.body')}</span>
                    <TemplateSourceStatus
                        source={savedValue === '' ? 'platform' : 'zev'}
                        changed={changed}
                        description={changed && inheritsDefault ? t('pages.zevSettings.emailInheritanceOnSave') : undefined}
                        action={!readOnly && (
                        <button
                            type="button"
                            className="button button-secondary button-compact"
                            onClick={() => {
                                setEditing(usesDefault)
                                change(usesDefault ? globalValue : '')
                            }}
                            aria-label={t(usesDefault
                                ? (isSubject ? 'pages.zevSettings.emailCustomizeSubject' : 'pages.zevSettings.emailCustomizeBody')
                                : (isSubject ? 'pages.zevSettings.emailResetSubject' : 'pages.zevSettings.emailResetBody'))}
                            aria-describedby={usesDefault && error ? errorId : undefined}
                        >
                            {t(usesDefault ? 'pages.zevSettings.emailCustomize' : 'pages.zevSettings.emailUseDefault')}
                        </button>
                        )}
                    />
                </div>
                {usesDefault ? (hasGlobal && (
                    <p className="zev-email-default-preview">{globalValue}</p>
                )) : isSubject ? (
                    <input
                        ref={subjectRef}
                        aria-labelledby={labelId}
                        onFocus={() => { lastFocusedRef.current = subjectRef.current }}
                        value={value}
                        disabled={readOnly}
                        aria-invalid={error ? true : undefined}
                        aria-describedby={error ? errorId : undefined}
                        onChange={(event) => { setEditing(true); change(event.target.value) }}
                    />
                ) : (
                    <textarea
                        ref={bodyRef}
                        aria-labelledby={labelId}
                        onFocus={() => { lastFocusedRef.current = bodyRef.current }}
                        rows={10}
                        value={value}
                        disabled={readOnly}
                        aria-invalid={error ? true : undefined}
                        aria-describedby={error ? errorId : undefined}
                        onChange={(event) => { setEditing(true); change(event.target.value) }}
                    />
                )}
                {error && <small className="field-error" id={errorId} role="alert">{error}</small>}
            </div>
        )
    }

    return (
        <>
            <header>
                <h3>{t('pages.zevSettings.emailTemplateTitle')}</h3>
            </header>

            <div className="inline-form page-stack">
                {renderField('subject')}
                {renderField('body')}

                {globalTemplateQuery.data ? (
                    <div className="zev-email-fields-toggle">
                        <button
                            type="button"
                            className="button button-ghost button-compact disclosure-toggle"
                            aria-expanded={fieldsOpen}
                            onClick={() => setFieldsOpen((open) => !open)}
                        >
                            <FontAwesomeIcon icon={faChevronDown} className="disclosure-toggle-icon" fixedWidth aria-hidden="true" />
                            {t('pages.zevSettings.emailInsertField')}
                        </button>
                        {fieldsOpen && (
                            <FieldReference
                                groups={globalTemplateQuery.data.fields ?? []}
                                content={`${subjectTemplate}\n${bodyTemplate}`}
                                onInsert={readOnly ? undefined : handleInsertWithCustomize}
                            />
                        )}
                    </div>
                ) : globalTemplateQuery.isError ? (
                    <p className="error-banner" role="alert">{t('common.error')}</p>
                ) : (
                    <p className="muted" role="status">{t('common.loading')}</p>
                )}
            </div>
        </>
    )
}
