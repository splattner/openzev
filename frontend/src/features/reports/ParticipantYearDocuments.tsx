import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Tabs } from '@mantine/core'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload } from '@fortawesome/free-solid-svg-icons'
import { PdfPreview } from '../../components/PdfPreview'
import { PageSkeleton } from '../../components/PageSkeleton'
import { downloadBlob } from '../../lib/downloadBlob'
import { downloadAnnualStatement, downloadFinancialSummary } from '../../lib/api/invoices'
import { usePdfObjectUrl } from '../../lib/usePdfObjectUrl'

type ParticipantYearDocumentsProps = {
  userId: number
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
  load: (year: number, signal: AbortSignal) => Promise<Blob>
}

const DESCRIPTORS: DocumentDescriptor[] = [
  {
    kind: 'annual-statement',
    titleKey: 'pages.reports.annualStatement.title',
    descriptionKey: 'pages.reports.annualStatement.description',
    errorKey: 'pages.reports.annualStatement.error',
    filenamePrefix: 'annual-statement',
    load: (year, signal) => downloadAnnualStatement({ year }, signal),
  },
  {
    kind: 'tax-overview',
    titleKey: 'pages.reports.financialSummary.title',
    descriptionKey: 'pages.reports.financialSummary.description',
    errorKey: 'pages.reports.financialSummary.error',
    filenamePrefix: 'financial-summary',
    load: (year, signal) => downloadFinancialSummary({ year }, signal),
  },
]

function AnnualDocumentPanel({
  descriptor,
  year,
  active,
}: {
  descriptor: DocumentDescriptor
  year: number
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
    return (signal: AbortSignal) => descriptor.load(year, signal)
    // Retry changes the fetcher identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year, descriptor, retryAttempt])

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
    <Tabs.Panel value={descriptor.kind} aria-busy={loading}>
      <div className="page-stack">
        <p className="muted" style={{ margin: 0 }}>{t(descriptor.descriptionKey)}</p>
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
                  <p className="muted" role="status" aria-live="polite" style={{ margin: 0 }}>
                    {t('pages.reports.preparingDocument', { document: documentLabel, year })}
                  </p>
                  <div className="yearly-document-skeleton">
                    <PageSkeleton variant="card" />
                  </div>
                </>
              ) : error ? (
                <div className="card error-banner page-stack" role="alert">
                  <p style={{ margin: 0 }}>{t(descriptor.errorKey)}</p>
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
    </Tabs.Panel>
  )
}

export function ParticipantYearDocuments({ userId, year, years, onYearChange }: ParticipantYearDocumentsProps) {
  const { t } = useTranslation()
  const [active, setActive] = useState<DocumentKind>('annual-statement')

  return (
    <div className="page-stack">
      <div className="actions-row">
        <label className="participant-document-year" htmlFor="participant-year-select">
          <span>{t('pages.reports.year')}</span>
          <select
            id="participant-year-select"
            value={year}
            onChange={(e) => onYearChange(Number(e.target.value))}
          >
            {years.map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </label>
      </div>

      <section id="yearly-documents-preview" aria-label={t('pages.reports.participantDescription')}>
        <Tabs
          classNames={{ root: 'app-tabs', list: 'app-tabs-list', tab: 'app-tabs-tab' }}
          value={active}
          onChange={(value) => {
            if (value === 'annual-statement' || value === 'tax-overview') setActive(value)
          }}
          keepMounted={false}
          activateTabWithKeyboard={false}
        >
          <Tabs.List aria-label={t('pages.reports.documentTabs')}>
            {DESCRIPTORS.map((descriptor) => (
              <Tabs.Tab key={descriptor.kind} value={descriptor.kind}>
                {t(descriptor.titleKey)}
              </Tabs.Tab>
            ))}
          </Tabs.List>
          {DESCRIPTORS.map((descriptor) => (
            <AnnualDocumentPanel
              key={`${descriptor.kind}-${userId}-${year}`}
              descriptor={descriptor}
              year={year}
              active={active === descriptor.kind}
            />
          ))}
        </Tabs>
      </section>
    </div>
  )
}
