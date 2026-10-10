import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useEffectEvent, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { TariffCategorySections } from '../features/tariffs/TariffCategorySections'
import { TariffDetailDrawer } from '../features/tariffs/TariffDetailDrawer'
import { useTariffCrud } from '../features/tariffs/useTariffCrud'
import { TariffEmptyState } from '../features/tariffs/TariffEmptyState'
import { TariffFormModal } from '../features/tariffs/TariffFormModal'
import { VseTariffImportModal } from '../features/tariffs/VseTariffImportModal'
import { TariffPeriodFormModal } from '../features/tariffs/TariffPeriodFormModal'
import { TariffToolbar, type TariffValidityFilter } from '../features/tariffs/TariffToolbar'
import { TariffVersionModal } from '../features/tariffs/TariffVersionModal'
import { useTariffVersions } from '../features/tariffs/useTariffVersions'
import { isTariffCurrentlyValid } from '../features/tariffs/validity'
import { seriesKeyOf } from '../features/tariffs/useTariffDisplay'
import { tariffOverviewFilename, tariffOverviewParams } from '../features/tariffs/tariffOverview'
import { fetchTariffSeries } from '../lib/api/tariffs'
import { downloadTariffOverview } from '../lib/api/invoices'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { todayBusinessIso } from '../lib/dates'
import { downloadBlob } from '../lib/downloadBlob'
import { useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'
import { PageSkeleton } from '../components/PageSkeleton'
import { useTranslation } from 'react-i18next'
import { useToast } from '../lib/toast'
import type { Tariff, TariffSeries } from '../types/api'
import { PageHeader } from '../components/PageHeader'
import { Notice } from '../components/Notice'
import { ScopeGuard } from '../components/ScopeGuard'

const TARIFF_PARAM = 'tariff'
const VERSION_PARAM = 'version'

const tariffCategoryOrder: Tariff['category'][] = ['energy', 'grid_fees', 'levies', 'metering']

export function TariffsPage() {
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const { user } = useAuth()
    const cancelConfirmation = useEffectEvent(handleCancel)
    const { settings } = useAppSettings()
    const { selectedZevId, selectedZev } = useManagedZev()
    const { t } = useTranslation()
    const scopeNote = useScopeNote()
    const { isZevScope, canWriteSelectedCommunity } = useCommunityAccess()
    const isManagedScope = isZevScope
    const readOnly = !canWriteSelectedCommunity
    const [validityFilter, setValidityFilter] = useState<TariffValidityFilter>('valid')
    const [showImportModal, setShowImportModal] = useState(false)
    const [searchParams, setSearchParams] = useSearchParams()
    // Shared with the validity badge on each card, so the filter and the badge
    // can never disagree about whether a tariff is in force.
    const today = todayBusinessIso()

    // One query, not three: the series endpoint already groups versions, names
    // the active one, detects gaps, and nests each version's price bands. The
    // flat lists below are derived from it so nothing can drift out of step
    // after a mutation.
    const seriesQuery = useQuery({
        queryKey: queryKeys.tariffs.series(selectedZevId || undefined),
        queryFn: () => fetchTariffSeries(isManagedScope ? selectedZevId || undefined : undefined),
        enabled: !!selectedZevId && selectedZev?.id === selectedZevId,
    })

    const allSeries = useMemo(
        () => (seriesQuery.data ?? []).filter(
            (series) => !isManagedScope || series.zev === selectedZevId,
        ),
        [seriesQuery.data, isManagedScope, selectedZevId],
    )

    const tariffs = useMemo<Tariff[]>(
        () => allSeries.flatMap((series) => series.versions),
        [allSeries],
    )

    // The detail drawer's open tariff (and, within it, which version) lives in
    // the URL rather than component state: a reload, the back button, or a
    // shared link all reopen the same view instead of dropping back to the
    // bare list (#728).
    const openSeries = useMemo<TariffSeries | null>(() => {
        const key = searchParams.get(TARIFF_PARAM)
        if (!key) return null
        return allSeries.find((series) => seriesKeyOf(series) === key) ?? null
    }, [allSeries, searchParams])
    const shownVersionId = searchParams.get(VERSION_PARAM)

    function openDetail(series: TariffSeries) {
        setSearchParams((previous) => {
            const next = new URLSearchParams(previous)
            next.set(TARIFF_PARAM, seriesKeyOf(series))
            next.delete(VERSION_PARAM)
            return next
        }, { replace: true })
    }

    function closeDetail() {
        setSearchParams((previous) => {
            const next = new URLSearchParams(previous)
            next.delete(TARIFF_PARAM)
            next.delete(VERSION_PARAM)
            return next
        }, { replace: true })
    }

    function showVersion(versionId: string) {
        setSearchParams((previous) => {
            const next = new URLSearchParams(previous)
            next.set(VERSION_PARAM, versionId)
            return next
        }, { replace: true })
    }

    const periods = useMemo(
        () => allSeries.flatMap((series) => series.versions.flatMap((version) => version.periods)),
        [allSeries],
    )

    const tariffNameById = useMemo(() => {
        return new Map((tariffs || []).map((tariff) => [tariff.id, tariff.name]))
    }, [tariffs])

    // Energy and percentage-of-energy tariffs are the two modes that take
    // bands (§4.1); the period modal's tariff picker and its "nothing to add
    // a band to yet" fallback both need the broader list.
    const bandableTariffs = useMemo(() => {
        return tariffs.filter((tariff) => tariff.billing_mode === 'energy' || tariff.billing_mode === 'percentage_of_energy')
    }, [tariffs])

    // "Valid only" now hides whole series that have no version in force, which is
    // what collapses a pile of superseded tariffs down to what is current.
    // Resolved client-side with the same helper the validity badge uses, so the
    // filter and the badge cannot disagree.
    const validSeries = useMemo(
        () => allSeries.filter((series) => series.versions.some(
            (version) => isTariffCurrentlyValid(version, today),
        )),
        [allSeries, today],
    )
    const visibleSeries = validityFilter === 'all' ? allSeries : validSeries
    // Only then can the overview PDF differ between its two scopes; the list's
    // tabs need no such flag, as FilterTabs drops a tab that changes nothing.
    const hasOutOfForceVersions = useMemo(
        () => allSeries.some((series) => series.versions.some(
            (version) => !isTariffCurrentlyValid(version, today),
        )),
        [allSeries, today],
    )

    const tariffSections = useMemo(
        () =>
            tariffCategoryOrder
                .map((category) => ({
                    category,
                    series: visibleSeries.filter((series) => series.category === category),
                }))
                .filter((section) => section.series.length > 0),
        [visibleSeries],
    )

    const {
        showTariffModal,
        showPeriodModal,
        editingTariffId,
        editingPeriodId,
        periodModalTariffId,
        editingTariff,
        editingPeriod,
        tariffPending,
        periodPending,
        deleteTariffPending,
        deletePeriodPending,
        submitTariff,
        submitPeriod,
        startTariffEdit,
        startPeriodEdit,
        openCreateTariffModal,
        closeTariffModal,
        openCreatePeriodModal,
        closePeriodModal,
        confirmDeleteTariff,
        confirmDeletePeriod,
    } = useTariffCrud({
        selectedZevId,
        canWrite: !readOnly,
        tariffs,
        periods,
        bandableTariffs,
        tariffNameById,
        queryClient,
        pushToast,
        confirm,
        t,
    })

    const versions = useTariffVersions({ selectedZevId, canWrite: !readOnly, queryClient, pushToast, t })

    useEffect(() => {
        setShowImportModal(false)
        cancelConfirmation()
    }, [readOnly, selectedZevId, user?.id])

    // The scope is chosen at the download, not by the list's tabs: those
    // filter whole series, so "All" often changes nothing in the list while
    // it would still add every superseded version to the PDF.
    const overviewMutation = useMutation({
        mutationFn: (scope: TariffValidityFilter) => downloadTariffOverview(tariffOverviewParams(selectedZevId ?? '', scope)),
        onSuccess: (blob) => downloadBlob(blob, tariffOverviewFilename(today)),
        onError: (error) => pushToast(formatApiError(error, t('pages.tariffs.overviewPdf.error')), 'error'),
    })

    const header = (
        <PageHeader
            eyebrow={selectedZev?.name}
            communitySwitch
            scopeNote={scopeNote}
            title={t('pages.tariffs.title')}
            description={t('pages.tariffs.description')}
        />
    )

    return (
        <div className="page-stack">
            {header}
            <ScopeGuard skeleton="table">
            {seriesQuery.isLoading ? <PageSkeleton variant="table" /> : seriesQuery.isError ? (
                <Notice tone="error" onRetry={() => void seriesQuery.refetch()} isRetrying={seriesQuery.isFetching}>{t('common.error')}</Notice>
            ) : <>
            <TariffToolbar
                validCount={validSeries.length}
                totalCount={allSeries.length}
                hasOutOfForceVersions={hasOutOfForceVersions}
                validityFilter={validityFilter}
                onValidityFilterChange={setValidityFilter}
                onOpenCreateTariffModal={openCreateTariffModal}
                onOpenImportModal={selectedZevId && !readOnly ? () => setShowImportModal(true) : undefined}
                readOnly={readOnly}
                onDownloadOverview={selectedZevId ? (scope) => overviewMutation.mutate(scope) : undefined}
                overviewBusy={overviewMutation.isPending}
            />

            {selectedZev?.vat_mode === 'inclusive' && (
                <div className="info-banner">{t('pages.tariffs.vatInclusiveNotice')}</div>
            )}

            {selectedZevId && (
                <VseTariffImportModal
                    isOpen={showImportModal}
                    onClose={() => setShowImportModal(false)}
                    zevId={selectedZevId}
                    initialUrl={selectedZev?.tariff_source_url ?? ''}
                />
            )}

            <TariffFormModal
                isOpen={showTariffModal}
                title={editingTariffId ? t('pages.tariffs.editTitle') : t('pages.tariffs.createTitle')}
                onClose={closeTariffModal}
                onSubmit={submitTariff}
                initialTariff={editingTariff}
                selectedZevId={selectedZevId || ''}
                isPending={tariffPending}
            />

            <TariffVersionModal
                settings={settings}
                dialog={versions.dialog}
                isPending={versions.isPending}
                onClose={versions.closeDialog}
                onSubmitNewVersion={versions.submitNewVersion}
                onSubmitDuplicate={versions.submitDuplicate}
                onSubmitRename={versions.submitRename}
            />

            <TariffPeriodFormModal
                isOpen={showPeriodModal}
                title={editingPeriodId ? t('pages.tariffs.editPeriodTitle') : t('pages.tariffs.createPeriodTitle')}
                onClose={closePeriodModal}
                onSubmit={submitPeriod}
                initialPeriod={editingPeriod}
                defaultTariffId={periodModalTariffId}
                tariffs={bandableTariffs}
                isPending={periodPending}
            />

            {tariffs.length === 0 ? (
                <TariffEmptyState onOpenCreateTariffModal={openCreateTariffModal} readOnly={readOnly} />
            ) : visibleSeries.length === 0 ? (
                <section className="card" style={{ display: 'grid', gap: '0.75rem' }}>
                    <h3 style={{ margin: 0 }}>{t('pages.tariffs.noResults.title')}</h3>
                    <p className="muted" style={{ margin: 0 }}>{t('pages.tariffs.noResults.description')}</p>
                    <div>
                        <button className="button button-secondary" type="button" onClick={() => setValidityFilter('all')}>
                            {t('pages.tariffs.filters.clear')}
                        </button>
                    </div>
                </section>
            ) : (
                <TariffCategorySections
                    settings={settings}
                    tariffSections={tariffSections}
                    openSeriesKey={openSeries ? seriesKeyOf(openSeries) : null}
                    onEditTariff={startTariffEdit}
                    onOpenDetail={openDetail}
                    readOnly={readOnly}
                />
            )}

            <TariffDetailDrawer
                series={openSeries}
                allSeries={allSeries}
                settings={settings}
                shownVersionId={shownVersionId}
                onShowVersion={showVersion}
                deleteTariffDisabled={deleteTariffPending || dialogLoading}
                deletePeriodDisabled={deletePeriodPending || dialogLoading}
                onClose={closeDetail}
                onEditTariff={startTariffEdit}
                onDeleteTariff={confirmDeleteTariff}
                onOpenCreatePeriodModal={openCreatePeriodModal}
                onEditPeriod={startPeriodEdit}
                onDeletePeriod={confirmDeletePeriod}
                onNewVersion={versions.openNewVersion}
                onDuplicate={versions.openDuplicate}
                onRenameSeries={versions.openRename}
                readOnly={readOnly}
            />

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
            </>}
            </ScopeGuard>
        </div>
    )
}
