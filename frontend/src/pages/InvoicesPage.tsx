import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
    approveInvoice,
    cancelInvoice,
    deleteInvoice,
    fetchEmailLogs,
    fetchInvoices,
    fetchParticipants,
    fetchZevs,
    generateInvoice,
    generateInvoicePdf,
    generateInvoicesForZev,
    markInvoicePaid,
    markInvoiceSent,
    retryFailedEmail,
    sendInvoiceEmail,
} from '../lib/api'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useToast } from '../lib/toast'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { EmailLogsModal } from '../components/EmailLogsModal'
import { DateRangeShortcutPicker } from '../components/DateRangeShortcutPicker'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import {
    daysAgoIso,
    todayIso,
} from '../lib/dateRangePresets'
import type { EmailLog } from '../types/api'

export function InvoicesPage() {
    const EMAIL_STATUS_POLL_TIMEOUT_MS = 90_000
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { selectedZevId, selectedZev } = useManagedZev()
    const isManagedScope = user?.role === 'admin' || user?.role === 'zev_owner'
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const [emailPollingInvoiceId, setEmailPollingInvoiceId] = useState<string | null>(null)
    const [emailPollingStartedAt, setEmailPollingStartedAt] = useState<number | null>(null)
    const { data, isLoading, isError } = useQuery({
        queryKey: ['invoices'],
        queryFn: fetchInvoices,
        refetchInterval: emailPollingInvoiceId ? 2500 : false,
        refetchIntervalInBackground: true,
    })
    const participantsQuery = useQuery({ queryKey: ['participants'], queryFn: fetchParticipants })
    const zevsQuery = useQuery({ queryKey: ['zevs'], queryFn: fetchZevs })

    const [selectedEmailLogs, setSelectedEmailLogs] = useState<EmailLog[]>([])
    const [showEmailModal, setShowEmailModal] = useState(false)
    const [selectedInvoiceNumber, setSelectedInvoiceNumber] = useState('')
    const [retiringEmailId, setRetiringEmailId] = useState<string | null>(null)

    const today = todayIso()
    const monthAgo = daysAgoIso(30)

    const [singleForm, setSingleForm] = useState({
        participant_id: '',
        period_start: monthAgo,
        period_end: today,
    })
    const [bulkForm, setBulkForm] = useState({
        zev_id: '',
        period_start: monthAgo,
        period_end: today,
    })

    const filteredParticipants = (participantsQuery.data?.results ?? []).filter(
        (participant) => !isManagedScope || !selectedZevId || participant.zev === selectedZevId,
    )
    const filteredZevs = (zevsQuery.data?.results ?? []).filter(
        (zev) => !isManagedScope || !selectedZevId || zev.id === selectedZevId,
    )
    const invoices = (data?.results ?? []).filter(
        (invoice) => !isManagedScope || !selectedZevId || invoice.zev === selectedZevId,
    )

    const singleMutation = useMutation({
        mutationFn: generateInvoice,
        onSuccess: () => {
            pushToast('Invoice generated.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoices'] })
        },
        onError: () => pushToast('Failed to generate invoice.', 'error'),
    })

    const bulkMutation = useMutation({
        mutationFn: generateInvoicesForZev,
        onSuccess: (result) => {
            pushToast(`Generated ${result.length} invoice(s).`, 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoices'] })
        },
        onError: () => pushToast('Failed to generate ZEV invoices.', 'error'),
    })

    const pdfMutation = useMutation({
        mutationFn: generateInvoicePdf,
        onSuccess: () => {
            pushToast('PDF generated.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoices'] })
        },
        onError: () => pushToast('Failed to generate PDF.', 'error'),
    })

    const emailMutation = useMutation({
        mutationFn: ({ invoiceId, email }: { invoiceId: string; email?: string }) => sendInvoiceEmail(invoiceId, email),
        onSuccess: (_result, variables) => {
            pushToast('Invoice email queued.', 'success')
            setEmailPollingInvoiceId(variables.invoiceId)
            setEmailPollingStartedAt(Date.now())
            void queryClient.invalidateQueries({ queryKey: ['invoices'] })
        },
        onError: () => pushToast('Failed to queue email.', 'error'),
    })

    const approveMutation = useMutation({
        mutationFn: approveInvoice,
        onSuccess: () => {
            pushToast('Invoice approved.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoices'] })
        },
        onError: () => pushToast('Failed to approve invoice.', 'error'),
    })

    const sendMutation = useMutation({
        mutationFn: markInvoiceSent,
        onSuccess: () => {
            pushToast('Invoice marked as sent.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoices'] })
        },
        onError: () => pushToast('Failed to mark invoice as sent.', 'error'),
    })

    const payMutation = useMutation({
        mutationFn: markInvoicePaid,
        onSuccess: () => {
            pushToast('Invoice marked as paid.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoices'] })
        },
        onError: () => pushToast('Failed to mark invoice as paid.', 'error'),
    })

    const cancelMutation = useMutation({
        mutationFn: cancelInvoice,
        onSuccess: () => {
            pushToast('Invoice cancelled.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoices'] })
        },
        onError: () => pushToast('Failed to cancel invoice.', 'error'),
    })

    const deleteMutation = useMutation({
        mutationFn: deleteInvoice,
        onSuccess: () => {
            pushToast('Invoice deleted.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoices'] })
        },
        onError: () => pushToast('Failed to delete invoice.', 'error'),
    })

    const retryEmailMutation = useMutation({
        mutationFn: ({ invoiceId, emailLogId }: { invoiceId: string; emailLogId: string }) =>
            retryFailedEmail(invoiceId, emailLogId),
        onSuccess: () => {
            pushToast('Email retry queued.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['invoices'] })
        },
        onError: () => pushToast('Failed to retry email.', 'error'),
    })

    const openEmailLogs = async (invoiceId: string, invoiceNumber: string) => {
        try {
            const logs = await fetchEmailLogs(invoiceId)
            setSelectedEmailLogs(logs)
            setSelectedInvoiceNumber(invoiceNumber)
            setShowEmailModal(true)
        } catch {
            pushToast('Failed to load email logs.', 'error')
        }
    }

    const handleRetryEmail = (emailLogId: string) => {
        if (!selectedInvoiceNumber) return
        setRetiringEmailId(emailLogId)
        retryEmailMutation.mutate(
            { invoiceId: invoices.find((inv) => inv.invoice_number === selectedInvoiceNumber)?.id || '', emailLogId },
            {
                onSettled: () => setRetiringEmailId(null),
            }
        )
    }

    const handleCancelClick = (invoiceId: string) => {
        confirm({
            title: 'Cancel invoice?',
            message: 'This action cannot be undone. The invoice will be marked as cancelled.',
            confirmText: 'Cancel invoice',
            cancelText: 'Keep invoice',
            isDangerous: true,
            onConfirm: async () => {
                await new Promise<void>((resolve, reject) => {
                    cancelMutation.mutate(invoiceId, {
                        onSuccess: () => resolve(),
                        onError: () => reject(),
                    })
                })
            },
        })
    }

    const handlePayClick = (invoiceId: string) => {
        confirm({
            title: 'Mark as paid?',
            message: 'This transitions the invoice to locked status. Further changes will not be possible.',
            confirmText: 'Mark as paid',
            cancelText: 'Not yet',
            isDangerous: true,
            onConfirm: async () => {
                await new Promise<void>((resolve, reject) => {
                    payMutation.mutate(invoiceId, {
                        onSuccess: () => resolve(),
                        onError: () => reject(),
                    })
                })
            },
        })
    }

    useEffect(() => {
        if (!emailPollingInvoiceId) return
        const trackedInvoice = invoices.find((invoice) => invoice.id === emailPollingInvoiceId)
        if (trackedInvoice?.status === 'sent') {
            setEmailPollingInvoiceId(null)
            setEmailPollingStartedAt(null)
        }
    }, [invoices, emailPollingInvoiceId])

    useEffect(() => {
        if (!emailPollingInvoiceId || !emailPollingStartedAt) return
        const timeoutId = window.setTimeout(() => {
            setEmailPollingInvoiceId(null)
            setEmailPollingStartedAt(null)
            pushToast('Email was queued, but status update is taking longer than expected.', 'error')
        }, EMAIL_STATUS_POLL_TIMEOUT_MS)

        return () => {
            window.clearTimeout(timeoutId)
        }
    }, [emailPollingInvoiceId, emailPollingStartedAt, pushToast])

    function submitSingle(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!singleForm.participant_id) {
            pushToast('Select a participant.', 'error')
            return
        }
        singleMutation.mutate(singleForm)
    }

    function submitBulk(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        const zevForSubmit = isManagedScope ? selectedZevId : bulkForm.zev_id
        if (!zevForSubmit) {
            pushToast('Select a ZEV.', 'error')
            return
        }
        bulkMutation.mutate({ ...bulkForm, zev_id: zevForSubmit })
    }

    const handleDeleteClick = (invoiceId: string, invoiceNumber: string, invoiceStatus: string) => {
        const isAdminDeletingLockedInvoice =
            user?.role === 'admin' && invoiceStatus !== 'draft' && invoiceStatus !== 'cancelled'

        confirm({
            title: 'Delete invoice?',
            message: isAdminDeletingLockedInvoice
                ? `Invoice ${invoiceNumber} is ${invoiceStatus.toUpperCase()} and will be permanently deleted. This can affect accounting/audit trails and cannot be undone.`
                : `Invoice ${invoiceNumber} will be permanently deleted.`,
            confirmText: 'Delete invoice',
            cancelText: 'Keep invoice',
            isDangerous: true,
            onConfirm: async () => {
                await new Promise<void>((resolve, reject) => {
                    deleteMutation.mutate(invoiceId, {
                        onSuccess: () => resolve(),
                        onError: () => reject(),
                    })
                })
            },
        })
    }

    if (isLoading) return <div className="card">Loading invoices...</div>
    if (isError) return <div className="card error-banner">Failed to load invoices.</div>

    return (
        <div className="page-stack">
            <header>
                <h2>Invoices</h2>
                <p className="muted">Drafts, approved invoices, and sent billing documents.</p>
            </header>

            <section className="card page-stack">
                <h3>Generate invoices</h3>

                <form className="inline-form grid grid-4" onSubmit={submitSingle}>
                    <label>
                        <span>Participant</span>
                        <select
                            value={singleForm.participant_id}
                            onChange={(event) => setSingleForm((prev) => ({ ...prev, participant_id: event.target.value }))}
                        >
                            <option value="">Select participant</option>
                            {filteredParticipants.map((participant) => (
                                <option key={participant.id} value={participant.id}>
                                    {participant.first_name} {participant.last_name}
                                </option>
                            ))}
                        </select>
                    </label>
                    <DateRangeShortcutPicker
                        from={singleForm.period_start}
                        to={singleForm.period_end}
                        onChange={({ from, to }) => {
                            setSingleForm((prev) => ({ ...prev, period_start: from, period_end: to }))
                        }}
                    />
                    <div className="actions-row">
                        <button className="button" type="submit" disabled={singleMutation.isPending}>
                            Generate single invoice
                        </button>
                    </div>
                </form>

                <form className="inline-form grid grid-4" onSubmit={submitBulk}>
                    {isManagedScope ? (
                        <label>
                            <span>ZEV</span>
                            <input value={selectedZev?.name ?? 'No ZEV selected'} disabled />
                        </label>
                    ) : (
                        <label>
                            <span>ZEV</span>
                            <select
                                value={bulkForm.zev_id}
                                onChange={(event) => setBulkForm((prev) => ({ ...prev, zev_id: event.target.value }))}
                            >
                                <option value="">Select ZEV</option>
                                {filteredZevs.map((zev) => (
                                    <option key={zev.id} value={zev.id}>{zev.name}</option>
                                ))}
                            </select>
                        </label>
                    )}
                    <DateRangeShortcutPicker
                        from={bulkForm.period_start}
                        to={bulkForm.period_end}
                        onChange={({ from, to }) => {
                            setBulkForm((prev) => ({ ...prev, period_start: from, period_end: to }))
                        }}
                    />
                    <div className="actions-row">
                        <button className="button" type="submit" disabled={bulkMutation.isPending}>
                            Generate all for ZEV
                        </button>
                    </div>
                </form>

            </section>

            <div className="table-card">
                <table>
                    <thead>
                        <tr>
                            <th>Invoice</th>
                            <th>Participant</th>
                            <th>Period</th>
                            <th>Status</th>
                            <th>Email</th>
                            <th>Total</th>
                            <th>PDF</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {invoices.length ? invoices.map((invoice) => {
                            const emailCount = invoice.email_logs?.length || 0
                            const sentCount = invoice.email_logs?.filter((log) => log.status === 'sent').length || 0
                            const failedCount = invoice.email_logs?.filter((log) => log.status === 'failed').length || 0

                            return (
                                <tr key={invoice.id}>
                                    <td>{invoice.invoice_number}</td>
                                    <td>{invoice.participant_name}</td>
                                    <td>{formatShortDate(invoice.period_start, settings)} → {formatShortDate(invoice.period_end, settings)}</td>
                                    <td>
                                        <strong>{invoice.status}</strong>
                                        {emailPollingInvoiceId === invoice.id && (
                                            <span
                                                className="muted"
                                                style={{ marginLeft: '0.45rem', fontSize: '0.8rem', fontWeight: 600 }}
                                            >
                                                Updating…
                                            </span>
                                        )}
                                    </td>
                                    <td style={{ fontSize: '0.9rem' }}>
                                        {emailCount === 0 ? (
                                            <span style={{ color: '#888' }}>—</span>
                                        ) : (
                                            <>
                                                <button
                                                    className="button button-primary"
                                                    style={{ fontSize: '0.75rem', padding: '0.3rem 0.5rem' }}
                                                    onClick={() => openEmailLogs(invoice.id, invoice.invoice_number)}
                                                    type="button"
                                                >
                                                    {sentCount}/{emailCount}
                                                </button>
                                                {failedCount > 0 && (
                                                    <span style={{ color: '#ef4444', marginLeft: '0.3rem', fontSize: '0.85rem', fontWeight: 'bold' }}>
                                                        ({failedCount} failed)
                                                    </span>
                                                )}
                                            </>
                                        )}
                                    </td>
                                    <td>CHF {invoice.total_chf}</td>
                                    <td>
                                        {invoice.pdf_url ? (
                                            <div className="actions-cell" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                                <a
                                                    href={invoice.pdf_url}
                                                    target="_blank"
                                                    rel="noreferrer"
                                                    className="button button-primary"
                                                    style={{ textDecoration: 'none', padding: '0.3rem 0.5rem', lineHeight: 1 }}
                                                    aria-label={`Open PDF for ${invoice.invoice_number}`}
                                                    title="Open PDF"
                                                >
                                                    📄
                                                </a>
                                                <button
                                                    className="button"
                                                    type="button"
                                                    disabled={pdfMutation.isPending}
                                                    onClick={() => pdfMutation.mutate(invoice.id)}
                                                    aria-label={`Regenerate PDF for ${invoice.invoice_number}`}
                                                    title="Regenerate PDF"
                                                    style={{ padding: '0.3rem 0.5rem', lineHeight: 1 }}
                                                >
                                                    ↻
                                                </button>
                                            </div>
                                        ) : (
                                            <button
                                                className="button"
                                                type="button"
                                                disabled={pdfMutation.isPending}
                                                onClick={() => pdfMutation.mutate(invoice.id)}
                                            >
                                                Generate PDF
                                            </button>
                                        )}
                                    </td>
                                    <td className="actions-cell" style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                                        <Link
                                            className="button button-primary"
                                            style={{ textDecoration: 'none' }}
                                            to={`/invoices/${invoice.id}`}
                                        >
                                            Details
                                        </Link>
                                        {invoice.status === 'draft' && (
                                            <>
                                                <button
                                                    className="button button-primary"
                                                    type="button"
                                                    disabled={approveMutation.isPending}
                                                    onClick={() => approveMutation.mutate(invoice.id)}
                                                >
                                                    Approve
                                                </button>
                                                <button
                                                    className="button danger"
                                                    type="button"
                                                    disabled={deleteMutation.isPending || dialogLoading}
                                                    onClick={() => handleDeleteClick(invoice.id, invoice.invoice_number, invoice.status)}
                                                >
                                                    Delete
                                                </button>
                                            </>
                                        )}
                                        {invoice.status === 'approved' && (
                                            <>
                                                <button
                                                    className="button button-primary"
                                                    type="button"
                                                    disabled={emailMutation.isPending}
                                                    onClick={() => emailMutation.mutate({ invoiceId: invoice.id, email: undefined })}
                                                >
                                                    Send Email
                                                </button>
                                                <button
                                                    className="button"
                                                    type="button"
                                                    disabled={sendMutation.isPending}
                                                    onClick={() => sendMutation.mutate(invoice.id)}
                                                >
                                                    Mark Sent
                                                </button>
                                                <button
                                                    className="button danger"
                                                    type="button"
                                                    disabled={cancelMutation.isPending || dialogLoading}
                                                    onClick={() => handleCancelClick(invoice.id)}
                                                >
                                                    Cancel
                                                </button>
                                            </>
                                        )}
                                        {invoice.status === 'sent' && (
                                            <>
                                                <button
                                                    className="button"
                                                    type="button"
                                                    disabled={payMutation.isPending || dialogLoading}
                                                    onClick={() => handlePayClick(invoice.id)}
                                                >
                                                    Mark Paid
                                                </button>
                                                <button
                                                    className="button button-primary"
                                                    type="button"
                                                    disabled={emailMutation.isPending}
                                                    onClick={() => emailMutation.mutate({ invoiceId: invoice.id, email: undefined })}
                                                >
                                                    Resend Email
                                                </button>
                                                <button
                                                    className="button danger"
                                                    type="button"
                                                    disabled={cancelMutation.isPending || dialogLoading}
                                                    onClick={() => handleCancelClick(invoice.id)}
                                                >
                                                    Cancel
                                                </button>
                                            </>
                                        )}
                                        {invoice.status === 'paid' && (
                                            <span className="muted" style={{ fontSize: '0.9rem', marginTop: '0.2rem' }}>Paid & locked</span>
                                        )}
                                        {user?.role === 'admin' && invoice.status !== 'draft' && (
                                            <button
                                                className="button danger"
                                                type="button"
                                                disabled={deleteMutation.isPending || dialogLoading}
                                                onClick={() => handleDeleteClick(invoice.id, invoice.invoice_number, invoice.status)}
                                            >
                                                Delete
                                            </button>
                                        )}
                                    </td>
                                </tr>
                            )
                        }) : (
                            <tr>
                                <td colSpan={8}>No invoices yet.</td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            {dialog && (
                <ConfirmDialog
                    {...dialog}
                    isLoading={dialogLoading}
                    onConfirm={handleConfirm}
                    onCancel={handleCancel}
                />
            )}

            <EmailLogsModal
                invoiceNumber={selectedInvoiceNumber}
                emailLogs={selectedEmailLogs}
                isOpen={showEmailModal}
                onClose={() => setShowEmailModal(false)}
                onRetry={handleRetryEmail}
                isRetrying={retiringEmailId !== null}
            />
        </div>
    )
}
