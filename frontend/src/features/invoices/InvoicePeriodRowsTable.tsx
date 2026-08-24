import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faEllipsis, faEnvelope, faFileInvoice, faFilePdf } from '@fortawesome/free-solid-svg-icons'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ActionMenu, type ActionMenuItem } from '../../components/ActionMenu'
import { getLatestEmailLog } from './emailLogs'
import { invoiceStatusBadgeClass } from './invoiceStatus'
import { openInvoicePdf } from '../../lib/api/invoices'
import type { InvoicePeriodParticipantRow } from '../../types/api'

function emailStatusBadgeClass(status: string): string {
  if (status === 'sent') return 'badge badge-success'
  if (status === 'failed') return 'badge badge-danger'
  return 'badge badge-neutral'
}

type InvoicePeriodRowsTableProps = {
  rows: InvoicePeriodParticipantRow[]
  onOpenEmailLogs: (invoiceId: string, invoiceNumber: string) => void
  getPrimaryRowAction: (row: InvoicePeriodParticipantRow) => ActionMenuItem | null
  getRowMenuItems: (row: InvoicePeriodParticipantRow) => ActionMenuItem[]
}

export function InvoicePeriodRowsTable({
  rows,
  onOpenEmailLogs,
  getPrimaryRowAction,
  getRowMenuItems,
}: InvoicePeriodRowsTableProps) {
  const { t } = useTranslation()

  return (
    <div className="table-card">
      <table>
        <thead>
          <tr>
            <th>{t('pages.invoices.col.participant')}</th>
            <th>{t('pages.invoices.col.meteringData')}</th>
            <th>{t('pages.invoices.col.invoice')}</th>
            <th>{t('pages.invoices.col.email')}</th>
            <th>{t('pages.invoices.col.total')}</th>
            <th>{t('pages.invoices.col.pdf')}</th>
            <th className="invoice-actions-cell">{t('pages.invoices.col.actions')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const invoice = row.invoice
            const latestEmailLog = getLatestEmailLog(invoice)
            const primaryAction = getPrimaryRowAction(row)
            const rowMenuItems = getRowMenuItems(row)

            return (
              <tr key={row.participant_id}>
                <td>
                  <strong>{row.participant_name}</strong>
                  {row.participant_email ? <div className="muted">{row.participant_email}</div> : null}
                </td>
                <td>
                  {row.metering_data_complete ? (
                    <span className="badge badge-success">{t('pages.invoices.metering.complete')}</span>
                  ) : (
                    <>
                      <span className="badge badge-danger">{t('pages.invoices.metering.missing')}</span>
                      <div className="muted" style={{ fontSize: '0.85rem' }}>
                        {t('pages.invoices.metering.pointsWithData', {
                          n: row.metering_points_with_data,
                          total: row.metering_points_total,
                        })}
                      </div>
                      {row.missing_meter_ids.length > 0 && (
                        <ul className="metering-missing-list muted">
                          {row.missing_meter_details?.length
                            ? row.missing_meter_details.map((item) => (
                                <li key={item.meter_id}>
                                  {item.meter_id} ({item.missing_days} day{item.missing_days === 1 ? '' : 's'})
                                </li>
                              ))
                            : row.missing_meter_ids.map((meterId) => <li key={meterId}>{meterId}</li>)}
                        </ul>
                      )}
                    </>
                  )}
                </td>
                <td>
                  {invoice ? (
                    <div className="invoice-cell-stack">
                      <span>{invoice.invoice_number}</span>
                      <span className={invoiceStatusBadgeClass(invoice.status)}>{t(`invoice.status.${invoice.status}`)}</span>
                    </div>
                  ) : (
                    <div className="invoice-cell-stack">
                      <span className="muted">{t('pages.invoices.notCreated')}</span>
                      <span className="badge badge-neutral">{t('pages.invoices.notCreated')}</span>
                    </div>
                  )}
                </td>
                <td>
                  {invoice && latestEmailLog ? (
                    <div className="invoice-cell-stack">
                      <span className={emailStatusBadgeClass(latestEmailLog.status)}>{t(`email.${latestEmailLog.status}`)}</span>
                      <div>
                        <button
                          className="table-inline-action"
                          type="button"
                          onClick={() => onOpenEmailLogs(invoice.id, invoice.invoice_number)}
                        >
                          <FontAwesomeIcon icon={faEnvelope} fixedWidth />
                          {t('pages.invoices.viewLogs')} ({invoice.email_logs?.length ?? 0})
                        </button>
                        {(invoice.email_logs?.filter((log) => log.status === 'failed').length ?? 0) > 0 && (
                          <span style={{ color: 'var(--danger-600)', marginLeft: '0.3rem', fontSize: '0.85rem', fontWeight: 'bold' }}>
                            {t('pages.invoices.failedEmails', {
                              n: invoice.email_logs?.filter((log) => log.status === 'failed').length,
                            })}
                          </span>
                        )}
                      </div>
                      {(invoice.email_logs?.length ?? 0) > 1 && (
                        <div className="muted" style={{ fontSize: '0.85rem' }}>
                          {t('pages.invoices.attempts', { n: invoice.email_logs?.length })}
                        </div>
                      )}
                    </div>
                  ) : (
                    <span className="muted">-</span>
                  )}
                </td>
                <td>{invoice ? `CHF ${invoice.total_chf}` : <span className="muted">-</span>}</td>
                <td>
                  {invoice ? (
                    invoice.pdf_url ? (
                      <div className="invoice-cell-stack">
                        <button type="button" onClick={() => { if (invoice) openInvoicePdf(invoice.id) }} className="table-inline-link">
                          <FontAwesomeIcon icon={faFilePdf} fixedWidth />
                          {t('pages.invoices.openPdf')}
                        </button>
                        <span className="badge badge-success">{t('pages.invoices.pdfReady')}</span>
                      </div>
                    ) : (
                      <span className="badge badge-neutral">{t('pages.invoices.pdfMissing')}</span>
                    )
                  ) : (
                    <span className="muted">-</span>
                  )}
                </td>
                <td className="invoice-actions-cell">
                  <div className="invoice-row-actions">
                    {primaryAction && (
                      <button
                        className="button button-primary button-compact"
                        type="button"
                        disabled={primaryAction.disabled}
                        onClick={primaryAction.onClick}
                      >
                        {primaryAction.icon}
                        {primaryAction.label}
                      </button>
                    )}
                    {invoice && (
                      <Link
                        className="button button-secondary button-compact"
                        style={{ textDecoration: 'none' }}
                        to={`/invoices/${invoice.id}`}
                      >
                        <FontAwesomeIcon icon={faFileInvoice} fixedWidth />
                        {t('pages.invoices.openDetails')}
                      </Link>
                    )}
                    {rowMenuItems.length > 0 && (
                      <ActionMenu
                        label={t('pages.invoices.moreActions')}
                        icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                        items={rowMenuItems}
                      />
                    )}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
