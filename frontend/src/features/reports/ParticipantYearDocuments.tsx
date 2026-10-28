import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AppTabs } from '../../components/AppTabs'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload } from '@fortawesome/free-solid-svg-icons'
import { PdfPreview } from '../../components/PdfPreview'
import { YearPicker } from '../../components/YearPicker'
import { PageSkeleton } from '../../components/PageSkeleton'
import { downloadBlob } from '../../lib/downloadBlob'
import { downloadAnnualStatement, downloadFinancialSummary } from '../../lib/api/invoices'
import { usePdfObjectUrl } from '../../lib/usePdfObjectUrl'

type ParticipantYearDocumentsProps = {
  userId: number
  /** The community to ask about; omitted, the server picks the account's first current membership. */
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
  load: (year: number, signal: AbortSignal, zevId?: string) => Promise<Blob>
}

const DESCRIPTORS: DocumentDescriptor[] = [
  {
    kind: 'annual-statement',
    titleKey: 'pages.reports.annualStatement.title',
    descriptionKey: 'pages.reports.annualStatement.description',
    errorKey: 'pages.reports.annualStatement.error',
    filenamePrefix: 'annual-statement',
    load: (year, signal, zevId) => downloadAnnualStatement({ year, ...(zevId ? { zev_id: zevId } : {}) }, signal),
  },
  {
    kind: 'tax-overview',
    titleKey: 'pages.reports.financialSummary.title',
    descriptionKey: 'pages.reports.financialSummary.description',
    errorKey: 'pages.reports.financialSummary.error',
    filenamePrefix: 'financial-summary',
    load: (year, signal, zevId) => downloadFinancialSummary({ year, ...(zevId ? { zev_id: zevId } : {}) }, signal),
  },
]

function AnnualDocumentPanel({
  descriptor,
  year,
  zevId,
  active,
}: {
  descriptor: DocumentDescriptor
  year: number
  zevId?: string
  active: boolean
}) {
  const { t } = useTranslation()
  const [requested, setRequested] = useState(() => active)
  const [retryAttempt, setRetryAttempt] = useState(0)
  const statusRef = useRef<HTMLDivElement>(null)
  const retryFocusPending = useRef(false)

  useEffect(() => {
    if (active) setRequested(true)
  }, [active])

  const fetcher = useMemo(() => {
    return (signal: AbortSignal) => descriptor.load(year, signal, zevId)
    // Retry changes the fetcher identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year, zevId, descriptor, retryAttempt])

  const { url, blob, loading, error } = usePdfObjectUrl(fetcher, requested)

  useEffect(() => {
    if (loading && retryFocusPending.current) {
      retryFocusPending.current = false
      statusRef.current?.focus()
    }
  }, [loading])

  const documentLabel = t(descriptor.titleKey) as string
  const frameTitle = t('pages.reports.documentTitle', { document: documentLabel, year }) as string
  const filename = `${descriptor.filenamePrefix}-${year}.pdf`

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
      </div>
    </AppTabs.Panel>
  )
}

export function ParticipantYearDocuments({ userId, zevId, year, years, onYearChange }: ParticipantYearDocumentsProps) {
  const { t } = useTranslation()
  const [active, setActive] = useState<DocumentKind>('annual-statement')

  return (
    <div className="page-stack">
      <div className="actions-row">
        <YearPicker
          className="participant-document-year"
          id="participant-year-select"
          label={t('pages.reports.year')}
          years={years}
          value={year}
          onChange={onYearChange}
        />
      </div>

      <section id="yearly-documents-preview" aria-label={t('pages.reports.participantDescription')}>
        <AppTabs
          value={active}
          onChange={(value) => {
            if (value === 'annual-statement' || value === 'tax-overview') setActive(value)
          }}
          keepMounted={false}
          activateTabWithKeyboard={false}
        >
          <AppTabs.List aria-label={t('pages.reports.documentTabs')}>
            {DESCRIPTORS.map((descriptor) => (
              <AppTabs.Tab key={descriptor.kind} value={descriptor.kind}>
                {t(descriptor.titleKey)}
              </AppTabs.Tab>
            ))}
          </AppTabs.List>
          {DESCRIPTORS.map((descriptor) => (
            <AnnualDocumentPanel
              key={`${descriptor.kind}-${userId}-${zevId ?? ''}-${year}`}
              descriptor={descriptor}
              year={year}
              zevId={zevId}
              active={active === descriptor.kind}
            />
          ))}
        </AppTabs>
      </section>
    </div>
  )
}
