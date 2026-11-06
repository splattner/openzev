import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { IssueText } from '../../components/IssueText'
import { InvoicePaymentState, InvoiceTotal } from '../../components/InvoicePresentation'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { formatChf } from '../../lib/numbers'
import type { DeliveredDocument } from '../../types/api'
import { CREDIT_STATUS_BADGE } from '../invoices/invoiceCredits'
import { useDownloadDocument } from './DocumentsList'
import './InvoiceDocuments.css'

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

function PeriodText({ document }: { document: DeliveredDocument }) {
  const { settings } = useAppSettings()
  return document.period_start && document.period_end
    ? <>{formatShortDate(document.period_start, settings)} → {formatShortDate(document.period_end, settings)}</>
    : <>{formatShortDate(document.delivered_at.slice(0, 10), settings)}</>
}

function PaymentCell({ document }: { document: DeliveredDocument }) {
  const { t } = useTranslation()
  const figures = document.invoice_figures
  if (!figures) return <span className="muted">-</span>
  return (
    <>
      <InvoicePaymentState invoice={figures} />
      {figures.open_data_impact_count > 0 && (
        <div className="doc-issue">
          <IssueText tone="warning" title={t('pages.invoices.dataReview.issuedNotice', { count: figures.open_data_impact_count })}>
            {t('pages.invoices.dataReview.badge')}
          </IssueText>
        </div>
      )}
    </>
  )
}

function CreditStatusCell({ document }: { document: DeliveredDocument }) {
  const { t } = useTranslation()
  const credit = document.credit_figures
  return (
    <>
      {credit && (
        <span className={CREDIT_STATUS_BADGE[credit.status]}>
          {t(`pages.invoiceDetail.credits.status.${credit.status}`)}
        </span>
      )}
      {(credit?.applied_to ?? []).map((application) => (
        <small key={application.invoice_number} className="muted doc-note">
          {t('pages.invoiceDetail.credits.appliedTo', {
            invoice: application.invoice_number,
            amount: formatChf(Number(application.amount_chf)),
          })}
        </small>
      ))}
    </>
  )
}

/**
 * The participant's invoices, from the document inbox: the figures are read live from the invoice
 * (`invoice_figures`), the PDF is the copy that was delivered. Shared by *My invoices* and the dashboard.
 * A table on a wide screen; one small card per invoice on a phone.
 */
export function InvoiceDocumentsTable({ documents, showCommunity }: TableProps) {
  const { t } = useTranslation()

  return (
    <>
      <div className="table-scroll doc-wide">
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
            {documents.map((document) => (
              <tr key={document.id}>
                <td className="invoice-number-cell">{document.title}</td>
                {showCommunity && <td>{document.zev_name}</td>}
                <td className="billing-period-cell"><PeriodText document={document} /></td>
                <td className="numeric">
                  {document.invoice_figures ? <InvoiceTotal invoice={document.invoice_figures} /> : <span className="muted">-</span>}
                </td>
                <td><PaymentCell document={document} /></td>
                <td><DownloadButton document={document} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="doc-cards">
        {documents.map((document) => (
          <li key={document.id} className="doc-card">
            <div className="doc-card-head">
              <strong>{document.title}</strong>
              {document.invoice_figures && <span className="doc-card-amount"><InvoiceTotal invoice={document.invoice_figures} /></span>}
            </div>
            <p className="muted doc-card-meta">
              <PeriodText document={document} />{showCommunity ? ` · ${document.zev_name}` : ''}
            </p>
            <div><PaymentCell document={document} /></div>
            <DownloadButton document={document} />
          </li>
        ))}
      </ul>
    </>
  )
}

/** The participant's credit notes, with what is left of each (read live from the credit note). */
export function CreditNoteDocumentsTable({ documents }: { documents: readonly DeliveredDocument[] }) {
  const { t } = useTranslation()
  const { settings } = useAppSettings()

  return (
    <>
      <div className="table-scroll doc-wide">
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
                  <td className="numeric">{credit ? formatChf(Number(credit.amount_chf)) : '-'}</td>
                  <td className="numeric">{credit ? formatChf(Number(credit.remaining_chf)) : '-'}</td>
                  <td><CreditStatusCell document={document} /></td>
                  <td><DownloadButton document={document} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <ul className="doc-cards">
        {documents.map((document) => {
          const credit = document.credit_figures
          return (
            <li key={document.id} className="doc-card">
              <div className="doc-card-head">
                <strong>{document.title}</strong>
                {credit && <span className="doc-card-amount">{formatChf(Number(credit.amount_chf))}</span>}
              </div>
              <p className="muted doc-card-meta">
                {formatShortDate(document.delivered_at.slice(0, 10), settings)}
                {credit?.source_invoice_number ? ` · ${t('pages.myInvoices.credits.invoice')} ${credit.source_invoice_number}` : ''}
              </p>
              {credit && (
                <p className="doc-card-meta">
                  {t('pages.myInvoices.credits.remaining')}: {formatChf(Number(credit.remaining_chf))}
                </p>
              )}
              <div><CreditStatusCell document={document} /></div>
              <DownloadButton document={document} />
            </li>
          )
        })}
      </ul>
    </>
  )
}
