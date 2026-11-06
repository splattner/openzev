import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { downloadInboxDocument } from '../../lib/api/inbox'
import { downloadBlob } from '../../lib/downloadBlob'
import { useToast } from '../../lib/toast'
import type { DeliveredDocument } from '../../types/api'
import { documentStanding, documentYear, formatFileSize, KIND_ICON } from './documentPresentation'
import './InvoiceDocuments.css'

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

/**
 * What was delivered to the account: a sheet like the other lists (the same table and header as the
 * manager's *Delivered documents*), newest first; a small card per document on a phone.
 */
export function DocumentsList({ documents, showCommunity }: { documents: readonly DeliveredDocument[]; showCommunity: boolean }) {
  const { t } = useTranslation()
  const { settings } = useAppSettings()
  const download = useDownloadDocument()

  const meta = (document: DeliveredDocument) =>
    [t(`inbox.kind.${document.kind}`), documentYear(document), document.size_bytes ? formatFileSize(document.size_bytes) : null]
      .filter(Boolean).join(' · ')
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
              <th scope="col">{t('inbox.outbox.col.document')}</th>
              {showCommunity && <th scope="col">{t('pages.myInvoices.col.community')}</th>}
              <th scope="col">{t('inbox.outbox.col.delivered')}</th>
              <th scope="col">{t('inbox.outbox.col.status')}</th>
              <th scope="col">{t('inbox.outbox.col.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((document) => (
              <tr key={document.id}>
                <td>
                  <FontAwesomeIcon icon={KIND_ICON[document.kind]} fixedWidth aria-hidden="true" />{' '}
                  {document.title}
                  <small className="muted doc-note">{meta(document)}</small>
                </td>
                {showCommunity && <td>{document.zev_name}</td>}
                <td>{formatShortDate(document.delivered_at.slice(0, 10), settings)}</td>
                <td><StandingBadge document={document} /></td>
                <td>{downloadButton(document, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="doc-cards">
        {documents.map((document) => (
          <li key={document.id} className="doc-card">
            <div className="doc-card-head">
              <strong><FontAwesomeIcon icon={KIND_ICON[document.kind]} fixedWidth aria-hidden="true" /> {document.title}</strong>
              <StandingBadge document={document} />
            </div>
            <p className="muted doc-card-meta">
              {meta(document)} · {t('inbox.deliveredOn', { date: formatShortDate(document.delivered_at.slice(0, 10), settings) })}
              {showCommunity ? ` · ${document.zev_name}` : ''}
            </p>
            {downloadButton(document, false)}
          </li>
        ))}
      </ul>
    </section>
  )
}
