import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload, faFileArrowUp, faPaperPlane } from '@fortawesome/free-solid-svg-icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ConfirmDialog, useConfirmDialog } from '../../components/ConfirmDialog'
import { Notice } from '../../components/Notice'
import { PageSkeleton } from '../../components/PageSkeleton'
import { Toolbar } from '../../components/Toolbar'
import { listInboxDocuments, withdrawInboxDocument } from '../../lib/api/inbox'
import { queryKeys } from '../../lib/api/queryKeys'
import { fetchParticipants } from '../../lib/api/zev'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { useCommunityAccess } from '../../lib/communityAccess'
import { todayBusinessIso } from '../../lib/dates'
import { useManagedZev } from '../../lib/managedZev'
import { useToast } from '../../lib/toast'
import type { DeliveredDocument, DocumentKind } from '../../types/api'
import { participantLabel } from './AudienceFields'
import { DOCUMENT_KINDS, documentYear, KIND_ICON } from './documentPresentation'
import { StandingBadge, useDownloadDocument } from './DocumentsList'
import { IssueReportsDialog, issueYears } from './IssueReportsDialog'
import { UploadDocumentDialog } from './UploadDocumentDialog'
import './inbox.css'
import './InvoiceDocuments.css'

/**
 * The manager's *Participant documents* page body (spec §7.2): what the community delivered to
 * whom and when, so "did Anna get her statement?" has an answer, and where documents are issued or
 * uploaded. Withdrawn rows stay visible here and are marked; participants no longer see them.
 */
export function Outbox() {
  const { t } = useTranslation()
  const { settings } = useAppSettings()
  const { pushToast } = useToast()
  const queryClient = useQueryClient()
  const { selectedZevId } = useManagedZev()
  const { canWriteSelectedCommunity } = useCommunityAccess()
  const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
  const download = useDownloadDocument()

  const [participantId, setParticipantId] = useState('')
  const [kind, setKind] = useState<'' | DocumentKind>('')
  const [year, setYear] = useState('')
  const [dialogOpen, setDialogOpen] = useState<'upload' | 'issue' | null>(null)

  const filters = {
    zevId: selectedZevId ?? undefined,
    participantId: participantId || undefined,
    kinds: kind ? [kind] : undefined,
    year: year ? Number(year) : undefined,
    includeWithdrawn: true,
  }
  const documentsQuery = useQuery({
    queryKey: queryKeys.inbox.list('outbox', filters),
    queryFn: () => listInboxDocuments(filters),
    enabled: !!selectedZevId,
  })
  const participantsQuery = useQuery({ queryKey: queryKeys.zev.participants(selectedZevId ?? undefined), queryFn: fetchParticipants })
  const participants = useMemo(
    () => (participantsQuery.data ?? []).filter((participant) => participant.zev === selectedZevId),
    [participantsQuery.data, selectedZevId],
  )
  const today = todayBusinessIso()
  const current = participants.filter((participant) => !participant.valid_to || participant.valid_to >= today)
  const byId = useMemo(() => new Map(participants.map((participant) => [participant.id, participant])), [participants])

  const withdraw = useMutation({
    mutationFn: (document: DeliveredDocument) => withdrawInboxDocument(document.id),
    onSuccess: () => {
      pushToast(t('inbox.outbox.withdrawn'), 'success')
      void queryClient.invalidateQueries({ queryKey: queryKeys.inbox.all })
    },
    onError: () => pushToast(t('common.error'), 'error'),
  })

  function askWithdraw(document: DeliveredDocument) {
    confirm({
      title: t('inbox.outbox.withdrawTitle'),
      message: t('inbox.outbox.withdrawMessage', { title: document.title, name: document.participant_name ?? '' }),
      confirmText: t('inbox.outbox.withdraw'),
      isDangerous: true,
      onConfirm: () => withdraw.mutateAsync(document).then(() => undefined),
    })
  }

  const documents = documentsQuery.data ?? []
  const years = issueYears(today)
  const filtered = !!(participantId || kind || year)

  return (
    <div className="page-stack">
      <Toolbar
        actions={canWriteSelectedCommunity && selectedZevId ? (
          <>
            <button type="button" className="button button-secondary" onClick={() => setDialogOpen('issue')}>
              <FontAwesomeIcon icon={faPaperPlane} fixedWidth />
              {t('inbox.outbox.issue')}
            </button>
            <button type="button" className="button button-primary" onClick={() => setDialogOpen('upload')}>
              <FontAwesomeIcon icon={faFileArrowUp} fixedWidth />
              {t('inbox.outbox.upload')}
            </button>
          </>
        ) : undefined}
      >
        <div className="outbox-filters">
          <label>
            <span>{t('inbox.outbox.participant')}</span>
            <select value={participantId} onChange={(event) => setParticipantId(event.target.value)}>
              <option value="">{t('inbox.outbox.allParticipants')}</option>
              {participants.map((participant) => <option key={participant.id} value={participant.id}>{participantLabel(participant)}</option>)}
            </select>
          </label>
          <label>
            <span>{t('inbox.filter.kind')}</span>
            <select value={kind} onChange={(event) => setKind(event.target.value as '' | DocumentKind)}>
              <option value="">{t('inbox.filter.all')}</option>
              {DOCUMENT_KINDS.map((value) => <option key={value} value={value}>{t(`inbox.kind.${value}`)}</option>)}
            </select>
          </label>
          <label>
            <span>{t('inbox.outbox.year')}</span>
            <select value={year} onChange={(event) => setYear(event.target.value)}>
              <option value="">{t('inbox.outbox.allYears')}</option>
              {years.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
        </div>
      </Toolbar>

      {documentsQuery.isLoading ? (
        <PageSkeleton variant="tableRows" />
      ) : documentsQuery.isError ? (
        <Notice tone="error" onRetry={() => void documentsQuery.refetch()} isRetrying={documentsQuery.isFetching}>{t('inbox.failed')}</Notice>
      ) : documents.length === 0 ? (
        <div className="card">
          <h3 className="mt-0">{filtered ? t('inbox.outbox.noMatch') : t('inbox.outbox.empty.title')}</h3>
          {!filtered && <p className="muted">{t('inbox.outbox.empty.description')}</p>}
        </div>
      ) : (
        <section className="table-card">
          <div className="table-scroll doc-wide">
            <table className="billing-workflow-table">
              <thead>
                <tr>
                  <th scope="col">{t('inbox.outbox.col.document')}</th>
                  <th scope="col">{t('inbox.outbox.col.participant')}</th>
                  <th scope="col">{t('inbox.outbox.col.delivered')}</th>
                  <th scope="col">{t('inbox.outbox.col.status')}</th>
                  <th scope="col">{t('inbox.outbox.col.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((document) => {
                  const addressee = document.participant ? byId.get(document.participant) : undefined
                  const withoutAccount = addressee != null && addressee.user == null
                  return (
                    <tr key={document.id}>
                      <td>
                        <FontAwesomeIcon icon={KIND_ICON[document.kind]} fixedWidth aria-hidden="true" />{' '}
                        {document.title}
                        <small className="muted" style={{ display: 'block' }}>
                          {t(`inbox.kind.${document.kind}`)} · {documentYear(document)}
                        </small>
                      </td>
                      <td>{document.participant_name ?? '—'}</td>
                      <td>
                        {formatShortDate(document.delivered_at.slice(0, 10), settings)}
                        {document.delivered_by_name && (
                          <small className="muted" style={{ display: 'block' }}>{document.delivered_by_name}</small>
                        )}
                      </td>
                      <td>
                        <StandingBadge document={document} />
                        {withoutAccount && <span className="badge badge-neutral">{t('inbox.outbox.noAccount')}</span>}
                      </td>
                      <td>
                        <div className="actions-row">
                          <button
                            type="button"
                            className="button button-secondary button-compact"
                            aria-label={t('inbox.downloadLabel', { title: document.title })}
                            onClick={() => void download(document)}
                          >
                            <FontAwesomeIcon icon={faDownload} fixedWidth />
                            {t('inbox.download')}
                          </button>
                          {canWriteSelectedCommunity && document.kind === 'operator' && !document.withdrawn_at && (
                            <button
                              type="button"
                              className="button button-secondary button-compact"
                              onClick={() => askWithdraw(document)}
                            >
                              {t('inbox.outbox.withdraw')}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <ul className="doc-cards">
            {documents.map((document) => {
              const addressee = document.participant ? byId.get(document.participant) : undefined
              const withoutAccount = addressee != null && addressee.user == null
              return (
                <li key={document.id} className="doc-card">
                  <div className="doc-card-head">
                    <strong><FontAwesomeIcon icon={KIND_ICON[document.kind]} fixedWidth aria-hidden="true" /> {document.title}</strong>
                    <span>
                      <StandingBadge document={document} />
                      {withoutAccount && <span className="badge badge-neutral">{t('inbox.outbox.noAccount')}</span>}
                    </span>
                  </div>
                  <p className="muted doc-card-meta">
                    {document.participant_name ?? '—'} · {t(`inbox.kind.${document.kind}`)} · {documentYear(document)}
                  </p>
                  <p className="muted doc-card-meta">
                    {formatShortDate(document.delivered_at.slice(0, 10), settings)}
                    {document.delivered_by_name ? ` · ${document.delivered_by_name}` : ''}
                  </p>
                  <button
                    type="button"
                    className="button button-secondary"
                    aria-label={t('inbox.downloadLabel', { title: document.title })}
                    onClick={() => void download(document)}
                  >
                    <FontAwesomeIcon icon={faDownload} fixedWidth />
                    {t('inbox.download')}
                  </button>
                  {canWriteSelectedCommunity && document.kind === 'operator' && !document.withdrawn_at && (
                    <button type="button" className="button button-secondary" onClick={() => askWithdraw(document)}>
                      {t('inbox.outbox.withdraw')}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {selectedZevId && (
        <>
          <UploadDocumentDialog isOpen={dialogOpen === 'upload'} onClose={() => setDialogOpen(null)} zevId={selectedZevId} participants={current} />
          <IssueReportsDialog isOpen={dialogOpen === 'issue'} onClose={() => setDialogOpen(null)} zevId={selectedZevId} participants={current} />
        </>
      )}
      {dialog && (
        <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
      )}
    </div>
  )
}
