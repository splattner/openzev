import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import type { ColumnDef, ColumnFiltersState } from '@tanstack/react-table'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { DataTable } from '../components/DataTable'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { deleteInvoice, fetchInvoices } from '../lib/api/invoices'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { useToast } from '../lib/toast'
import { invoiceStatusBadgeClass } from '../features/invoices/invoiceStatus'
import type { Invoice } from '../types/api'

// Stable empty array so the useMemo below keeps a consistent dependency reference.
const EMPTY_INVOICES: Invoice[] = []

export function AdminInvoicesPage() {
    const { t } = useTranslation()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { settings } = useAppSettings()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const invoicesQuery = useQuery({
        queryKey: queryKeys.invoices.list(),
        queryFn: () => fetchInvoices(),
    })

    const deleteMutation = useMutation({
        mutationFn: (id: string) => deleteInvoice(id),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.list() })
            pushToast(t('adminInvoices.deleted'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error), 'error'),
    })

    const deleteInvoiceAsync = deleteMutation.mutateAsync
    const handleDelete = useCallback((invoice: Invoice) => {
        confirm({
            title: t('adminInvoices.confirmDeleteTitle'),
            message: t('adminInvoices.confirmDeleteMessage', {
                number: invoice.invoice_number,
                participant: invoice.participant_name,
            }),
            isDangerous: true,
            onConfirm: async () => {
                await deleteInvoiceAsync(invoice.id)
            },
        })
    }, [confirm, deleteInvoiceAsync, t])

    const invoices = invoicesQuery.data ?? EMPTY_INVOICES

    const rows = useMemo(
        () =>
            invoices.map((inv) => ({
                ...inv,
                period_display: `${formatShortDate(inv.period_start, settings)} - ${formatShortDate(inv.period_end, settings)}`,
                period_sort: `${inv.period_start}|${inv.period_end}`,
                total_value: Number.parseFloat(inv.total_chf),
            })),
        [invoices, settings],
    )

    const [search, setSearch] = useState('')
    const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])

    const filteredRows = useMemo(() => {
        const q = search.trim().toLowerCase()
        if (!q) return rows
        return rows.filter((row) =>
            row.invoice_number.toLowerCase().includes(q)
            || row.zev_name.toLowerCase().includes(q)
            || row.participant_name.toLowerCase().includes(q)
            || row.period_display.toLowerCase().includes(q)
            || row.status.toLowerCase().includes(q),
        )
    }, [rows, search])

    const columns = useMemo<ColumnDef<(typeof rows)[number], unknown>[]>(
        () => [
            {
                accessorKey: 'invoice_number',
                header: t('adminInvoices.number'),
                cell: (ctx) => <code>{ctx.getValue<string>()}</code>,
            },
            {
                accessorKey: 'zev_name',
                header: t('adminInvoices.zev'),
            },
            {
                accessorKey: 'participant_name',
                header: t('adminInvoices.participant'),
            },
            {
                accessorKey: 'period_sort',
                header: t('adminInvoices.period'),
                cell: (ctx) => `${formatShortDate(ctx.row.original.period_start, settings)} - ${formatShortDate(ctx.row.original.period_end, settings)}`,
            },
            {
                accessorKey: 'total_value',
                header: t('adminInvoices.total'),
                meta: { numeric: true },
                cell: (ctx) => `${ctx.row.original.total_chf} CHF`,
            },
            {
                accessorKey: 'status',
                header: t('adminInvoices.status'),
                filterFn: 'equalsString',
                cell: (ctx) => {
                    const status = String(ctx.getValue() ?? '')
                    return <span className={invoiceStatusBadgeClass(status)}>{status ? t(`invoice.status.${status}`) : ''}</span>
                },
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                meta: { numeric: false },
                cell: (ctx) => (
                    <button
                        type="button"
                        className="button button-danger"
                        onClick={() => handleDelete(ctx.row.original)}
                        disabled={deleteMutation.isPending}
                        title={t('adminInvoices.delete')}
                    >
                        {t('adminInvoices.delete')}
                    </button>
                ),
            },
        ],
        [t, settings, handleDelete, deleteMutation.isPending],
    )

    return (
        <div className="page-stack">
            <header>
                <p className="eyebrow">{t('adminInvoices.eyebrow')}</p>
                <h2>{t('adminInvoices.title')}</h2>
                <p className="muted">{t('adminInvoices.description')}</p>
            </header>

            <section className="card">
                {invoicesQuery.isLoading && <p>{t('adminInvoices.loading')}</p>}
                {invoicesQuery.isError && <p className="text-error">{t('adminInvoices.loadError')}</p>}
                {!invoicesQuery.isLoading && invoices.length === 0 && (
                    <p className="muted">{t('adminInvoices.empty')}</p>
                )}
                {invoices.length > 0 && (
                    <div className="page-stack" style={{ width: '100%' }}>
                        <div className="actions-row" style={{ flexWrap: 'wrap' }}>
                            <input
                                type="search"
                                placeholder={t('adminInvoices.quickFilterPlaceholder')}
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                style={{ maxWidth: '20rem' }}
                            />
                            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
                                <span className="muted">{t('adminInvoices.status')}</span>
                                <select
                                    value={String(columnFilters.find((f) => f.id === 'status')?.value ?? '')}
                                    onChange={(e) =>
                                        setColumnFilters(
                                            e.target.value
                                                ? [{ id: 'status', value: e.target.value }]
                                                : [],
                                        )
                                    }
                                    style={{ width: 'auto' }}
                                >
                                    <option value="">{t('adminInvoices.allStatuses')}</option>
                                    {(['draft', 'approved', 'sent', 'paid', 'cancelled'] as const).map((value) => (
                                        <option key={value} value={value}>{t(`invoice.status.${value}`)}</option>
                                    ))}
                                </select>
                            </label>
                        </div>
                        <DataTable
                            data={filteredRows}
                            columns={columns}
                            getRowId={(row) => row.id}
                            loading={invoicesQuery.isLoading}
                            initialSorting={[{ id: 'period_sort', desc: true }]}
                            columnFilters={columnFilters}
                            onColumnFiltersChange={setColumnFilters}
                            emptyMessage={t('adminInvoices.noFilteredResults')}
                        />
                    </div>
                )}
            </section>
            {dialog && (
                <ConfirmDialog
                    {...dialog}
                    isLoading={dialogLoading}
                    onConfirm={handleConfirm}
                    onCancel={handleCancel}
                />
            )}
        </div>
    )
}
