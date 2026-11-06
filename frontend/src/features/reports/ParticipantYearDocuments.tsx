import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AppTabs } from '../../components/AppTabs'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload } from '@fortawesome/free-solid-svg-icons'
import { Notice } from '../../components/Notice'
import { PdfPreview } from '../../components/PdfPreview'
import { YearPicker } from '../../components/YearPicker'
import { PageSkeleton } from '../../components/PageSkeleton'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { downloadBlob } from '../../lib/downloadBlob'
import { downloadInboxDocument, listInboxDocuments } from '../../lib/api/inbox'
import { queryKeys } from '../../lib/api/queryKeys'
import { useAuth } from '../../lib/auth'
import { ownParticipantIds } from '../../lib/membership'
import { usePdfObjectUrl } from '../../lib/usePdfObjectUrl'
import type { DeliveredDocument } from '../../types/api'

type ParticipantYearDocumentsProps = {
  userId: number
  /** The community to read from; omitted, every community the account takes part in. */
  zevId?: string
  year: number
  years: number[]
  onYearChange: (year: number) => void
}

type DocumentKind = 'annual-statement' | 'tax-overview'

type DocumentDescriptor = {
  kind: DocumentKind
  titleKey: 'pages.reports.annualStatement.title' | 'pages.reports.financialSummary.title'
  descriptionKey:
    | 'pages.reports.annualStatement.description'
    | 'pages.reports.financialSummary.description'
  errorKey: 'pages.reports.annualStatement.error' | 'pages.reports.financialSummary.error'
  filenamePrefix: string
  /** The inbox kind this tab reads: what the operator issued, not a live render. */
  inboxKind: 'annual_statement' | 'financial_summary'
}

const DESCRIPTORS: DocumentDescriptor[] = [
  {
    kind: 'annual-statement',
    titleKey: 'pages.reports.annualStatement.title',
    descriptionKey: 'pages.reports.annualStatement.description',
    errorKey: 'pages.reports.annualStatement.error',
    filenamePrefix: 'annual-statement',
    inboxKind: 'annual_statement',
  },
  {
    kind: 'tax-overview',
    titleKey: 'pages.reports.financialSummary.title',
    descriptionKey: 'pages.reports.financialSummary.description',
    errorKey: 'pages.reports.financialSummary.error',
    filenamePrefix: 'financial-summary',
    inboxKind: 'financial_summary',
  },
]

function AnnualDocumentPanel({
  descriptor,
  year,
  document,
  active,
}: {
  descriptor: DocumentDescriptor
  year: number
  /** The issued document for this year, or `undefined` when the operator has not issued one. */
  document: DeliveredDocument | undefined
  active: boolean
}) {
  const { t } = useTranslation()
  const { settings } = useAppSettings()
  const [requested, setRequested] = useState(() => active)
  const [retryAttempt, setRetryAttempt] = useState(0)
  const statusRef = useRef<HTMLDivElement>(null)
  const retryFocusPending = useRef(false)

  useEffect(() => {
    if (active) setRequested(true)
  }, [active])

  const documentId = document?.id
  const fetcher = useMemo(() => {
    if (!documentId) return null
    return (signal: AbortSignal) => downloadInboxDocument(documentId, signal)
    // Retry changes the fetcher identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId, retryAttempt])

  const { url, blob, loading, error } = usePdfObjectUrl(fetcher, requested)

  useEffect(() => {
    if (loading && retryFocusPending.current) {
      retryFocusPending.current = false
      statusRef.current?.focus()
    }
  }, [loading])

  const documentLabel = t(descriptor.titleKey) as string
  const frameTitle = t('pages.reports.documentTitle', { document: documentLabel, year }) as string
  const filename = document?.file_name || `${descriptor.filenamePrefix}-${year}.pdf`

  const downloadButton = (
    <button
      type="button"
      className="button button-primary"
      disabled={!blob}
      onClick={() => {
        if (blob) downloadBlob(blob, filename)
      }}
    >
      <FontAwesomeIcon icon={faDownload} fixedWidth />
      {t('pdf.download')}
    </button>
  )

  return (
    <AppTabs.Panel value={descriptor.kind} aria-busy={loading}>
      <div className="page-stack">
        <p className="muted m-0">{t(descriptor.descriptionKey)}</p>
        {!document ? (
          <div className="card">
            <p className="muted m-0">{t('pages.reports.notIssued', { document: documentLabel, year })}</p>
          </div>
        ) : (
          <>
            <p className="muted m-0">
              {t('pages.reports.issuedOn', { date: formatShortDate(document.delivered_at.slice(0, 10), settings) })}
            </p>
            {/* Keep focus here when Retry replaces the error with the viewer. */}
            <div
              ref={statusRef}
              tabIndex={-1}
              aria-busy={loading}
              aria-label={frameTitle}
              className="yearly-document-status"
            >
              {url && blob ? (
                <PdfPreview
                  src={url}
                  title={frameTitle}
                  actions={downloadButton}
                  openInNewTabFetcher={() => Promise.resolve(blob)}
                />
              ) : (
                <>
                  <div className="actions-row actions-row-wrap">
                    {downloadButton}
                  </div>
                  {loading ? (
                    <>
                      <p className="muted m-0" role="status" aria-live="polite">
                        {t('pages.reports.preparingDocument', { document: documentLabel, year })}
                      </p>
                      <div className="yearly-document-skeleton">
                        <PageSkeleton variant="card" />
                      </div>
                    </>
                  ) : error ? (
                    <div className="card error-banner page-stack" role="alert">
                      <p className="m-0">{t(descriptor.errorKey)}</p>
                      <div className="actions-row">
                        <button
                          className="button button-secondary button-compact"
                          type="button"
                          onClick={() => {
                            retryFocusPending.current = true
                            setRetryAttempt((n) => n + 1)
                          }}
                        >
                          {t('common.retry')}
                        </button>
                      </div>
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </>
        )}
      </div>
    </AppTabs.Panel>
  )
}

/**
 * The newest current document of ``kind`` for ``year`` that was issued to one of the account's own
 * participations (in ``zevId`` when given).
 */
export function issuedDocumentFor(
  documents: readonly DeliveredDocument[],
  kind: DocumentDescriptor['inboxKind'],
  year: number,
  ownIds: ReadonlySet<string>,
  zevId?: string,
): DeliveredDocument | undefined {
  return documents
    .filter((document) =>
      document.kind === kind
      && document.participant != null && ownIds.has(document.participant)
      && (!zevId || document.zev === zevId)
      && !document.superseded_at && !document.withdrawn_at
      && document.period_start?.slice(0, 4) === String(year))
    .sort((a, b) => b.delivered_at.localeCompare(a.delivered_at))[0]
}

/** The years for which the account has a current document of one of ``kinds``, newest first. */
export function issuedYears(
  documents: readonly DeliveredDocument[],
  kinds: ReadonlyArray<DocumentDescriptor['inboxKind']>,
  ownIds: ReadonlySet<string>,
  zevId?: string,
): number[] {
  const found = new Set<number>()
  for (const document of documents) {
    if (!(kinds as readonly string[]).includes(document.kind)) continue
    if (document.participant == null || !ownIds.has(document.participant)) continue
    if (zevId && document.zev !== zevId) continue
    if (document.superseded_at || document.withdrawn_at || !document.period_start) continue
    found.add(Number(document.period_start.slice(0, 4)))
  }
  return [...found].sort((a, b) => b - a)
}

export function ParticipantYearDocuments({ userId, zevId, year, years, onYearChange }: ParticipantYearDocumentsProps) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [active, setActive] = useState<DocumentKind>('annual-statement')
  // Its own cache entry: the filter makes it a different list from *My documents*.
  const query = useQuery({
    queryKey: queryKeys.inbox.list('mine', { kinds: ['annual_statement', 'financial_summary'] }),
    queryFn: () => listInboxDocuments({ kinds: ['annual_statement', 'financial_summary'] }),
  })
  const ownIds = useMemo(() => ownParticipantIds(user), [user])

  // Only what was issued is on offer: the years that have a document, and the tax overview tab only
  // for someone who has one at all (it is for producers). Until the list is there, or when nothing
  // was issued, the page keeps the plain year list and says so in the panel.
  const documents = query.data
  const issued = useMemo(
    () => (documents ? issuedYears(documents, ['annual_statement', 'financial_summary'], ownIds, zevId) : []),
    [documents, ownIds, zevId],
  )
  const offeredYears = issued.length > 0 ? issued : years
  const shownYear = offeredYears.includes(year) ? year : offeredYears[0]
  const hasSummary = !!documents && issuedYears(documents, ['financial_summary'], ownIds, zevId).length > 0
  const descriptors = hasSummary ? DESCRIPTORS : DESCRIPTORS.filter((descriptor) => descriptor.kind === 'annual-statement')
  const shownKind = descriptors.some((descriptor) => descriptor.kind === active) ? active : 'annual-statement'

  return (
    <div className="page-stack">
      <div className="actions-row">
        <YearPicker
          className="participant-document-year"
          id="participant-year-select"
          label={t('pages.reports.year')}
          years={offeredYears}
          value={shownYear}
          onChange={onYearChange}
        />
      </div>

      {query.isError && (
        <Notice tone="error" onRetry={() => void query.refetch()} isRetrying={query.isFetching}>{t('inbox.failed')}</Notice>
      )}
      {query.isLoading && <PageSkeleton variant="card" />}
      {documents && (
      <section id="yearly-documents-preview" aria-label={t('pages.reports.participantDescription')}>
        <AppTabs
          value={shownKind}
          onChange={(value) => {
            if (value === 'annual-statement' || value === 'tax-overview') setActive(value)
          }}
          keepMounted={false}
          activateTabWithKeyboard={false}
        >
          <AppTabs.List aria-label={t('pages.reports.documentTabs')}>
            {descriptors.map((descriptor) => (
              <AppTabs.Tab key={descriptor.kind} value={descriptor.kind}>
                {t(descriptor.titleKey)}
              </AppTabs.Tab>
            ))}
          </AppTabs.List>
          {descriptors.map((descriptor) => (
            <AnnualDocumentPanel
              key={`${descriptor.kind}-${userId}-${zevId ?? ''}-${shownYear}`}
              descriptor={descriptor}
              year={shownYear}
              document={issuedDocumentFor(documents, descriptor.inboxKind, shownYear, ownIds, zevId)}
              active={shownKind === descriptor.kind}
            />
          ))}
        </AppTabs>
      </section>
      )}
    </div>
  )
}
