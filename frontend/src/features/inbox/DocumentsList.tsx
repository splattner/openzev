import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { downloadInboxDocument } from '../../lib/api/inbox'
import { downloadBlob } from '../../lib/downloadBlob'
import { useToast } from '../../lib/toast'
import type { DeliveredDocument } from '../../types/api'
import { documentStanding, formatFileSize, KIND_ICON, type YearGroup } from './documentPresentation'
import './DocumentsList.css'

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

export function DocumentsList({ groups, showCommunity }: { groups: YearGroup[]; showCommunity: boolean }) {
  const { t } = useTranslation()
  const { settings } = useAppSettings()
  const download = useDownloadDocument()

  return (
    <div className="inbox-years">
      {groups.map((group) => (
        <section key={group.year} aria-labelledby={`inbox-year-${group.year}`} className="card inbox-year">
          <h2 id={`inbox-year-${group.year}`} className="inbox-year-title">{group.year}</h2>
          <ul className="inbox-list">
            {group.documents.map((document) => (
              <li key={document.id} className="inbox-row">
                <span className="inbox-row-icon" aria-hidden="true">
                  <FontAwesomeIcon icon={KIND_ICON[document.kind]} fixedWidth />
                </span>
                <div className="inbox-row-main">
                  <p className="inbox-row-title">
                    {document.title}
                    <StandingBadge document={document} />
                  </p>
                  <p className="muted inbox-row-meta">
                    {t(`inbox.kind.${document.kind}`)}
                    {' · '}
                    {t('inbox.deliveredOn', { date: formatShortDate(document.delivered_at.slice(0, 10), settings) })}
                    {showCommunity ? ` · ${document.zev_name}` : ''}
                    {document.size_bytes ? ` · ${formatFileSize(document.size_bytes)}` : ''}
                  </p>
                </div>
                <button
                  type="button"
                  className="button button-secondary inbox-row-action"
                  aria-label={t('inbox.downloadLabel', { title: document.title })}
                  onClick={() => void download(document)}
                >
                  <FontAwesomeIcon icon={faDownload} fixedWidth />
                  {t('inbox.download')}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
