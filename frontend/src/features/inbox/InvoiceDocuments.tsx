import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { IssueText } from '../../components/IssueText'
import { InvoicePaymentState, InvoiceTotal } from '../../components/InvoicePresentation'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { formatChf, formatChfAmount } from '../../lib/numbers'
import type { DeliveredDocument } from '../../types/api'
import { CREDIT_STATUS_BADGE } from '../invoices/invoiceCredits'
import { useDownloadDocument } from './DocumentsList'

interface TableProps {
  documents: readonly DeliveredDocument[]
  showCommunity: boolean
}

function DownloadButton({ document }: { document: DeliveredDocument }) {
  const { t } = useTranslation()
  const download = useDownloadDocument()
  return (
    <button
      type="button"
      className="button button-secondary"
      aria-label={t('inbox.downloadLabel', { title: document.title })}
      onClick={() => void download(document)}
    >
      <FontAwesomeIcon icon={faDownload} fixedWidth />
      {t('inbox.download')}
    </button>
  )
}

/**
 * The participant's invoices, from the document inbox: the figures are read live from the invoice
 * (`invoice_figures`), the PDF is the copy that was delivered. Shared by *My invoices* and the dashboard.
 */
export function InvoiceDocumentsTable({ documents, showCommunity }: TableProps) {
  const { t } = useTranslation()
  const { settings } = useAppSettings()

  return (
    <div className="table-scroll">
      <table className="billing-workflow-table">
        <thead>
          <tr>
            <th scope="col">{t('pages.myInvoices.col.invoice')}</th>
            {showCommunity && <th scope="col">{t('pages.myInvoices.col.community')}</th>}
            <th scope="col">{t('pages.myInvoices.col.period')}</th>
            <th scope="col">{t('pages.myInvoices.col.total')}</th>
            <th scope="col">{t('pages.myInvoices.col.status')}</th>
            <th scope="col">{t('pages.myInvoices.col.actions')}</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((document) => {
            const figures = document.invoice_figures
            return (
              <tr key={document.id}>
                <td className="invoice-number-cell">{document.title}</td>
                {showCommunity && <td>{document.zev_name}</td>}
                <td className="billing-period-cell">
                  {document.period_start && document.period_end
                    ? <>{formatShortDate(document.period_start, settings)} → {formatShortDate(document.period_end, settings)}</>
                    : formatShortDate(document.delivered_at.slice(0, 10), settings)}
                </td>
                <td className="numeric">
                  {figures ? <InvoiceTotal invoice={figures} /> : <span className="muted">-</span>}
                </td>
                <td>
                  {figures ? <InvoicePaymentState invoice={figures} /> : <span className="muted">-</span>}
                  {figures && figures.open_data_impact_count > 0 && (
                    <div style={{ marginTop: '0.25rem' }}>
                      <IssueText tone="warning" title={t('pages.invoices.dataReview.issuedNotice', { count: figures.open_data_impact_count })}>
                        {t('pages.invoices.dataReview.badge')}
                      </IssueText>
                    </div>
                  )}
                </td>
                <td><DownloadButton document={document} /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** The participant's credit notes, with what is left of each (read live from the credit note). */
export function CreditNoteDocumentsTable({ documents }: { documents: readonly DeliveredDocument[] }) {
  const { t } = useTranslation()
  const { settings } = useAppSettings()

  return (
    <div className="table-scroll">
      <table className="billing-workflow-table">
        <thead>
          <tr>
            <th scope="col">{t('pages.myInvoices.credits.number')}</th>
            <th scope="col">{t('pages.myInvoices.credits.invoice')}</th>
            <th scope="col">{t('pages.myInvoices.credits.date')}</th>
            <th scope="col">{t('pages.myInvoices.credits.amount')}</th>
            <th scope="col">{t('pages.myInvoices.credits.remaining')}</th>
            <th scope="col">{t('pages.myInvoices.credits.status')}</th>
            <th scope="col">{t('pages.myInvoices.col.actions')}</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((document) => {
            const credit = document.credit_figures
            return (
              <tr key={document.id}>
                <td>{document.title}</td>
                <td>{credit?.source_invoice_number ?? '-'}</td>
                <td>{formatShortDate(document.delivered_at.slice(0, 10), settings)}</td>
                <td className="numeric">{credit ? formatChfAmount(Number(credit.amount_chf)) : '-'}</td>
                <td className="numeric">{credit ? formatChfAmount(Number(credit.remaining_chf)) : '-'}</td>
                <td>
                  {credit && (
                    <span className={CREDIT_STATUS_BADGE[credit.status]}>
                      {t(`pages.invoiceDetail.credits.status.${credit.status}`)}
                    </span>
                  )}
                  {(credit?.applied_to ?? []).map((application) => (
                    <small key={application.invoice_number} className="muted" style={{ display: 'block' }}>
                      {t('pages.invoiceDetail.credits.appliedTo', {
                        invoice: application.invoice_number,
                        amount: formatChf(Number(application.amount_chf)),
                      })}
                    </small>
                  ))}
                </td>
                <td><DownloadButton document={document} /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
