import { useTranslation } from 'react-i18next'

import { ConfirmDialog, useConfirmDialog } from '../../components/ConfirmDialog'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import type { InvoiceAccessLink } from '../../types/api'

/**
 * The QR link printed on this invoice, and the one control over it.
 *
 * The token has no expiry — it is on a document that sits in a folder for
 * years — so revoking is the only way a leaked or mis-sent invoice stops
 * granting access. That makes this card the security control the feature
 * otherwise only claims to have, which is why it says plainly what revoking
 * costs: the printed QR stops working for good.
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
    const { dialog, confirm, handleConfirm, handleCancel, isLoading } = useConfirmDialog()

    return (
        <section className="card">
            <h3 style={{ marginTop: 0 }}>{t('pages.invoiceDetail.accessLink.title')}</h3>
            <p className="muted">{t('pages.invoiceDetail.accessLink.description')}</p>

            <div className="inline-form grid grid-2" style={{ marginBottom: '1rem' }}>
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
                className="button danger"
                onClick={() =>
                    confirm({
                        title: t('pages.invoiceDetail.accessLink.revokeTitle'),
                        message: t('pages.invoiceDetail.accessLink.revokeWarning'),
                        confirmText: t('pages.invoiceDetail.accessLink.revoke'),
                        isDangerous: true,
                        onConfirm: onRevoke,
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
