import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation } from '@tanstack/react-query'
import { downloadAnnualStatement, downloadFinancialSummary } from '../lib/api/invoices'
import { downloadBlob } from '../lib/downloadBlob'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { ReportsEmptyState } from '../features/reports/ReportsEmptyState'
import { YearDownloadCard } from '../features/reports/YearDownloadCard'
import { PageSkeleton } from '../components/PageSkeleton'

const YEAR_COUNT = 5

function useYearDownload(fn: () => Promise<Blob>, filename: () => string) {
    return useMutation({
        mutationFn: fn,
        onSuccess: (blob) => downloadBlob(blob, filename()),
    })
}

/**
 * Self-service statement downloads (nav-regroup phase 3).
 *
 * Participants download their own annual-statement PDF here — this page is
 * the canonical host of `/me/statement`.
 *
 * Owners and admins use this page for the ZEV-level tax overview and the
 * upcoming analytics views. The whole-ZEV annual-statement ZIP remains in the
 * Billing hub's Annual statements tab.
 */
export function ReportsPage() {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { selectedZevId, isLoading: managedZevLoading, managedZevs, selectedZev } = useManagedZev()

    const isZevScopedRole = user?.role === 'admin' || user?.role === 'zev_owner'
    const hasValidZev = !isZevScopedRole || !!(selectedZevId && selectedZev)
    const showGuard = isZevScopedRole && !hasValidZev && !managedZevLoading
    // Owners read the name from the switcher selection; participants from /auth/me.
    const scopeName = isZevScopedRole ? selectedZev?.name : user?.zev_name

    // Recomputed per render so a long-lived session picks up the year rollover.
    const years = Array.from({ length: YEAR_COUNT }, (_, i) => new Date().getFullYear() - i)
    const [year, setYear] = useState(() => new Date().getFullYear() - 1)
    const selectedYear = years.includes(year) ? year : years[1]

    const annualStatementMutation = useYearDownload(
        () => downloadAnnualStatement({ year: selectedYear }),
        () => `annual-statement-${selectedYear}.pdf`,
    )

    const financialSummaryMutation = useYearDownload(
        () => downloadFinancialSummary({
            year: selectedYear,
            ...(isZevScopedRole && selectedZevId ? { zev_id: selectedZevId } : {}),
        }),
        () => `financial-summary-${selectedYear}.pdf`,
    )

    return (
        <div className="page-stack">
            <header>
                {scopeName ? <p className="eyebrow">{scopeName}</p> : null}
                <h2>{t('pages.reports.title')}</h2>
                <p className="muted">{t('pages.reports.description')}</p>
            </header>

            {isZevScopedRole && managedZevLoading && !hasValidZev && <PageSkeleton variant="cardList" />}

            {showGuard && <ReportsEmptyState hasManagedZevs={managedZevs.length > 0} />}

            {/* Owner/admin: the ZEV-level tax overview belongs to Reports;
                the remaining analytics views are planned below it. */}
            {isZevScopedRole && hasValidZev && (
                <>
                    <div className="actions-row">
                        <label className="inline-form">
                            <select
                                aria-label={t('pages.reports.year')}
                                value={selectedYear}
                                onChange={(e) => setYear(Number(e.target.value))}
                                disabled={financialSummaryMutation.isPending}
                            >
                                {years.map((y) => (
                                    <option key={y} value={y}>{y}</option>
                                ))}
                            </select>
                        </label>
                    </div>

                    <YearDownloadCard
                        titleKey="pages.reports.financialSummary.title"
                        descriptionKey="pages.reports.financialSummary.ownerDescription"
                        busy={financialSummaryMutation.isPending}
                        error={financialSummaryMutation.isError ? t('pages.reports.financialSummary.error') : null}
                        onDownload={() => financialSummaryMutation.mutate()}
                        actionLabelKey="pages.reports.financialSummary.download"
                    />

                    <div className="card page-stack">
                        <h3 style={{ marginTop: 0 }}>{t('pages.reports.ownerComing.title')}</h3>
                        <p className="muted" style={{ margin: 0 }}>
                            {t('pages.reports.ownerComing.description')}
                        </p>
                    </div>
                </>
            )}

            {/* Participant: own annual statement + producer tax overview
                (same cards as /me/statement). */}
            {!isZevScopedRole && (
                <>
                    <div className="actions-row">
                        <label className="inline-form">
                            <select
                                aria-label={t('pages.reports.year')}
                                value={selectedYear}
                                onChange={(e) => setYear(Number(e.target.value))}
                                disabled={annualStatementMutation.isPending || financialSummaryMutation.isPending}
                            >
                                {years.map((y) => (
                                    <option key={y} value={y}>{y}</option>
                                ))}
                            </select>
                        </label>
                    </div>

                    <div className="grid grid-2">
                        <YearDownloadCard
                            titleKey="pages.reports.annualStatement.title"
                            descriptionKey="pages.reports.annualStatement.description"
                            busy={annualStatementMutation.isPending}
                            error={annualStatementMutation.isError ? t('pages.reports.annualStatement.error') : null}
                            onDownload={() => annualStatementMutation.mutate()}
                            actionLabelKey="pages.reports.annualStatement.download"
                        />
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
