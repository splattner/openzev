import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
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

    const invoices = invoicesQuery.data?.results ?? []

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
                    <div className="table-responsive">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('adminInvoices.number')}</th>
                                    <th>{t('adminInvoices.zev')}</th>
                                    <th>{t('adminInvoices.participant')}</th>
                                    <th>{t('adminInvoices.period')}</th>
                                    <th>{t('adminInvoices.total')}</th>
                                    <th>{t('adminInvoices.status')}</th>
                                    <th style={{ width: 80 }}></th>
                                </tr>
                            </thead>
                            <tbody>
                                {invoices.map((inv) => (
                                    <tr key={inv.id}>
                                        <td><code>{inv.invoice_number}</code></td>
                                        <td>{inv.zev_name}</td>
                                        <td>{inv.participant_name}</td>
                                        <td>{inv.period_start} – {inv.period_end}</td>
                                        <td style={{ textAlign: 'right' }}>{inv.total_chf} CHF</td>
                                        <td><span className={invoiceStatusBadgeClass(inv.status)}>{humanizeStatus(inv.status)}</span></td>
                                        <td>
                                            <button
                                                type="button"
                                                className="btn btn-sm btn-danger"
                                                onClick={() => handleDelete(inv)}
                                                disabled={deleteMutation.isPending}
                                                title={t('adminInvoices.delete')}
                                            >
                                                {t('adminInvoices.delete')}
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
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
