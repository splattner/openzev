import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation } from '@tanstack/react-query'
import { downloadAnnualStatement, downloadFinancialSummary } from '../lib/api/invoices'
import { downloadBlob } from '../lib/downloadBlob'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { ReportsEmptyState } from '../features/reports/ReportsEmptyState'
import { YearDownloadCard } from '../features/reports/YearDownloadCard'
import { AnnualStatementsExportCard } from '../features/reports/AnnualStatementsExportCard'
import { PageSkeleton } from '../components/PageSkeleton'

const YEAR_COUNT = 5

function useYearDownload(fn: () => Promise<Blob>, filename: () => string) {
    return useMutation({
        mutationFn: fn,
        onSuccess: (blob) => downloadBlob(blob, filename()),
    })
}

export function ReportsPage() {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { selectedZevId, isLoading: managedZevLoading, managedZevs, selectedZev } = useManagedZev()

    const isZevScopedRole = user?.role === 'admin' || user?.role === 'zev_owner'
    const hasValidZev = !isZevScopedRole || !!(selectedZevId && selectedZev)
    const showGuard = isZevScopedRole && !hasValidZev && !managedZevLoading

    // Recomputed per render so a long-lived session picks up the year rollover.
    const years = Array.from({ length: YEAR_COUNT }, (_, i) => new Date().getFullYear() - i)
    const [year, setYear] = useState(() => new Date().getFullYear() - 1)
    const selectedYear = years.includes(year) ? year : years[1]

    // Disable the shared year selector while the ZIP card is preparing.
    const [zipBusy, setZipBusy] = useState(false)

    const annualStatementMutation = useYearDownload(
        () => downloadAnnualStatement({ year: selectedYear }),
        () => `annual-statement-${selectedYear}.pdf`,
    )

    const financialSummaryMutation = useYearDownload(
        () => downloadFinancialSummary({ year: selectedYear, zev_id: isZevScopedRole ? selectedZevId || undefined : undefined }),
        () => `financial-summary-${selectedYear}.pdf`,
    )

    const busy = zipBusy || annualStatementMutation.isPending || financialSummaryMutation.isPending

    return (
        <div className="page-stack">
            <header>
                {isZevScopedRole && selectedZev?.name ? <p className="eyebrow">{selectedZev.name}</p> : null}
                <h2>{t('pages.reports.title')}</h2>
                <p className="muted">{t('pages.reports.description')}</p>
            </header>

            {isZevScopedRole && managedZevLoading && !hasValidZev && <PageSkeleton variant="cardList" />}

            {showGuard && <ReportsEmptyState hasManagedZevs={managedZevs.length > 0} />}

            {hasValidZev && (
                <>
                    <div className="actions-row">
                        <label className="inline-form">
                            <select
                                aria-label={t('pages.reports.year')}
                                value={selectedYear}
                                onChange={(e) => setYear(Number(e.target.value))}
                                disabled={busy}
                            >
                                {years.map((y) => (
                                    <option key={y} value={y}>{y}</option>
                                ))}
                            </select>
                        </label>
                    </div>

                    <div className="grid grid-2">
                        {isZevScopedRole ? (
                            <AnnualStatementsExportCard
                                zevId={selectedZevId}
                                year={selectedYear}
                                enabled={!!selectedZevId}
                                onBusyChange={setZipBusy}
                            />
                        ) : (
                            <YearDownloadCard
                                titleKey="pages.reports.annualStatement.title"
                                descriptionKey="pages.reports.annualStatement.description"
                                busy={annualStatementMutation.isPending}
                                error={annualStatementMutation.isError ? t('pages.reports.annualStatement.error') : null}
                                onDownload={() => annualStatementMutation.mutate()}
                                actionLabelKey="pages.reports.annualStatement.download"
                            />
                        )}
                        <YearDownloadCard
                            titleKey="pages.reports.financialSummary.title"
                            descriptionKey="pages.reports.financialSummary.description"
                            busy={financialSummaryMutation.isPending}
                            error={financialSummaryMutation.isError ? t('pages.reports.financialSummary.error') : null}
                            onDownload={() => financialSummaryMutation.mutate()}
                            actionLabelKey="pages.reports.financialSummary.download"
                        />
                    </div>
                </>
            )}
        </div>
    )
}
