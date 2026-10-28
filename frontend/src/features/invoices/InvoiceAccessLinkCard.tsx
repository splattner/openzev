import { useMutation } from '@tanstack/react-query'
import { useToast } from '../../lib/toast'
import { formatApiError } from '../../lib/api/errors'
import { useTranslation } from 'react-i18next'

import { ConfirmDialog, consumeReportedError, useConfirmDialog } from '../../components/ConfirmDialog'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import type { InvoiceAccessLink } from '../../types/api'

/**
 * Shows the invoice access link and allows revocation.
 * Printed links do not expire; revocation stops access through a leaked invoice.
 * Revocation permanently invalidates the QR link printed on the invoice.
 */
export function InvoiceAccessLinkCard({
    link,
    onRevoke,
}: {
    link: InvoiceAccessLink
    onRevoke: () => Promise<void>
}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { pushToast } = useToast()
    const revokeMutation = useMutation({
        mutationFn: onRevoke,
        onError: error => pushToast(formatApiError(error, t('common.error')), 'error'),
    })
    const { dialog, confirm, handleConfirm, handleCancel, isLoading } = useConfirmDialog()

    return (
        <section className="card">
            <h3 className="mt-0">{t('pages.invoiceDetail.accessLink.title')}</h3>
            <p className="muted">{t('pages.invoiceDetail.accessLink.description')}</p>

            <div className="inline-form grid grid-2 mb-1">
                <div>
                    <strong>{t('pages.invoiceDetail.accessLink.created')}</strong>
                    <div>{formatShortDate(link.created_at, settings)}</div>
                </div>
                <div>
                    <strong>{t('pages.invoiceDetail.accessLink.lastOpened')}</strong>
                    <div>
                        {link.last_used_at
                            ? formatShortDate(link.last_used_at, settings)
                            : t('pages.invoiceDetail.accessLink.neverOpened')}
                    </div>
                </div>
            </div>

            <button
                type="button"
                className="button button-danger"
                disabled={revokeMutation.isPending}
                onClick={() =>
                    confirm({
                        title: t('pages.invoiceDetail.accessLink.revokeTitle'),
                        message: t('pages.invoiceDetail.accessLink.revokeWarning'),
                        confirmText: t('pages.invoiceDetail.accessLink.revoke'),
                        isDangerous: true,
                        onConfirm: () => consumeReportedError(revokeMutation.mutateAsync()),
                    })
                }
            >
                {t('pages.invoiceDetail.accessLink.revoke')}
            </button>

            {dialog && (
                <ConfirmDialog
                    {...dialog}
                    isLoading={isLoading}
                    onConfirm={handleConfirm}
                    onCancel={handleCancel}
                />
            )}
        </section>
    )
}
