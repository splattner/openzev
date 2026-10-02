import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation } from '@tanstack/react-query'
import { downloadFinancialSummary } from '../lib/api/invoices'
import { downloadBlob } from '../lib/downloadBlob'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useCommunityAccess } from '../lib/communityAccess'
import { ReportsEmptyState } from '../features/reports/ReportsEmptyState'
import { YearDownloadCard } from '../features/reports/YearDownloadCard'
import { AnnualReportSection } from '../features/reports/AnnualReportSection'
import { AnnualStatementsExportCard } from '../features/reports/AnnualStatementsExportCard'
import { ParticipantYearDocuments } from '../features/reports/ParticipantYearDocuments'
import { PageSkeleton } from '../components/PageSkeleton'

const YEAR_COUNT = 5

export function ReportsPage() {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { selectedZevId, isLoading: managedZevLoading, managedZevs, selectedZev } = useManagedZev()

    const { isZevScope: isZevScopedRole, isParticipantScope: isParticipant } = useCommunityAccess()
    const hasValidZev = !isZevScopedRole || !!(selectedZevId && selectedZev)
    const showGuard = isZevScopedRole && !hasValidZev && !managedZevLoading
    const scopeName = isZevScopedRole ? selectedZev?.name : user?.zev_name

    // Recomputed per render so a long-lived session picks up the year rollover.
    const years = Array.from({ length: YEAR_COUNT }, (_, i) => new Date().getFullYear() - i)
    const [year, setYear] = useState(() => new Date().getFullYear() - 1)
    const selectedYear = years.includes(year) ? year : years[1]
    // Disable the shared year selector while the ZIP export is preparing.
    const [zipBusy, setZipBusy] = useState(false)

    const financialSummaryMutation = useMutation({
        mutationFn: () => downloadFinancialSummary({
            year: selectedYear,
            ...(isZevScopedRole && selectedZevId ? { zev_id: selectedZevId } : {}),
        }),
        onSuccess: (blob) => downloadBlob(blob, `financial-summary-${selectedYear}.pdf`),
    })

    return (
        <div className="page-stack">
            <header>
                {scopeName ? <p className="eyebrow">{scopeName}</p> : null}
                <h2>{t('pages.reports.title')}</h2>
                <p className="muted">
                    {isParticipant ? t('pages.reports.participantDescription') : t('pages.reports.description')}
                </p>
            </header>

            {isZevScopedRole && managedZevLoading && !hasValidZev && <PageSkeleton variant="cardList" />}

            {showGuard && <ReportsEmptyState hasManagedZevs={managedZevs.length > 0} />}

            {isZevScopedRole && hasValidZev && (
                <>
                    <div className="actions-row">
                        <label className="inline-form">
                            <select
                                aria-label={t('pages.reports.year')}
                                value={selectedYear}
                                onChange={(e) => setYear(Number(e.target.value))}
                                disabled={financialSummaryMutation.isPending || zipBusy}
                            >
                                {years.map((y) => (
                                    <option key={y} value={y}>{y}</option>
                                ))}
                            </select>
                        </label>
                    </div>

                    <AnnualReportSection zevId={selectedZevId} year={selectedYear} />

                    <h3 style={{ margin: '0.5rem 0 0' }}>{t('pages.reports.documentsTitle')}</h3>
                    <div className="grid grid-2">
                        <YearDownloadCard
                            titleKey="pages.reports.financialSummary.title"
                            descriptionKey="pages.reports.financialSummary.ownerDescription"
                            busy={financialSummaryMutation.isPending}
                            error={financialSummaryMutation.isError ? t('pages.reports.financialSummary.error') : null}
                            onDownload={() => financialSummaryMutation.mutate()}
                            actionLabelKey="pages.reports.financialSummary.download"
                        />
                        <AnnualStatementsExportCard
                            zevId={selectedZevId}
                            year={selectedYear}
                            enabled={!!selectedZevId}
                            onBusyChange={setZipBusy}
                        />
                    </div>
                </>
            )}

            {isParticipant && user && (
                <ParticipantYearDocuments
                    key={user.id}
                    userId={user.id}
                    year={selectedYear}
                    years={years}
                    onYearChange={setYear}
                />
            )}
        </div>
    )
}
