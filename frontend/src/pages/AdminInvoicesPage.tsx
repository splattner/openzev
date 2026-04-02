import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { DataGrid, type GridColDef, type GridRenderCellParams } from '@mui/x-data-grid'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { deleteInvoice, fetchInvoices, formatApiError } from '../lib/api'
import { useToast } from '../lib/toast'
import type { Invoice } from '../types/api'

function invoiceStatusBadgeClass(status: string): string {
    if (status === 'paid') return 'badge badge-success'
    if (status === 'cancelled') return 'badge badge-danger'
    if (status === 'approved' || status === 'sent') return 'badge badge-info'
    return 'badge badge-neutral'
}

function humanizeStatus(status: string): string {
    return status.replace('_', ' ').replace(/^./, (char) => char.toUpperCase())
}

export function AdminInvoicesPage() {
    const { t } = useTranslation()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { settings } = useAppSettings()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const invoicesQuery = useQuery({
        queryKey: ['invoices'],
        queryFn: fetchInvoices,
    })

    const deleteMutation = useMutation({
        mutationFn: (id: string) => deleteInvoice(id),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['invoices'] })
            pushToast(t('adminInvoices.deleted'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error), 'error'),
    })

    const handleDelete = (invoice: Invoice) => {
        confirm({
            title: t('adminInvoices.confirmDeleteTitle'),
            message: t('adminInvoices.confirmDeleteMessage', {
                number: invoice.invoice_number,
                participant: invoice.participant_name,
            }),
            isDangerous: true,
            onConfirm: async () => {
                await deleteMutation.mutateAsync(invoice.id)
            },
        })
    }

    const invoices = useMemo(() => invoicesQuery.data?.results ?? [], [invoicesQuery.data?.results])

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

    const columns: GridColDef[] = [
        {
            field: 'invoice_number',
            headerName: t('adminInvoices.number'),
            flex: 1,
            minWidth: 150,
            filterable: true,
            renderCell: (params: GridRenderCellParams<Invoice>) => <code>{String(params.value ?? '')}</code>,
        },
        {
            field: 'zev_name',
            headerName: t('adminInvoices.zev'),
            flex: 1.2,
            minWidth: 170,
            filterable: true,
        },
        {
            field: 'participant_name',
            headerName: t('adminInvoices.participant'),
            flex: 1.2,
            minWidth: 170,
            filterable: true,
        },
        {
            field: 'period_sort',
            headerName: t('adminInvoices.period'),
            flex: 1.4,
            minWidth: 210,
            filterable: true,
            renderCell: (params: GridRenderCellParams<Invoice>) =>
                `${formatShortDate(params.row.period_start, settings)} - ${formatShortDate(params.row.period_end, settings)}`,
        },
        {
            field: 'total_value',
            headerName: t('adminInvoices.total'),
            type: 'number',
            flex: 0.9,
            minWidth: 130,
            filterable: true,
            renderCell: (params: GridRenderCellParams<Invoice>) => `${params.row.total_chf} CHF`,
        },
        {
            field: 'status',
            headerName: t('adminInvoices.status'),
            flex: 0.9,
            minWidth: 130,
            filterable: true,
            type: 'singleSelect',
            valueOptions: ['draft', 'approved', 'sent', 'paid', 'cancelled'],
            renderCell: (params: GridRenderCellParams<Invoice>) => (
                <span className={invoiceStatusBadgeClass(String(params.value ?? ''))}>{humanizeStatus(String(params.value ?? ''))}</span>
            ),
        },
        {
            field: 'actions',
            headerName: '',
            sortable: false,
            filterable: false,
            width: 120,
            align: 'center',
            renderCell: (params: GridRenderCellParams<Invoice>) => (
                <button
                    type="button"
                    className="button button-danger"
                    onClick={() => handleDelete(params.row)}
                    disabled={deleteMutation.isPending}
                    title={t('adminInvoices.delete')}
                >
                    {t('adminInvoices.delete')}
                </button>
            ),
        },
    ]

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
                    <div style={{ width: '100%' }}>
                        <DataGrid
                            rows={rows}
                            columns={columns}
                            getRowId={(row) => row.id}
                            loading={invoicesQuery.isLoading}
                            disableRowSelectionOnClick
                            showToolbar
                            initialState={{
                                sorting: {
                                    sortModel: [{ field: 'period_sort', sort: 'desc' }],
                                },
                                pagination: {
                                    paginationModel: { pageSize: 25, page: 0 },
                                },
                            }}
                            pageSizeOptions={[10, 25, 50, 100]}
                            slotProps={{
                                toolbar: {
                                    showQuickFilter: true,
                                    quickFilterProps: { debounceMs: 300 },
                                },
                            }}
                            sx={{
                                border: 0,
                                '& .MuiDataGrid-columnHeaders': {
                                    backgroundColor: '#f8fafc',
                                },
                            }}
                            localeText={{
                                toolbarQuickFilterPlaceholder: t('adminInvoices.quickFilterPlaceholder'),
                                noRowsLabel: t('adminInvoices.noFilteredResults'),
                            }}
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
