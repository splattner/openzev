import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faBuilding, faSpinner } from '@fortawesome/free-solid-svg-icons'
import type { ActionMenuItem } from '../../components/ActionMenu'
import { InvoiceAmount, InvoiceLink, InvoiceRowActions, InvoiceTotal } from '../../components/InvoicePresentation'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { InvoiceProgressLegend, InvoiceRowProgress } from './InvoiceRowProgress'
import { invoiceStepReasonText } from './invoiceRowText'
import { invoiceRowIssues, liveInvoice, type InvoiceRowWork } from './invoiceRowState'
import type { InvoicePeriodParticipantRow } from '../../types/api'

type InvoicePeriodRowsTableProps = {
  rows: InvoicePeriodParticipantRow[]
  period: { period_start: string; period_end: string }
  getPrimaryRowAction: (row: InvoicePeriodParticipantRow) => ActionMenuItem | null
  getRowMenuItems: (row: InvoicePeriodParticipantRow) => ActionMenuItem[]
  /** Locally pending invoice, PDF or email work. */
  getRowWork: (row: InvoicePeriodParticipantRow) => InvoiceRowWork
  /** Repeated parties across the unfiltered period; their rows show meter locations. */
  repeatedPartyIds: ReadonlySet<string>
}

/** Period invoice rows; narrow containers render cards. */
export function InvoicePeriodRowsTable({
  rows,
  period,
  getPrimaryRowAction,
  getRowMenuItems,
  getRowWork,
  repeatedPartyIds,
}: InvoicePeriodRowsTableProps) {
  const { t } = useTranslation()
  const { settings } = useAppSettings()

  return (
    <>
      <div className="table-card invoice-rows">
        {/* Explicit roles keep table semantics when narrow containers turn
            the table into cards with display: block. */}
        <table role="table">
          <thead role="rowgroup">
            <tr role="row">
              <th role="columnheader" scope="col">{t('pages.invoices.col.participant')}</th>
              <th role="columnheader" scope="col">{t('pages.invoices.col.progress')}</th>
              <th role="columnheader" scope="col" className="numeric">{t('pages.invoices.col.amount')}</th>
              <th role="columnheader" scope="col" className="invoice-actions-cell">{t('pages.invoices.col.actions')}</th>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {rows.map((row) => {
              const invoice = row.invoice
              const live = liveInvoice(row)
              const work = getRowWork(row)
              const issues = invoiceRowIssues(row, work)
              const missingMeters = row.missing_meter_details?.length
                ? row.missing_meter_details.map((item) => ({
                    id: item.meter_id,
                    text: `${item.meter_id} (${t('pages.invoices.metering.missingDays', { count: item.missing_days })})`,
                  }))
                : row.missing_meter_ids.map((meterId) => ({ id: meterId, text: meterId }))
              // A move in or out inside the period explains a short bill.
              const joined = row.participant_valid_from && row.participant_valid_from > period.period_start
                ? row.participant_valid_from : null
              const left = row.participant_valid_to && row.participant_valid_to < period.period_end
                ? row.participant_valid_to : null

              const locations = repeatedPartyIds.has(row.party_id) ? row.metering_point_labels : []

              return (
                <tr key={row.participant_id} role="row">
                  <td role="cell" className="invoice-row-who">
                    <span className="invoice-row-name">
                      {row.participant_kind === 'organisation' && (
                        <FontAwesomeIcon
                          icon={faBuilding}
                          fixedWidth
                          title={t('pages.participants.kind.organisation')}
                          className="invoice-row-kind"
                        />
                      )}
                      <strong>{row.participant_name}</strong>
                      {row.participant_name_addition && (
                        <span className="muted">{row.participant_name_addition}</span>
                      )}
                    </span>
                    <span className="invoice-row-meta">
                      {invoice ? (
                        <span>
                          <InvoiceLink invoice={invoice} from="/billing/invoices" period={period} />
                          {!live && ` (${t('invoice.status.cancelled')})`}
                        </span>
                      ) : null}
                      {/* A correction or a cancel-and-regenerate leaves the earlier invoice behind. */}
                      {invoice?.replaces?.length ? (
                        <span>
                          {t('pages.invoices.row.replaces')}{' '}
                          <InvoiceLink invoice={invoice.replaces[0]} from="/billing/invoices" period={period} />
                          {` (${t('invoice.status.cancelled')})`}
                          {invoice.replaces.length > 1 && ` ${t('pages.invoices.row.moreReplaced', { count: invoice.replaces.length - 1 })}`}
                        </span>
                      ) : null}
                      {!live && work.generating ? (
                        <span className="invoice-row-pending">
                          <FontAwesomeIcon icon={faSpinner} spin fixedWidth aria-hidden="true" />
                          {t('pages.invoices.progress.reasons.generating')}
                        </span>
                      ) : !invoice && row.generation_eligibility?.state !== 'covered' ? (
                        <span>{t('pages.invoices.notCreated')}</span>
                      ) : null}
                      {locations.length > 0 && <span>{locations.join(', ')}</span>}
                      {joined && <span>{t('pages.invoices.row.joined', { date: formatShortDate(joined, settings) })}</span>}
                      {left && <span>{t('pages.invoices.row.left', { date: formatShortDate(left, settings) })}</span>}
                    </span>
                    {issues.length > 0 && (
                      <span className="invoice-row-issues">
                        {issues.map((issue) => (
                          <span key={issue} title={issue === 'pdf' ? t('pages.invoices.pdfFailedHint') : undefined}>
                            {invoiceStepReasonText(t, issue, row)}
                          </span>
                        ))}
                      </span>
                    )}
                    {missingMeters.length > 0 && (
                      <ul className="metering-missing-list muted">
                        {missingMeters.map((meter) => <li key={meter.id}>{meter.text}</li>)}
                      </ul>
                    )}
                  </td>
                  <td role="cell" className="invoice-row-progress">
                    <InvoiceRowProgress row={row} period={period} work={work} />
                  </td>
                  <td role="cell" className="numeric invoice-row-total">
                    {live && <span className="invoice-row-currency">CHF </span>}
                    {live ? <InvoiceTotal invoice={live} currency={false} /> : <InvoiceAmount value={null} currency={false} />}
                  </td>
                  <td role="cell" className="invoice-actions-cell">
                    <InvoiceRowActions primary={getPrimaryRowAction(row)} menuItems={getRowMenuItems(row)} variant="secondary" iconOnlyMenu />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <InvoiceProgressLegend />
    </>
  )
}
