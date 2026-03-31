import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
    fetchContractPdfTemplate,
    fetchInvoicePdfTemplate,
    previewPdfTemplate,
    resetContractPdfTemplate,
    resetInvoicePdfTemplate,
    updateContractPdfTemplate,
    updateInvoicePdfTemplate,
} from '../lib/api'
import type { PdfTemplateResponse } from '../types/api'
import { useToast } from '../lib/toast'

interface FieldGroup {
    title: string
    fields: { variable: string; description: string }[]
}

function FieldReference({ groups }: { groups: FieldGroup[] }) {
    const { t } = useTranslation()
    return (
        <aside className="card page-stack" style={{ minWidth: 400, maxHeight: '80vh', overflowY: 'auto' }}>
            <h4 style={{ margin: 0 }}>{t('admin.availableFields')}</h4>
            {groups.map((group) => (
                <div key={group.title}>
                    <h5 style={{ margin: '0.75rem 0 0.25rem' }}>{group.title}</h5>
                    <table style={{ width: '100%', fontSize: '0.82rem', borderCollapse: 'collapse' }}>
                        <tbody>
                            {group.fields.map((f) => (
                                <tr key={f.variable} style={{ borderBottom: '1px solid var(--color-border, #e5e7eb)' }}>
                                    <td style={{ padding: '0.25rem 0.5rem 0.25rem 0', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                                        {f.variable}
                                    </td>
                                    <td className="muted" style={{ padding: '0.25rem 0' }}>
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
        <div style={{ position: 'relative' }}>
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
                            style={{
                                pointerEvents: 'auto',
                                cursor: 'help',
                                borderRadius: '3px',
                                background: 'rgba(0, 102, 204, 0.08)',
                            }}
                            onMouseEnter={(e) => {
                                const rect = (e.target as HTMLElement).getBoundingClientRect()
                                const container = (e.target as HTMLElement).closest('[style*="position: relative"]')
                                const containerRect = container?.getBoundingClientRect() ?? rect
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
                    style={{
                        position: 'absolute',
                        left: tooltip.x,
                        top: tooltip.y,
                        background: 'var(--color-bg-tooltip, #1e293b)',
                        color: '#fff',
                        padding: '0.25rem 0.5rem',
                        borderRadius: '4px',
                        fontSize: '0.78rem',
                        whiteSpace: 'nowrap',
                        pointerEvents: 'none',
                        zIndex: 10,
                        boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
                    }}
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
    templateType: 'invoice' | 'contract'
}) {
    const { t } = useTranslation()
    const [content, setContent] = useState('')
    const [showPreview, setShowPreview] = useState(false)
    const [previewHtml, setPreviewHtml] = useState('')
    const [previewLoading, setPreviewLoading] = useState(false)
    const [previewError, setPreviewError] = useState('')
    const iframeRef = useRef<HTMLIFrameElement>(null)

    useEffect(() => {
        if (data?.content != null) {
            setContent(data.content)
        }
    }, [data])

    const handlePreview = useCallback(async () => {
        if (showPreview) {
            setShowPreview(false)
            return
        }
        setPreviewLoading(true)
        setPreviewError('')
        try {
            const result = await previewPdfTemplate(content, templateType)
            setPreviewHtml(result.html)
            setShowPreview(true)
        } catch {
            setPreviewError(t('admin.previewError'))
        } finally {
            setPreviewLoading(false)
        }
    }, [showPreview, content, templateType, t])

    useEffect(() => {
        if (showPreview && iframeRef.current) {
            const doc = iframeRef.current.contentDocument
            if (doc) {
                doc.open()
                doc.write(previewHtml)
                doc.close()
            }
        }
    }, [showPreview, previewHtml])

    return (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 420px', gap: '1.5rem', alignItems: 'start' }}>
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
                        <p className="muted">{data.template_name}</p>
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
                        {showPreview && (
                            <div>
                                <span className="muted" style={{ display: 'block', marginBottom: '0.5rem' }}>{t('admin.previewLabel')}</span>
                                <iframe
                                    ref={iframeRef}
                                    title={t('admin.previewLabel')}
                                    sandbox="allow-same-origin"
                                    style={{
                                        width: '100%',
                                        minHeight: '28rem',
                                        height: '70vh',
                                        border: '1px solid #cbd5e1',
                                        borderRadius: '0.9rem',
                                        background: '#fff',
                                    }}
                                />
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
                                disabled={previewLoading}
                                onClick={handlePreview}
                            >
                                {previewLoading
                                    ? t('common.loading')
                                    : showPreview
                                      ? t('admin.backToEditor')
                                      : t('admin.preview')}
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
    const [activeTab, setActiveTab] = useState<'invoice' | 'contract'>('invoice')

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
                { variable: '{{ zev.owner.email }}', description: t('admin.fields.email') },
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
                { variable: '{{ local_tariff_notes }}', description: t('admin.fields.localTariffNotes') },
            ],
        },
        {
            title: t('admin.fields.contractDetails'),
            fields: [
                { variable: '{{ contract_date }}', description: t('admin.fields.contractDate') },
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

    const invoiceTemplateQuery = useQuery({
        queryKey: ['admin-pdf-template'],
        queryFn: fetchInvoicePdfTemplate,
    })

    const saveInvoiceMutation = useMutation({
        mutationFn: updateInvoicePdfTemplate,
        onSuccess: (result) => {
            pushToast(result.detail ?? t('common.save'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['admin-pdf-template'] })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    const resetInvoiceMutation = useMutation({
        mutationFn: resetInvoicePdfTemplate,
        onSuccess: (result) => {
            pushToast(result.detail ?? t('admin.resetToDefault'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['admin-pdf-template'] })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    const contractTemplateQuery = useQuery({
        queryKey: ['admin-contract-pdf-template'],
        queryFn: fetchContractPdfTemplate,
    })

    const saveContractMutation = useMutation({
        mutationFn: updateContractPdfTemplate,
        onSuccess: (result) => {
            pushToast(result.detail ?? t('common.save'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['admin-contract-pdf-template'] })
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    const resetContractMutation = useMutation({
        mutationFn: resetContractPdfTemplate,
        onSuccess: (result) => {
            pushToast(result.detail ?? t('admin.resetToDefault'), 'success')
            void queryClient.invalidateQueries({ queryKey: ['admin-contract-pdf-template'] })
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

            <div style={{ display: 'flex', gap: '1rem', borderBottom: '1px solid var(--color-border, #e5e7eb)', marginBottom: '1.5rem' }}>
                <button
                    onClick={() => setActiveTab('invoice')}
                    style={{
                        background: 'transparent',
                        color: activeTab === 'invoice' ? 'var(--color-text, #000)' : 'var(--color-text-muted, #888)',
                        borderBottom: activeTab === 'invoice' ? '2px solid var(--color-primary, #0066cc)' : 'none',
                        padding: '0.75rem 1rem',
                        fontSize: '1rem',
                        fontWeight: activeTab === 'invoice' ? 600 : 400,
                        cursor: 'pointer',
                        border: 'none',
                        borderBlockEnd: activeTab === 'invoice' ? '2px solid var(--color-primary, #0066cc)' : 'none',
                    }}
                >
                    {t('admin.invoiceTemplate')}
                </button>
                <button
                    onClick={() => setActiveTab('contract')}
                    style={{
                        background: 'transparent',
                        color: activeTab === 'contract' ? 'var(--color-text, #000)' : 'var(--color-text-muted, #888)',
                        borderBottom: activeTab === 'contract' ? '2px solid var(--color-primary, #0066cc)' : 'none',
                        padding: '0.75rem 1rem',
                        fontSize: '1rem',
                        fontWeight: activeTab === 'contract' ? 600 : 400,
                        cursor: 'pointer',
                        border: 'none',
                        borderBlockEnd: activeTab === 'contract' ? '2px solid var(--color-primary, #0066cc)' : 'none',
                    }}
                >
                    {t('admin.contractTemplate')}
                </button>
            </div>

            {activeTab === 'invoice' && (
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
            )}

            {activeTab === 'contract' && (
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
            )}
        </div>
    )
}
