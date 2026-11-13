import { SortableHeader, useTableSorting } from '../../components/tableSorting'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload, faEllipsis, faFileArrowUp, faPaperPlane } from '@fortawesome/free-solid-svg-icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ActionMenu } from '../../components/ActionMenu'
import { ConfirmDialog, useConfirmDialog } from '../../components/ConfirmDialog'
import { Disclosure } from '../../components/Disclosure'
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
import { DOCUMENT_KINDS, documentStanding, documentYear, groupOutbox, KIND_ICON, type OutboxEntry } from './documentPresentation'
import { StandingBadge, useDownloadDocument } from './DocumentsList'
import { IssueReportsDialog, issueYears } from './IssueReportsDialog'
import { UploadDocumentDialog } from './UploadDocumentDialog'
import './inbox.css'
import './DocumentCards.css'

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
    mutationFn: (documents: DeliveredDocument[]) => Promise.all(documents.map((document) => withdrawInboxDocument(document.id))),
    onSuccess: () => {
      pushToast(t('inbox.outbox.withdrawn'), 'success')
      void queryClient.invalidateQueries({ queryKey: queryKeys.inbox.all })
    },
    onError: () => pushToast(t('common.error'), 'error'),
  })

  /** The rows of an entry that can still be taken back: an operator document not yet withdrawn. */
  const withdrawable = (entry: OutboxEntry) =>
    canWriteSelectedCommunity ? entry.documents.filter((document) => document.kind === 'operator' && !document.withdrawn_at) : []

  function askWithdraw(entry: OutboxEntry) {
    const rows = withdrawable(entry)
    const first = entry.documents[0]
    confirm({
      title: t('inbox.outbox.withdrawTitle'),
      message: rows.length > 1
        ? t('inbox.outbox.withdrawGroupMessage', { title: first.title, count: rows.length })
        : t('inbox.outbox.withdrawMessage', { title: first.title, name: rows[0]?.participant_name ?? '' }),
      confirmText: t('inbox.outbox.withdraw'),
      isDangerous: true,
      onConfirm: () => withdraw.mutateAsync(rows).then(() => undefined),
    })
  }

  const documents = documentsQuery.data ?? []
  const entries = useMemo(() => groupOutbox(documentsQuery.data ?? []), [documentsQuery.data])
  const isWithoutAccount = (document: DeliveredDocument) => {
    const addressee = document.participant ? byId.get(document.participant) : undefined
    return addressee != null && addressee.user == null
  }
  /** What an entry says about itself: one standing when all its rows share it, and who has no account yet. */
  const statusOf = (entry: OutboxEntry) => {
    const standings = entry.documents.map(documentStanding)
    return {
      standing: standings.every((standing) => standing === standings[0]) ? standings[0] : null,
      withoutAccount: entry.documents.filter(isWithoutAccount).length,
    }
  }
  // The Status column only earns its width when a row has something to say.
  const showStatus = entries.some((entry) => {
    const status = statusOf(entry)
    return status.standing !== null || status.withoutAccount > 0
  })
  const sorting = useTableSorting(entries, {
    document: row => row.documents[0].title,
    participant: row => row.documents[0].participant_name,
    delivered: row => row.documents[0].delivered_at,
    status: row => statusOf(row).standing ?? (statusOf(row).withoutAccount > 0 ? 'no_account' : null),
  })
  const isGroup = (entry: OutboxEntry) => entry.documents.length > 1
  const years = issueYears(today)
  const filtered = !!(participantId || kind || year)

  const participantCell = (entry: OutboxEntry) => {
    if (!isGroup(entry)) return entry.documents[0].participant_name ?? '—'
    return (
      <Disclosure summary={t('inbox.outbox.recipients', { count: entry.documents.length })} className="doc-recipients">
        <ul>
          {entry.documents.map((document) => (
            <li key={document.id}>
              {document.participant_name ?? '—'}
              {isWithoutAccount(document) && <small className="muted"> · {t('inbox.outbox.noAccount')}</small>}
            </li>
          ))}
        </ul>
      </Disclosure>
    )
  }
  const statusBadges = (entry: OutboxEntry) => {
    const status = statusOf(entry)
    return (
      <>
        {status.standing && <StandingBadge document={entry.documents[0]} />}
        {status.withoutAccount > 0 && (
          <span className="badge badge-neutral">
            {isGroup(entry) ? t('inbox.outbox.noAccountCount', { count: status.withoutAccount }) : t('inbox.outbox.noAccount')}
          </span>
        )}
      </>
    )
  }
  const downloadButton = (entry: OutboxEntry, compact: boolean) => {
    const document = entry.documents[0]
    return (
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
  }
  const moreActions = (entry: OutboxEntry) =>
    withdrawable(entry).length > 0 ? (
      <ActionMenu
        label={t('inbox.outbox.moreActions')}
        icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
        iconOnly
        items={[{ key: 'withdraw', label: t('inbox.outbox.withdraw'), danger: true, onClick: () => askWithdraw(entry) }]}
      />
    ) : null

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
                  <SortableHeader {...sorting.header('document')} scope="col">{t('inbox.outbox.col.document')}</SortableHeader>
                  <SortableHeader {...sorting.header('participant')} scope="col">{t('inbox.outbox.col.participant')}</SortableHeader>
                  <SortableHeader {...sorting.header('delivered')} scope="col">{t('inbox.outbox.col.delivered')}</SortableHeader>
                  {showStatus && <SortableHeader {...sorting.header('status')} scope="col">{t('inbox.outbox.col.status')}</SortableHeader>}
                  <th scope="col" className="doc-actions-col">{t('inbox.outbox.col.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {sorting.rows.map((entry) => {
                  const document = entry.documents[0]
                  return (
                    <tr key={entry.key}>
                      <td>
                        <FontAwesomeIcon icon={KIND_ICON[document.kind]} fixedWidth aria-hidden="true" />{' '}
                        {document.title}
                        <small className="muted doc-note">
                          {t(`inbox.kind.${document.kind}`)} · {documentYear(document)}
                        </small>
                      </td>
                      <td>{participantCell(entry)}</td>
                      <td>
                        {formatShortDate(document.delivered_at.slice(0, 10), settings)}
                        {document.delivered_by_name && (
                          <small className="muted doc-note">{document.delivered_by_name}</small>
                        )}
                      </td>
                      {showStatus && <td>{statusBadges(entry)}</td>}
                      <td className="doc-actions-col">
                        <div className="actions-row">
                          {downloadButton(entry, true)}
                          {moreActions(entry)}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <ul className="doc-cards">
            {sorting.rows.map((entry) => {
              const document = entry.documents[0]
              return (
                <li key={entry.key} className="doc-card">
                  <div className="doc-card-head">
                    <strong><FontAwesomeIcon icon={KIND_ICON[document.kind]} fixedWidth aria-hidden="true" /> {document.title}</strong>
                    <span>{statusBadges(entry)}</span>
                  </div>
                  <p className="muted doc-card-meta">
                    {isGroup(entry) ? t('inbox.outbox.recipients', { count: entry.documents.length }) : (document.participant_name ?? '—')}
                    {' · '}{t(`inbox.kind.${document.kind}`)} · {documentYear(document)}
                  </p>
                  <p className="muted doc-card-meta">
                    {formatShortDate(document.delivered_at.slice(0, 10), settings)}
                    {document.delivered_by_name ? ` · ${document.delivered_by_name}` : ''}
                  </p>
                  <div className="doc-card-actions">
                    {downloadButton(entry, false)}
                    {moreActions(entry)}
                  </div>
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
