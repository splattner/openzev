import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useManagedZev } from '../lib/managedZev'
import { AnnualStatementsExportCard } from '../features/reports/AnnualStatementsExportCard'
import { ReportsEmptyState } from '../features/reports/ReportsEmptyState'
import { PageSkeleton } from '../components/PageSkeleton'

const YEAR_COUNT = 5

/**
 * Annual statements tab (nav-regroup phase 3): the owner path — whole-ZEV
 * annual-statement ZIP. The ZEV-level tax overview lives in Reports;
 * participants keep their self-service statement at /me/statement. This tab
 * is owner/admin-only.
 */
export function BillingStatementsPage() {
    const { t } = useTranslation()
    const { selectedZevId, isLoading: managedZevLoading, managedZevs, selectedZev } = useManagedZev()

    const hasValidZev = !!(selectedZevId && selectedZev)
    const showGuard = !hasValidZev && !managedZevLoading

    // Recomputed per render so a long-lived session picks up the year rollover.
    const years = Array.from({ length: YEAR_COUNT }, (_, i) => new Date().getFullYear() - i)
    const [year, setYear] = useState(() => new Date().getFullYear() - 1)
    const selectedYear = years.includes(year) ? year : years[1]

    // Disable the shared year selector while the export card is preparing.
    const [zipBusy, setZipBusy] = useState(false)

    return (
        <div className="page-stack">

            {managedZevLoading && !hasValidZev && <PageSkeleton variant="cardList" />}

            {showGuard && <ReportsEmptyState hasManagedZevs={managedZevs.length > 0} />}

            {hasValidZev && (
                <>
                    <div className="actions-row">
                        <label className="inline-form">
                            <select
                                aria-label={t('pages.reports.year')}
                                value={selectedYear}
                                onChange={(e) => setYear(Number(e.target.value))}
                                disabled={zipBusy}
                            >
                                {years.map((y) => (
                                    <option key={y} value={y}>{y}</option>
                                ))}
                            </select>
                        </label>
                    </div>

                    <div>
                        <AnnualStatementsExportCard
                            zevId={selectedZevId}
                            year={selectedYear}
                            enabled={!!selectedZevId}
                            onBusyChange={setZipBusy}
                        />
                    </div>
                </>
            )}
        </div>
    )
}
