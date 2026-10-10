import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation } from '@tanstack/react-query'
import { downloadFinancialSummary } from '../lib/api/invoices'
import { downloadBlob } from '../lib/downloadBlob'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'
import { YearDownloadCard } from '../features/reports/YearDownloadCard'
import { AnnualReportSection } from '../features/reports/AnnualReportSection'
import { AnnualStatementsExportCard } from '../features/reports/AnnualStatementsExportCard'
import { ParticipantYearDocuments } from '../features/reports/ParticipantYearDocuments'
import { PageHeader } from '../components/PageHeader'
import { ScopeGuard } from '../components/ScopeGuard'
import { YearPicker } from '../components/YearPicker'
import { selectedCommunityName } from '../lib/membership'

const YEAR_COUNT = 5

export function ReportsPage() {
    const { t } = useTranslation()
    const scopeNote = useScopeNote()
    const { user } = useAuth()
    const { entries, selectedZevId, selectedZev } = useManagedZev()

    const { isZevScope: isZevScopedRole, isParticipantScope: isParticipant } = useCommunityAccess()
    const participantZevId = isParticipant && (entries?.length ?? 0) > 1 ? selectedZevId : undefined
    const scopeName = selectedCommunityName({ selectedZev, entries, selectedZevId })

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
            <PageHeader
                eyebrow={scopeName}
                communitySwitch
                scopeNote={scopeNote}
                title={t('pages.reports.title')}
                description={isParticipant ? t('pages.reports.participantDescription') : t('pages.reports.description')}
            />

            <ScopeGuard>
                {isZevScopedRole && (
                    <>
                        <div className="actions-row">
                            <YearPicker
                                className="inline-form"
                                label={t('pages.reports.year')}
                                visibleLabel={false}
                                years={years}
                                value={selectedYear}
                                onChange={setYear}
                                disabled={financialSummaryMutation.isPending || zipBusy}
                            />
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
                        zevId={participantZevId}
                        year={selectedYear}
                        years={years}
                        onYearChange={setYear}
                    />
                )}
            </ScopeGuard>
        </div>
    )
}
