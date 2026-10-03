import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { PageSkeleton } from '../components/PageSkeleton'
import { FieldReference, fieldDescription, tokenMatchKey, useTemplateTokenInsertionAtElement } from '../components/FieldReference'
import { useTranslation } from 'react-i18next'
import {
    fetchContractPdfTemplate,
    fetchInvoicePdfTemplate,
    fetchAnnualStatementPdfTemplate,
    previewPdfTemplateBlob,
    resetContractPdfTemplate,
    resetInvoicePdfTemplate,
    resetAnnualStatementPdfTemplate,
    updateContractPdfTemplate,
    updateInvoicePdfTemplate,
    updateAnnualStatementPdfTemplate,
} from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'
import { formatApiError } from '../lib/api/errors'
import type { PdfTemplateMutationResponse, PdfTemplateResponse, TemplateField, TemplateFieldGroup } from '../types/api'
import { useToast } from '../lib/toast'
import { PdfPreview } from '../components/PdfPreview'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { TemplateSourceStatus } from '../components/TemplateSourceStatus'
import { useTemplateDraft } from '../lib/useTemplateDraft'
import { PageHeader } from '../components/PageHeader'

const PDF_TEMPLATE_TABS = ['invoice', 'contract', 'annual_statement'] as const

export type PdfTemplateTab = (typeof PDF_TEMPLATE_TABS)[number]

const PDF_TEMPLATE_CONFIG = {
    invoice: {
        queryKey: queryKeys.admin.invoicePdfTemplate,
        fetch: fetchInvoicePdfTemplate,
        save: updateInvoicePdfTemplate,
        reset: resetInvoicePdfTemplate,
    },
    contract: {
        queryKey: queryKeys.admin.contractPdfTemplate,
        fetch: fetchContractPdfTemplate,
        save: updateContractPdfTemplate,
        reset: resetContractPdfTemplate,
    },
    annual_statement: {
        queryKey: queryKeys.admin.annualStatementPdfTemplate,
        fetch: fetchAnnualStatementPdfTemplate,
        save: updateAnnualStatementPdfTemplate,
        reset: resetAnnualStatementPdfTemplate,
    },
} satisfies Record<PdfTemplateTab, {
    queryKey: () => readonly string[]
    fetch: () => Promise<PdfTemplateResponse>
    save: (content: string) => Promise<PdfTemplateMutationResponse>
    reset: () => Promise<PdfTemplateMutationResponse>
}>

const selectPdfContent = (data: PdfTemplateResponse) => data.content
const equalPdfContent = (left: string, right: string) => left === right

export interface TemplateTextareaHandle {
    insert: (variable: string, keepFocus: boolean) => void
}

const TemplateTextarea = forwardRef(function TemplateTextarea(
    {
        value,
        onChange,
        groups,
        disabled = false,
    }: {
        value: string
        onChange: (value: string) => void
        groups: TemplateFieldGroup[]
        disabled?: boolean
    },
    ref,
) {
    const { t } = useTranslation()
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const overlayRef = useRef<HTMLDivElement>(null)
    const containerRef = useRef<HTMLDivElement>(null)
    const [tooltip, setTooltip] = useState<{ text: string; example?: string | null; x: number; y: number } | null>(null)

    const insertToken = useTemplateTokenInsertionAtElement(textareaRef, onChange)

    const fieldMaps = useMemo(() => {
        const exact = new Map<string, TemplateField>()
        const normalized = new Map<string, TemplateField>()
        for (const group of groups) {
            for (const field of group.fields) {
                exact.set(field.variable, field)
                const key = tokenMatchKey(field.variable)
                // Keep the first normalized entry as a deterministic fallback;
                // exact filter variants still resolve to their own description.
                if (!normalized.has(key)) {
                    normalized.set(key, field)
                }
            }
        }
        return { exact, normalized }
    }, [groups])

    useImperativeHandle(ref, () => ({
        insert(variable: string, keepFocus: boolean) {
            insertToken(variable, keepFocus)
        },
    }), [insertToken])

    const handleScroll = useCallback(() => {
        if (textareaRef.current && overlayRef.current) {
            overlayRef.current.scrollTop = textareaRef.current.scrollTop
            overlayRef.current.scrollLeft = textareaRef.current.scrollLeft
        }
    }, [])

    const parts = useMemo(() => {
        const result: { text: string; variable?: string }[] = []
        // Match {{ ... }}, {% ... %}, and {{ ...|safe }}
        const regex = /(\{\{.*?\}\}|\{%.*?%\})/g
        let lastIndex = 0
        let match: RegExpExecArray | null
        while ((match = regex.exec(value)) !== null) {
            if (match.index > lastIndex) {
                result.push({ text: value.slice(lastIndex, match.index) })
            }
            result.push({ text: match[0], variable: match[0].trim() })
            lastIndex = regex.lastIndex
        }
        if (lastIndex < value.length) {
            result.push({ text: value.slice(lastIndex) })
        }
        return result
    }, [value])

    return (
        <div ref={containerRef} style={{ position: 'relative' }}>
            <textarea
                ref={textareaRef}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                onScroll={handleScroll}
                rows={24}
                className="template-editor"
                spellCheck={false}
                disabled={disabled}
            />
            <div
                ref={overlayRef}
                aria-hidden="true"
                style={{
                    position: 'absolute',
                    inset: 0,
                    padding: '1rem',
                    fontFamily: "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace",
                    fontSize: '0.9rem',
                    lineHeight: 1.5,
                    whiteSpace: 'pre-wrap',
                    wordWrap: 'break-word',
                    overflow: 'hidden',
                    pointerEvents: 'none',
                    color: 'transparent',
                    borderRadius: '0.9rem',
                    border: '1px solid transparent',
                }}
            >
                {parts.map((part, i) => {
                    if (!part.variable) {
                        return <span key={i}>{part.text}</span>
                    }
                    const field = fieldMaps.exact.get(part.variable.trim()) ?? fieldMaps.normalized.get(tokenMatchKey(part.variable))
                    if (!field) {
                        // Local or custom variables may not be cataloged.
                        return <span key={i}>{part.text}</span>
                    }
                    return (
                        <span
                            key={i}
                            className="template-var-chip"
                            onMouseEnter={(e) => {
                                const rect = (e.target as HTMLElement).getBoundingClientRect()
                                const containerRect = containerRef.current?.getBoundingClientRect() ?? rect
                                setTooltip({
                                    text: fieldDescription(t, field),
                                    example: field.example,
                                    x: rect.left - containerRect.left,
                                    y: rect.top - containerRect.top - 28,
                                })
                            }}
                            onMouseLeave={() => setTooltip(null)}
                        >
                            {part.text}
                        </span>
                    )
                })}
            </div>
            {tooltip && (
                <div
                    className="template-var-tooltip"
                    style={{ left: tooltip.x, top: tooltip.y }}
                >
                    {tooltip.text}
                    {tooltip.example && (
                        <div style={{ fontStyle: 'italic' }}>
                            {t('admin.example')}: {tooltip.example}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
})

function TemplateEditor({
    data,
    isLoading,
    isError,
    onSave,
    onReset,
    isSaving,
    isResetting,
    templateType,
}: {
    data: PdfTemplateResponse | undefined
    isLoading: boolean
    isError: boolean
    onSave: (content: string) => Promise<PdfTemplateMutationResponse>
    onReset: () => Promise<PdfTemplateMutationResponse>
    isSaving: boolean
    isResetting: boolean
    templateType: 'invoice' | 'contract' | 'annual_statement'
}) {
    const { t } = useTranslation()
    const [mutationError, setMutationError] = useState<string | null>(null)
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const busy = isSaving || isResetting || dialogLoading
    const { draft, setDraft, saved, accept } = useTemplateDraft(data, busy, selectPdfContent, equalPdfContent)
    const content = draft ?? ''
    const savedContent = saved
    const setContent = setDraft
    const [showPreview, setShowPreview] = useState(true)
    const [debugSource, setDebugSource] = useState(false)
    const [previewUrl, setPreviewUrl] = useState<string | null>(null)
    const [rendering, setRendering] = useState(false)
    const [previewError, setPreviewError] = useState('')
    // Guards against out-of-order responses: only the latest request may
    // replace the frame; superseded ones are aborted and their blobs revoked.
    const revisionRef = useRef(0)
    const urlRef = useRef<string | null>(null)
    const abortRef = useRef<AbortController | null>(null)
    const textareaHandleRef = useRef<TemplateTextareaHandle>(null)

    async function save() {
        if (busy) return
        setMutationError(null)
        try {
            const result = await onSave(content)
            accept(result.content)
        } catch (error) {
            setMutationError(formatApiError(error, t('common.error')))
        }
    }

    function askReset() {
        if (busy || !data?.is_customized) return
        confirm({
            title: t('admin.resetBuiltInConfirmTitle', {
                template: t(templateType === 'invoice' ? 'admin.invoiceTemplate'
                    : templateType === 'contract' ? 'admin.contractTemplate' : 'admin.annualStatementTemplate'),
            }),
            message: t('admin.resetBuiltInConfirmMessage'),
            confirmText: t('admin.resetBuiltIn'),
            onConfirm: async () => {
                setMutationError(null)
                try {
                    const result = await onReset()
                    accept(result.content)
                } catch (error) {
                    setMutationError(formatApiError(error, t('common.error')))
                }
            },
        })
    }

    // Single render path shared by the debounced auto-render and the explicit
    // Render button: owns the revision guard, the abort controller and the
    // object-URL lifecycle. The source text is passed in so the callback stays
    // stable across content edits.
    const renderPreview = useCallback(
        async (source: string) => {
            const revision = ++revisionRef.current
            const controller = new AbortController()
            abortRef.current?.abort()
            abortRef.current = controller
            setRendering(true)
            setPreviewError('')
            try {
                const blob = await previewPdfTemplateBlob(source, templateType, controller.signal)
                if (revision !== revisionRef.current) return // superseded
                const url = URL.createObjectURL(blob)
                const previous = urlRef.current
                urlRef.current = url
                setPreviewUrl(url)
                setRendering(false)
                // Revoke the replaced URL only after the new frame had time to load.
                if (previous) window.setTimeout(() => URL.revokeObjectURL(previous), 10_000)
            } catch (err) {
                if (controller.signal.aborted || revision !== revisionRef.current) return
                setRendering(false)
                const status = (err as { response?: { status?: number } }).response?.status
                let detail = ''
                const errData = (err as { response?: { data?: unknown } }).response?.data
                if (errData instanceof Blob) {
                    try {
                        detail = (JSON.parse(await errData.text()) as { error?: string }).error ?? ''
                    } catch {
                        /* non-JSON body */
                    }
                }
                setPreviewError(detail || t(status === 400 ? 'admin.previewRenderError' : 'admin.previewError'))
            }
        },
        [templateType, t],
    )

    // Debounced auto-render whenever the preview view is open and the content
    // changes (typing happens in the separate editor view, so in practice this
    // fires once on entering the preview and after each editor round-trip).
    // The previous object URL stays visible with a transient "re-rendering…"
    // state until the replacement frame has loaded.
    useEffect(() => {
        if (!showPreview || debugSource) return
        if (!content.trim()) return
        const timer = window.setTimeout(() => void renderPreview(content), 700)
        return () => window.clearTimeout(timer)
    }, [content, showPreview, debugSource, renderPreview])

    useEffect(
        () => () => {
            revisionRef.current += 1
            abortRef.current?.abort()
            if (urlRef.current) URL.revokeObjectURL(urlRef.current)
        },
        [],
    )

    const handleInsert = useCallback((variable: string, keepFocus: boolean) => {
        if (busy) return
        textareaHandleRef.current?.insert(variable, keepFocus)
    }, [busy])

    return (
        <>
        <div className="content-with-aside">
            <section className="card page-stack">
                {isLoading && <PageSkeleton variant="card" />}
                {isError && <p className="error-banner">{t('common.error')}</p>}
                {data && (
                    <>
                        <TemplateSourceStatus
                            source={data.is_customized ? 'customized' : 'builtIn'}
                            changed={savedContent !== null && content !== savedContent}
                            description={t('admin.platformPdfScope')}
                        />
                        {mutationError && <p className="error-banner" role="alert">{mutationError}</p>}
                        {data.is_stale && (
                            <div className="warning-banner" role="alert">
                                {t('admin.staleTemplate')}
                            </div>
                        )}
                        {!showPreview && (
                            <label>
                                <span>{t('admin.templateContent')}</span>
                                <TemplateTextarea
                                    ref={textareaHandleRef}
                                    value={content}
                                    onChange={setContent}
                                    groups={data.fields ?? []}
                                    disabled={busy}
                                />
                            </label>
                        )}
                        {/* The shared-base include lives in the invoice and
                            contract defaults; the annual-statement template
                            is standalone, so the hint only applies there. */}
                        {templateType !== 'annual_statement' && !showPreview && (
                            <p className="muted" style={{ marginTop: '0.5rem' }}>
                                {t('admin.templateIncludeHint')}
                            </p>
                        )}
                        {showPreview && (
                            <div className="page-stack">
                                <div className="actions-row">
                                    <button
                                        className={`button button-compact ${debugSource ? 'button-secondary' : ''}`}
                                        type="button"
                                        aria-pressed={!debugSource}
                                        onClick={() => setDebugSource(false)}
                                    >
                                        {t('pdf.previewTitle')}
                                    </button>
                                    <button
                                        className={`button button-compact ${debugSource ? '' : 'button-secondary'}`}
                                        type="button"
                                        aria-pressed={debugSource}
                                        onClick={() => setDebugSource(true)}
                                    >
                                        {t('admin.previewSource')}
                                    </button>
                                    {rendering && (
                                        <span className="muted" role="status">{t('admin.previewRerendering')}</span>
                                    )}
                                    <span style={{ flex: 1 }} />
                                    <button
                                        className="button button-secondary button-compact"
                                        type="button"
                                        disabled={rendering || debugSource}
                                        onClick={() => void renderPreview(content)}
                                    >
                                        {t('admin.previewRenderNow')}
                                    </button>
                                </div>
                                {debugSource ? (
                                    // Escaped source text — server-rendered admin HTML is
                                    // never written into a document or executed.
                                    <pre
                                        className="template-editor"
                                        style={{
                                            whiteSpace: 'pre-wrap',
                                            wordBreak: 'break-word',
                                            maxHeight: '70vh',
                                            overflowY: 'auto',
                                        }}
                                    >
                                        {content}
                                    </pre>
                                ) : (
                                    <PdfPreview src={previewUrl} title={t('admin.previewLabel')} height="70vh" />
                                )}
                            </div>
                        )}
                        {previewError && <p className="error-banner">{previewError}</p>}
                        <div className="actions-row actions-row-wrap">
                            <button
                                className="button"
                                type="button"
                                disabled={busy}
                                onClick={() => void save()}
                            >
                                {isSaving ? t('common.saving') : t('common.save')}
                            </button>
                            <button
                                className="button button-secondary"
                                type="button"
                                onClick={() => setShowPreview((v) => !v)}
                            >
                                {showPreview ? t('admin.backToEditor') : t('admin.preview')}
                            </button>
                            {data.is_customized && (
                                <button
                                    className="button button-secondary"
                                    type="button"
                                    disabled={busy}
                                    onClick={askReset}
                                >
                                    {isResetting ? t('common.loading') : t('admin.resetBuiltIn')}
                                </button>
                            )}
                        </div>
                    </>
                )}
            </section>
            {data ? (
                <FieldReference
                    groups={data.fields ?? []}
                    content={content}
                    onInsert={showPreview || busy ? undefined : handleInsert}
                />
            ) : isError ? (
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
 * since phase 3; /admin/pdf-templates stays as a deep-link alias).
 */
export function AdminPdfTemplatesPage({ embedded = false, template }: {
    embedded?: boolean
    template?: PdfTemplateTab
}) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const [selectedTemplate, setSelectedTemplate] = useState<PdfTemplateTab>('invoice')
    const activeTab = template ?? selectedTemplate

    const tabLabels: Record<PdfTemplateTab, string> = {
        invoice: t('admin.invoiceTemplate'),
        contract: t('admin.contractTemplate'),
        annual_statement: t('admin.annualStatementTemplate'),
    }


    const selectedConfig = PDF_TEMPLATE_CONFIG[activeTab]
    const templateQuery = useQuery({
        queryKey: selectedConfig.queryKey(),
        queryFn: selectedConfig.fetch,
    })

    async function acceptResult(result: PdfTemplateMutationResponse, templateType: PdfTemplateTab) {
        const key = PDF_TEMPLATE_CONFIG[templateType].queryKey()
        await queryClient.cancelQueries({ queryKey: key })
        queryClient.setQueryData<PdfTemplateResponse>(key, (previous) =>
            previous ? { ...previous, ...result, is_stale: result.is_stale ?? false } : previous)
    }

    const saveMutation = useMutation({
        mutationFn: ({ templateType, content }: { templateType: PdfTemplateTab; content: string }) =>
            PDF_TEMPLATE_CONFIG[templateType].save(content),
        onSuccess: async (result, { templateType }) => {
            await acceptResult(result, templateType)
            pushToast(result.detail ?? t('common.save'), 'success')
        },
    })

    const resetMutation = useMutation({
        mutationFn: (templateType: PdfTemplateTab) => PDF_TEMPLATE_CONFIG[templateType].reset(),
        onSuccess: async (result, templateType) => {
            await acceptResult(result, templateType)
            pushToast(result.detail ?? t('admin.resetToDefault'), 'success')
        },
    })

    return (
        <div className="page-stack">
            {!embedded && (
                <PageHeader
                    eyebrow={t('nav.platformScope')}
                    title={t('admin.pdfTemplates')}
                    description={t('admin.pdfTemplatesDescription')}
                />
            )}

            {!embedded && (
                <label>
                    <span>{t('pages.adminTemplates.selectTemplate')}</span>
                    <select value={activeTab} onChange={(event) => setSelectedTemplate(event.target.value as PdfTemplateTab)}>
                        {PDF_TEMPLATE_TABS.map((tab) => <option key={tab} value={tab}>{tabLabels[tab]}</option>)}
                    </select>
                </label>
            )}

            <TemplateEditor
                key={activeTab}
                data={templateQuery.data}
                isLoading={templateQuery.isLoading}
                isError={templateQuery.isError}
                onSave={(content) => saveMutation.mutateAsync({ templateType: activeTab, content })}
                onReset={() => resetMutation.mutateAsync(activeTab)}
                isSaving={saveMutation.isPending && saveMutation.variables?.templateType === activeTab}
                isResetting={resetMutation.isPending && resetMutation.variables === activeTab}
                templateType={activeTab}
            />
        </div>
    )
}
