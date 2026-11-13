import { SortableHeader, useTableSorting } from '../../components/tableSorting'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { IssueText } from '../../components/IssueText'
import { InvoicePaymentState, InvoiceTotal } from '../../components/InvoicePresentation'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { formatChf } from '../../lib/numbers'
import { downloadInboxDocument } from '../../lib/api/inbox'
import { downloadBlob } from '../../lib/downloadBlob'
import { useToast } from '../../lib/toast'
import type { DeliveredDocument } from '../../types/api'
import { CREDIT_STATUS_BADGE } from '../invoices/invoiceCredits'
import { documentStanding, documentYear, formatFileSize, KIND_ICON } from './documentPresentation'
import './DocumentCards.css'

export function StandingBadge({ document }: { document: DeliveredDocument }) {
  const { t } = useTranslation()
  const standing = documentStanding(document)
  if (!standing) return null
  return (
    <span className={`badge ${standing === 'superseded' ? 'badge-neutral' : 'badge-warning'}`}>
      {t(`inbox.standing.${standing}`)}
    </span>
  )
}

/** Fetch the PDF through the API (it is never served from a media URL) and save it. */
export function useDownloadDocument() {
  const { t } = useTranslation()
  const { pushToast } = useToast()
  return (document: DeliveredDocument) =>
    downloadInboxDocument(document.id)
      .then((blob) => downloadBlob(blob, document.file_name || `${document.title}.pdf`))
      .catch(() => pushToast(t('inbox.downloadError'), 'error'))
}

/** The amount of an invoice (with what is due after credit) or of a credit note (with what is left). */
function AmountCell({ document }: { document: DeliveredDocument }) {
  const { t } = useTranslation()
  if (document.invoice_figures) return <InvoiceTotal invoice={document.invoice_figures} />
  const credit = document.credit_figures
  if (!credit) return null
  return (
    <>
      {formatChf(Number(credit.amount_chf))}
      <small className="muted doc-note">{t('inbox.credit.remaining', { amount: formatChf(Number(credit.remaining_chf)) })}</small>
    </>
  )
}

/**
 * Where a document stands: what a participant needs to know about an invoice (due, overdue, paid, and a
 * warning while a reading correction is open), what is left of a credit note and where it was set off,
 * and for everything else whether it was replaced or withdrawn. Read live from the invoice or credit
 * note; the file itself is the copy that was delivered.
 */
function StatusCell({ document }: { document: DeliveredDocument }) {
  const { t } = useTranslation()
  const invoice = document.invoice_figures
  if (invoice) {
    return (
      <>
        <InvoicePaymentState invoice={invoice} />
        {invoice.open_data_impact_count > 0 && (
          <div className="doc-issue">
            <IssueText tone="warning" title={t('pages.invoices.dataReview.issuedNotice', { count: invoice.open_data_impact_count })}>
              {t('pages.invoices.dataReview.badge')}
            </IssueText>
          </div>
        )}
      </>
    )
  }
  const credit = document.credit_figures
  if (credit) {
    return (
      <>
        <span className={CREDIT_STATUS_BADGE[credit.status]}>
          {t(`pages.invoiceDetail.credits.status.${credit.status}`)}
        </span>
        {credit.applied_to.map((application) => (
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
  return <StandingBadge document={document} />
}

/** Whether the status cell of a document has anything to show. */
function hasStatus(document: DeliveredDocument): boolean {
  return !!(document.invoice_figures || document.credit_figures || documentStanding(document))
}

/**
 * What was delivered to the account: a sheet like the other lists (the same table and header as the
 * manager's *Documents* page), newest first; a small card per document on a phone. Invoices and credit
 * notes carry their amount and where they stand.
 */
export function DocumentsList({ documents, showCommunity }: { documents: readonly DeliveredDocument[]; showCommunity: boolean }) {
  const { t } = useTranslation()
  const { settings } = useAppSettings()
  const download = useDownloadDocument()
  const showAmount = documents.some((document) => document.invoice_figures || document.credit_figures)
  // Status only earns its column when a row has something to say, as for the amount.
  const showStatus = documents.some(hasStatus)

  const sorting = useTableSorting(documents, {
    document: row => row.title,
    community: row => row.zev_name,
    delivered: row => row.delivered_at,
    amount: row => row.invoice_figures || row.credit_figures ? Number(row.invoice_figures?.total_chf ?? row.credit_figures?.amount_chf) : null,
    status: row => row.invoice_figures?.status ?? row.credit_figures?.status ?? documentStanding(row),
  })
  const meta = (document: DeliveredDocument) =>
    [
      t(`inbox.kind.${document.kind}`),
      documentYear(document),
      document.credit_figures?.source_invoice_number ? `${t('inbox.credit.forInvoice')} ${document.credit_figures.source_invoice_number}` : null,
      document.size_bytes ? formatFileSize(document.size_bytes) : null,
    ].filter(Boolean).join(' · ')
  const downloadButton = (document: DeliveredDocument, compact: boolean) => (
    <button
      type="button"
      className={`button button-secondary${compact ? ' button-compact' : ''}`}
      aria-label={t('inbox.downloadLabel', { title: document.title })}
      onClick={() => void download(document)}
    >
      <FontAwesomeIcon icon={faDownload} fixedWidth />
      {t('inbox.download')}
    </button>
  )

  return (
    <section className="table-card" aria-label={t('inbox.title')}>
      <div className="table-scroll doc-wide">
        <table className="billing-workflow-table">
          <thead>
            <tr>
              <SortableHeader {...sorting.header('document')} scope="col">{t('inbox.outbox.col.document')}</SortableHeader>
              {showCommunity && <SortableHeader {...sorting.header('community')} scope="col">{t('inbox.col.community')}</SortableHeader>}
              <SortableHeader {...sorting.header('delivered')} scope="col">{t('inbox.outbox.col.delivered')}</SortableHeader>
              {showAmount && <SortableHeader {...sorting.header('amount')} scope="col" className="numeric">{t('inbox.col.amount')}</SortableHeader>}
              {showStatus && <SortableHeader {...sorting.header('status')} scope="col">{t('inbox.outbox.col.status')}</SortableHeader>}
              <th scope="col">{t('inbox.outbox.col.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map((document) => (
              <tr key={document.id}>
                <td>
                  <FontAwesomeIcon icon={KIND_ICON[document.kind]} fixedWidth aria-hidden="true" />{' '}
                  {document.title}
                  <small className="muted doc-note">{meta(document)}</small>
                </td>
                {showCommunity && <td>{document.zev_name}</td>}
                <td>{formatShortDate(document.delivered_at.slice(0, 10), settings)}</td>
                {showAmount && <td className="numeric"><AmountCell document={document} /></td>}
                {showStatus && <td><StatusCell document={document} /></td>}
                <td>{downloadButton(document, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="doc-cards">
        {sorting.rows.map((document) => (
          <li key={document.id} className="doc-card">
            <div className="doc-card-head">
              <strong><FontAwesomeIcon icon={KIND_ICON[document.kind]} fixedWidth aria-hidden="true" /> {document.title}</strong>
              {showAmount && <span className="doc-card-amount"><AmountCell document={document} /></span>}
            </div>
            <p className="muted doc-card-meta">
              {meta(document)} · {t('inbox.deliveredOn', { date: formatShortDate(document.delivered_at.slice(0, 10), settings) })}
              {showCommunity ? ` · ${document.zev_name}` : ''}
            </p>
            {hasStatus(document) && <div><StatusCell document={document} /></div>}
            {downloadButton(document, false)}
          </li>
        ))}
      </ul>
    </section>
  )
}
