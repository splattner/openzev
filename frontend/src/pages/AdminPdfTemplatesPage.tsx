import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import type { PdfTemplateResponse } from '../types/api'
import { useToast } from '../lib/toast'
import { PdfPreview } from '../components/PdfPreview'

const PDF_TEMPLATE_TABS = ['invoice', 'contract', 'annual_statement'] as const

type PdfTemplateTab = (typeof PDF_TEMPLATE_TABS)[number]

interface FieldGroup {
    title: string
    fields: { variable: string; description: string }[]
}

function FieldReference({ groups }: { groups: FieldGroup[] }) {
    const { t } = useTranslation()
    return (
        <aside
            className="card page-stack"
            style={{ maxHeight: '80vh', overflowY: 'auto', width: '100%' }}
            tabIndex={0}
            aria-label={t('admin.fieldReference')}
        >
            <h4 style={{ margin: 0 }}>{t('admin.availableFields')}</h4>
            {groups.map((group) => (
                <div key={group.title}>
                    <h5 style={{ margin: '0.75rem 0 0.25rem' }}>{group.title}</h5>
                    <table style={{ width: '100%', fontSize: '0.82rem', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
                        <tbody>
                            {group.fields.map((f) => (
                                <tr key={f.variable} style={{ borderBottom: '1px solid var(--border-default)' }}>
                                    <td style={{ padding: '0.25rem 0.4rem 0.25rem 0', fontFamily: 'monospace', overflowWrap: 'anywhere', width: '52%' }}>
                                        {f.variable}
                                    </td>
                                    <td className="muted" style={{ padding: '0.25rem 0', overflowWrap: 'anywhere', lineHeight: 1.35 }}>
                                        {f.description}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            ))}
        </aside>
    )
}

function TemplateTextarea({
    value,
    onChange,
    fieldGroups,
}: {
    value: string
    onChange: (value: string) => void
    fieldGroups: FieldGroup[]
}) {
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const overlayRef = useRef<HTMLDivElement>(null)
    const containerRef = useRef<HTMLDivElement>(null)
    const [tooltip, setTooltip] = useState<{ text: string; x: number; y: number } | null>(null)

    const fieldMap = useMemo(() => {
        const map = new Map<string, string>()
        for (const group of fieldGroups) {
            for (const f of group.fields) {
                map.set(f.variable, f.description)
            }
        }
        return map
    }, [fieldGroups])

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
                    const desc = fieldMap.get(part.variable)
                    if (!desc) {
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
                                    text: desc,
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
                </div>
            )}
        </div>
    )
}

function TemplateEditor({
    data,
    isLoading,
    isError,
    onSave,
    onReset,
    isSaving,
    isResetting,
    title,
    fieldGroups,
    templateType,
}: {
    data: PdfTemplateResponse | undefined
    isLoading: boolean
    isError: boolean
    onSave: (content: string) => void
    onReset: () => void
    isSaving: boolean
    isResetting: boolean
    title: string
    fieldGroups: FieldGroup[]
    templateType: 'invoice' | 'contract' | 'annual_statement'
}) {
    const { t } = useTranslation()
    const [content, setContent] = useState('')
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

    useEffect(() => {
        if (data?.content != null) {
            setContent(data.content)
        }
    }, [data])

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

    // Cleanup on unmount.
    useEffect(
        () => () => {
            revisionRef.current += 1
            abortRef.current?.abort()
            if (urlRef.current) URL.revokeObjectURL(urlRef.current)
        },
        [],
    )

    return (
        <div className="content-with-aside">
            <section className="card page-stack">
                <div className="actions-row">
                    <h3 style={{ margin: 0 }}>{title}</h3>
                    {data?.is_customized && (
                        <span className="badge badge-info">{t('admin.customized')}</span>
                    )}
                </div>
                {isLoading && <p>{t('common.loading')}</p>}
                {isError && <p className="error-banner">{t('common.error')}</p>}
                {data && (
                    <>
                        {data.is_stale && (
                            <div className="warning-banner" role="alert">
                                {t('admin.staleTemplate')}
                            </div>
                        )}
                        {!showPreview && (
                            <label>
                                <span>{t('admin.templateContent')}</span>
                                <TemplateTextarea
                                    value={content}
                                    onChange={setContent}
                                    fieldGroups={fieldGroups}
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
                        <div className="actions-row">
                            <button
                                className="button"
                                type="button"
                                disabled={isSaving || isResetting}
                                onClick={() => onSave(content)}
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
                                    disabled={isSaving || isResetting}
                                    onClick={onReset}
                                >
                                    {isResetting ? t('common.loading') : t('admin.resetToDefault')}
                                </button>
                            )}
                        </div>
                    </>
                )}
            </section>
            <FieldReference groups={fieldGroups} />
        </div>
    )
}

export function AdminPdfTemplatesPage() {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const [activeTab, setActiveTab] = useState<PdfTemplateTab>('invoice')

    const tabLabels: Record<PdfTemplateTab, string> = {
        invoice: t('admin.invoiceTemplate'),
        contract: t('admin.contractTemplate'),
        annual_statement: t('admin.annualStatementTemplate'),
    }

    const handleTabKeyDown = useCallback(
        (event: React.KeyboardEvent<HTMLDivElement>) => {
            const index = PDF_TEMPLATE_TABS.indexOf(activeTab)
            let next: number | null = null
            if (event.key === 'ArrowRight') next = (index + 1) % PDF_TEMPLATE_TABS.length
            else if (event.key === 'ArrowLeft') next = (index - 1 + PDF_TEMPLATE_TABS.length) % PDF_TEMPLATE_TABS.length
            else if (event.key === 'Home') next = 0
            else if (event.key === 'End') next = PDF_TEMPLATE_TABS.length - 1
            if (next === null) return
            event.preventDefault()
            setActiveTab(PDF_TEMPLATE_TABS[next])
            document.getElementById(`pdf-template-tab-${PDF_TEMPLATE_TABS[next]}`)?.focus()
        },
        [activeTab],
    )

    const invoiceFieldGroups: FieldGroup[] = [
        {
            title: t('admin.fields.invoiceObject'),
            fields: [
                { variable: '{{ invoice.invoice_number }}', description: t('admin.fields.invoiceNumber') },
                { variable: '{{ invoice.get_status_display }}', description: t('admin.fields.invoiceStatus') },
                { variable: '{{ invoice.subtotal_chf }}', description: t('admin.fields.subtotal') },
                { variable: '{{ invoice.vat_rate }}', description: t('admin.fields.vatRate') },
                { variable: '{{ invoice.vat_chf }}', description: t('admin.fields.vatAmount') },
                { variable: '{{ invoice.total_chf }}', description: t('admin.fields.total') },
                { variable: '{{ invoice.notes }}', description: t('admin.fields.invoiceNotes') },
            ],
        },
        {
            title: t('admin.fields.formattedDates'),
            fields: [
                { variable: '{{ formatted_dates.invoice_date }}', description: t('admin.fields.invoiceDate') },
                { variable: '{{ formatted_dates.period_start }}', description: t('admin.fields.periodStart') },
                { variable: '{{ formatted_dates.period_end }}', description: t('admin.fields.periodEnd') },
                { variable: '{{ formatted_dates.due_date }}', description: t('admin.fields.dueDate') },
            ],
        },
        {
            title: t('admin.fields.participant'),
            fields: [
                { variable: '{{ participant.full_name }}', description: t('admin.fields.fullName') },
                { variable: '{{ participant.address_line1 }}', description: t('admin.fields.addressLine1') },
                { variable: '{{ participant.postal_code }}', description: t('admin.fields.postalCode') },
                { variable: '{{ participant.city }}', description: t('admin.fields.city') },
                { variable: '{{ participant.email }}', description: t('admin.fields.email') },
            ],
        },
        {
            title: t('admin.fields.zev'),
            fields: [
                { variable: '{{ zev.name }}', description: t('admin.fields.zevName') },
                { variable: '{{ zev.vat_number }}', description: t('admin.fields.vatNumber') },
                { variable: '{{ zev.bank_iban }}', description: t('admin.fields.bankIban') },
            ],
        },
        {
            title: t('admin.fields.ownerParticipant'),
            fields: [
                { variable: '{{ owner_participant.full_name }}', description: t('admin.fields.fullName') },
                { variable: '{{ owner_participant.address_line1 }}', description: t('admin.fields.addressLine1') },
                { variable: '{{ owner_participant.address_line2 }}', description: t('admin.fields.addressLine2') },
                { variable: '{{ owner_participant.postal_code }}', description: t('admin.fields.postalCode') },
                { variable: '{{ owner_participant.city }}', description: t('admin.fields.city') },
            ],
        },
        {
            title: t('admin.fields.lineItems'),
            fields: [
                { variable: '{% for group in grouped_items %}', description: t('admin.fields.groupLoop') },
                { variable: '{{ group.label }}', description: t('admin.fields.groupLabel') },
                { variable: '{{ group.subtotal }}', description: t('admin.fields.groupSubtotal') },
                { variable: '{% for item in group.items %}', description: t('admin.fields.itemLoop') },
                { variable: '{{ item.description }}', description: t('admin.fields.itemDescription') },
                { variable: '{{ item.quantity_kwh }}', description: t('admin.fields.itemQuantity') },
                { variable: '{{ item.unit_price_chf }}', description: t('admin.fields.itemUnitPrice') },
                { variable: '{{ item.total_chf }}', description: t('admin.fields.itemTotal') },
            ],
        },
        {
            title: t('admin.fields.chartsAndSavings'),
            fields: [
                { variable: '{{ energy_chart_svg|safe }}', description: t('admin.fields.energyChart') },
                { variable: '{{ hourly_profile_chart_svg|safe }}', description: t('admin.fields.hourlyChart') },
                { variable: '{{ savings_data.local_kwh }}', description: t('admin.fields.savingsLocalKwh') },
                { variable: '{{ savings_data.saved_chf }}', description: t('admin.fields.savingsSavedChf') },
                { variable: '{{ qr_svg|safe }}', description: t('admin.fields.qrCode') },
            ],
        },
        {
            title: t('admin.fields.translations'),
            fields: [
                { variable: '{{ tr.<key> }}', description: t('admin.fields.trDescription') },
            ],
        },
    ]

    const contractFieldGroups: FieldGroup[] = [
        {
            title: t('admin.fields.participant'),
            fields: [
                { variable: '{{ participant.full_name }}', description: t('admin.fields.fullName') },
                { variable: '{{ participant.address_line1 }}', description: t('admin.fields.addressLine1') },
                { variable: '{{ participant.address_line2 }}', description: t('admin.fields.addressLine2') },
                { variable: '{{ participant.postal_code }}', description: t('admin.fields.postalCode') },
                { variable: '{{ participant.city }}', description: t('admin.fields.city') },
                { variable: '{{ participant.phone }}', description: t('admin.fields.phone') },
                { variable: '{{ participant.email }}', description: t('admin.fields.email') },
            ],
        },
        {
            title: t('admin.fields.zev'),
            fields: [
                { variable: '{{ zev.name }}', description: t('admin.fields.zevName') },
                { variable: '{{ zev.get_zev_type_display }}', description: t('admin.fields.zevType') },
                { variable: '{{ zev.grid_operator }}', description: t('admin.fields.gridOperator') },
                { variable: '{{ zev.vat_number }}', description: t('admin.fields.vatNumber') },
                { variable: '{{ zev.bank_iban }}', description: t('admin.fields.bankIban') },
            ],
        },
        {
            title: t('admin.fields.ownerParticipant'),
            fields: [
                { variable: '{{ owner_participant.full_name }}', description: t('admin.fields.fullName') },
                { variable: '{{ owner_participant.address_line1 }}', description: t('admin.fields.addressLine1') },
                { variable: '{{ owner_participant.address_line2 }}', description: t('admin.fields.addressLine2') },
                { variable: '{{ owner_participant.postal_code }}', description: t('admin.fields.postalCode') },
                { variable: '{{ owner_participant.city }}', description: t('admin.fields.city') },
                { variable: '{{ owner_participant.email }}', description: t('admin.fields.email') },
            ],
        },
        {
            title: t('admin.fields.meteringPoints'),
            fields: [
                { variable: '{% for mp in consumption_mps %}', description: t('admin.fields.consumptionMpLoop') },
                { variable: '{% for mp in production_mps %}', description: t('admin.fields.productionMpLoop') },
                { variable: '{{ mp.meter_id }}', description: t('admin.fields.meterId') },
                { variable: '{{ mp.location_description }}', description: t('admin.fields.meterLocation') },
            ],
        },
        {
            title: t('admin.fields.tariffs'),
            fields: [
                { variable: '{% for row in local_tariff_rows %}', description: t('admin.fields.tariffLoop') },
                { variable: '{{ row.name }}', description: t('admin.fields.tariffName') },
                { variable: '{{ row.rate_rp }}', description: t('admin.fields.tariffRate') },
                { variable: '{{ row.rate_description }}', description: t('admin.fields.tariffRateDesc') },
                { variable: '{{ row.pct }}', description: t('admin.fields.tariffPct') },
                { variable: '{{ row.unit }}', description: t('admin.fields.tariffUnit') },
                { variable: '{{ row.valid_from }}', description: t('admin.fields.tariffValidFrom') },
                { variable: '{{ row.valid_to }}', description: t('admin.fields.tariffValidTo') },
                { variable: '{{ row.validity }}', description: t('admin.fields.tariffValidity') },
                { variable: '{{ row.notes }}', description: t('admin.fields.tariffNotes') },
                { variable: '{{ local_tariff_notes }}', description: t('admin.fields.localTariffNotes') },
            ],
        },
        {
            title: t('admin.fields.tariffClause'),
            fields: [
                { variable: '{{ tariff_rule }}', description: t('admin.fields.tariffRule') },
                { variable: '{{ tariff_pct_line }}', description: t('admin.fields.tariffPctLine') },
                { variable: '{{ tariff_reference_product }}', description: t('admin.fields.tariffReferenceProduct') },
            ],
        },
        {
            title: t('admin.fields.contractDetails'),
            fields: [
                { variable: '{{ contract_date }}', description: t('admin.fields.contractDate') },
                { variable: '{{ participation_start }}', description: t('admin.fields.participationStart') },
                { variable: '{{ document_id }}', description: t('admin.fields.documentId') },
                { variable: '{{ vat_rate_display }}', description: t('admin.fields.vatRateDisplay') },
                { variable: '{{ billing_interval_display }}', description: t('admin.fields.billingInterval') },
                { variable: '{{ additional_contract_notes }}', description: t('admin.fields.additionalNotes') },
                { variable: '{{ lang }}', description: t('admin.fields.languageCode') },
            ],
        },
        {
            title: t('admin.fields.translations'),
            fields: [
                { variable: '{{ tr.<key> }}', description: t('admin.fields.trDescription') },
            ],
        },
    ]

    const annualStatementFieldGroups: FieldGroup[] = [
        {
            title: t('admin.fields.annualStatementData'),
            fields: [
                { variable: '{{ year }}', description: t('admin.fields.annualYear') },
                { variable: '{{ lang }}', description: t('admin.fields.languageCode') },
            ],
        },
        {
            title: t('admin.fields.participant'),
            fields: [
                { variable: '{{ participant.full_name }}', description: t('admin.fields.fullName') },
                { variable: '{{ participant.address_line1 }}', description: t('admin.fields.addressLine1') },
                { variable: '{{ participant.address_line2 }}', description: t('admin.fields.addressLine2') },
                { variable: '{{ participant.postal_code }}', description: t('admin.fields.postalCode') },
                { variable: '{{ participant.city }}', description: t('admin.fields.city') },
            ],
        },
        {
            title: t('admin.fields.zev'),
            fields: [
                { variable: '{{ zev.name }}', description: t('admin.fields.zevName') },
                { variable: '{{ zev.vat_number }}', description: t('admin.fields.vatNumber') },
            ],
        },
        {
            title: t('admin.fields.ownerParticipant'),
            fields: [
                { variable: '{{ owner_participant.full_name }}', description: t('admin.fields.fullName') },
                { variable: '{{ owner_participant.address_line1 }}', description: t('admin.fields.addressLine1') },
                { variable: '{{ owner_participant.postal_code }}', description: t('admin.fields.postalCode') },
                { variable: '{{ owner_participant.city }}', description: t('admin.fields.city') },
            ],
        },
        {
            title: t('admin.fields.annualTotals'),
            fields: [
                { variable: '{{ totals.total_consumed_kwh }}', description: t('admin.fields.annualTotalConsumed') },
                { variable: '{{ totals.from_zev_kwh }}', description: t('admin.fields.annualFromZev') },
                { variable: '{{ totals.from_grid_kwh }}', description: t('admin.fields.annualFromGrid') },
                { variable: '{{ totals.total_produced_kwh }}', description: t('admin.fields.annualTotalProduced') },
                { variable: '{{ totals.self_sufficiency_pct }}', description: t('admin.fields.annualSelfSufficiency') },
            ],
        },
        {
            title: t('admin.fields.annualMonthlyData'),
            fields: [
                { variable: '{% for row in monthly_data %}', description: t('admin.fields.annualMonthlyLoop') },
                { variable: '{{ row.month_label }}', description: t('admin.fields.annualMonthLabel') },
                { variable: '{{ row.consumed_kwh }}', description: t('admin.fields.annualMonthConsumed') },
                { variable: '{{ row.from_zev_kwh }}', description: t('admin.fields.annualMonthFromZev') },
                { variable: '{{ row.from_grid_kwh }}', description: t('admin.fields.annualMonthFromGrid') },
                { variable: '{{ row.produced_kwh }}', description: t('admin.fields.annualMonthProduced') },
                { variable: '{{ row.self_sufficiency_pct }}', description: t('admin.fields.annualMonthSelfSufficiency') },
            ],
        },
        {
            title: t('admin.fields.annualInvoices'),
            fields: [
                { variable: '{% for inv in invoices %}', description: t('admin.fields.annualInvoiceLoop') },
                { variable: '{{ inv.invoice_number }}', description: t('admin.fields.invoiceNumber') },
                { variable: '{{ inv.period_start_formatted }}', description: t('admin.fields.periodStart') },
                { variable: '{{ inv.period_end_formatted }}', description: t('admin.fields.periodEnd') },
                { variable: '{{ inv.subtotal_chf }}', description: t('admin.fields.subtotal') },
                { variable: '{{ inv.vat_chf }}', description: t('admin.fields.vatAmount') },
                { variable: '{{ inv.total_chf }}', description: t('admin.fields.total') },
                { variable: '{{ invoice_totals.subtotal_chf }}', description: t('admin.fields.annualInvoiceTotalSubtotal') },
                { variable: '{{ invoice_totals.total_chf }}', description: t('admin.fields.annualInvoiceTotalTotal') },
            ],
        },
        {
            title: t('admin.fields.chartsAndSavings'),
            fields: [
                { variable: '{{ monthly_chart_svg|safe }}', description: t('admin.fields.annualMonthlyChart') },
                { variable: '{{ savings.local_kwh }}', description: t('admin.fields.savingsLocalKwh') },
                { variable: '{{ savings.local_chf }}', description: t('admin.fields.annualSavingsLocalChf') },
                { variable: '{{ savings.local_rp }}', description: t('admin.fields.annualSavingsLocalRp') },
                { variable: '{{ savings.grid_rp }}', description: t('admin.fields.annualSavingsGridRp') },
                { variable: '{{ savings.hypothetical_chf }}', description: t('admin.fields.annualSavingsHypothetical') },
                { variable: '{{ savings.saved_chf }}', description: t('admin.fields.savingsSavedChf') },
            ],
        },
        {
            title: t('admin.fields.formattedDates'),
            fields: [
                { variable: '{{ formatted_dates.statement_date }}', description: t('admin.fields.annualStatementDate') },
            ],
        },
        {
            title: t('admin.fields.translations'),
            fields: [
                { variable: '{{ tr.<key> }}', description: t('admin.fields.trDescription') },
            ],
        },
    ]

    const invoiceTemplateQuery = useQuery({
        queryKey: queryKeys.admin.invoicePdfTemplate(),
        queryFn: fetchInvoicePdfTemplate,
        enabled: activeTab === 'invoice',
    })

    const saveInvoiceMutation = useMutation({
        mutationFn: updateInvoicePdfTemplate,
        onSuccess: (result) => {
            pushToast(result.detail ?? t('common.save'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.admin.invoicePdfTemplate() })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    const resetInvoiceMutation = useMutation({
        mutationFn: resetInvoicePdfTemplate,
        onSuccess: (result) => {
            pushToast(result.detail ?? t('admin.resetToDefault'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.admin.invoicePdfTemplate() })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    const contractTemplateQuery = useQuery({
        queryKey: queryKeys.admin.contractPdfTemplate(),
        queryFn: fetchContractPdfTemplate,
        enabled: activeTab === 'contract',
    })

    const saveContractMutation = useMutation({
        mutationFn: updateContractPdfTemplate,
        onSuccess: (result) => {
            pushToast(result.detail ?? t('common.save'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.admin.contractPdfTemplate() })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    const resetContractMutation = useMutation({
        mutationFn: resetContractPdfTemplate,
        onSuccess: (result) => {
            pushToast(result.detail ?? t('admin.resetToDefault'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.admin.contractPdfTemplate() })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    const annualStatementTemplateQuery = useQuery({
        queryKey: queryKeys.admin.annualStatementPdfTemplate(),
        queryFn: fetchAnnualStatementPdfTemplate,
        enabled: activeTab === 'annual_statement',
    })

    const saveAnnualStatementMutation = useMutation({
        mutationFn: updateAnnualStatementPdfTemplate,
        onSuccess: (result) => {
            pushToast(result.detail ?? t('common.save'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.admin.annualStatementPdfTemplate() })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    const resetAnnualStatementMutation = useMutation({
        mutationFn: resetAnnualStatementPdfTemplate,
        onSuccess: (result) => {
            pushToast(result.detail ?? t('admin.resetToDefault'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.admin.annualStatementPdfTemplate() })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('nav.adminConsole')}</p>
                <h2>{t('admin.pdfTemplates')}</h2>
                <p className="muted">
                    {t('admin.pdfTemplatesDescription')}
                </p>
            </header>

            <div
                role="tablist"
                aria-label={t('admin.pdfTemplates')}
                onKeyDown={handleTabKeyDown}
                style={{ display: 'flex', gap: '1rem', borderBottom: '1px solid var(--border-default)', marginBottom: '1.5rem' }}
            >
                {PDF_TEMPLATE_TABS.map((tab) => (
                    <button
                        key={tab}
                        type="button"
                        role="tab"
                        id={`pdf-template-tab-${tab}`}
                        aria-selected={activeTab === tab}
                        aria-controls={`pdf-template-panel-${tab}`}
                        tabIndex={activeTab === tab ? 0 : -1}
                        onClick={() => setActiveTab(tab)}
                        style={{
                            background: 'transparent',
                            color: activeTab === tab ? 'var(--text-primary)' : 'var(--text-muted)',
                            padding: '0.75rem 1rem',
                            fontSize: '1rem',
                            fontWeight: activeTab === tab ? 600 : 400,
                            cursor: 'pointer',
                            border: 'none',
                            borderBlockEnd: activeTab === tab ? '2px solid var(--interactive)' : 'none',
                        }}
                    >
                        {tabLabels[tab]}
                    </button>
                ))}
            </div>

            {activeTab === 'invoice' && (
                <div
                    id="pdf-template-panel-invoice"
                    role="tabpanel"
                    aria-labelledby="pdf-template-tab-invoice"
                >
                    <TemplateEditor
                        data={invoiceTemplateQuery.data}
                        isLoading={invoiceTemplateQuery.isLoading}
                        isError={invoiceTemplateQuery.isError}
                        onSave={(content) => saveInvoiceMutation.mutate(content)}
                        onReset={() => resetInvoiceMutation.mutate()}
                        isSaving={saveInvoiceMutation.isPending}
                        isResetting={resetInvoiceMutation.isPending}
                        title={t('admin.invoiceTemplate')}
                        fieldGroups={invoiceFieldGroups}
                        templateType="invoice"
                    />
                </div>
            )}

            {activeTab === 'contract' && (
                <div
                    id="pdf-template-panel-contract"
                    role="tabpanel"
                    aria-labelledby="pdf-template-tab-contract"
                >
                    <TemplateEditor
                        data={contractTemplateQuery.data}
                        isLoading={contractTemplateQuery.isLoading}
                        isError={contractTemplateQuery.isError}
                        onSave={(content) => saveContractMutation.mutate(content)}
                        onReset={() => resetContractMutation.mutate()}
                        isSaving={saveContractMutation.isPending}
                        isResetting={resetContractMutation.isPending}
                        title={t('admin.contractTemplate')}
                        fieldGroups={contractFieldGroups}
                        templateType="contract"
                    />
                </div>
            )}

            {activeTab === 'annual_statement' && (
                <div
                    id="pdf-template-panel-annual_statement"
                    role="tabpanel"
                    aria-labelledby="pdf-template-tab-annual_statement"
                >
                    <TemplateEditor
                        data={annualStatementTemplateQuery.data}
                        isLoading={annualStatementTemplateQuery.isLoading}
                        isError={annualStatementTemplateQuery.isError}
                        onSave={(content) => saveAnnualStatementMutation.mutate(content)}
                        onReset={() => resetAnnualStatementMutation.mutate()}
                        isSaving={saveAnnualStatementMutation.isPending}
                        isResetting={resetAnnualStatementMutation.isPending}
                        title={t('admin.annualStatementTemplate')}
                        fieldGroups={annualStatementFieldGroups}
                        templateType="annual_statement"
                    />
                </div>
            )}
        </div>
    )
}
