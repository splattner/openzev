import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { TariffCategorySections } from '../features/tariffs/TariffCategorySections'
import { useTariffCrud } from '../features/tariffs/useTariffCrud'
import { TariffEmptyState } from '../features/tariffs/TariffEmptyState'
import { TariffFormModal } from '../features/tariffs/TariffFormModal'
import { TariffPeriodFormModal } from '../features/tariffs/TariffPeriodFormModal'
import { TariffToolbar, type TariffValidityFilter } from '../features/tariffs/TariffToolbar'
import { TariffVersionModal } from '../features/tariffs/TariffVersionModal'
import { useTariffVersions } from '../features/tariffs/useTariffVersions'
import { isTariffCurrentlyValid, todayIso } from '../features/tariffs/validity'
import { fetchTariffSeries } from '../lib/api/tariffs'
import { queryKeys } from '../lib/api/queryKeys'
import { useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { useManagedZev } from '../lib/managedZev'
import { useTranslation } from 'react-i18next'
import { useToast } from '../lib/toast'
import type { Tariff, TariffPeriod } from '../types/api'

const tariffCategoryOrder: Tariff['category'][] = ['energy', 'grid_fees', 'levies', 'metering']

export function TariffsPage() {
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const { user } = useAuth()
    const { settings } = useAppSettings()
    const { selectedZevId } = useManagedZev()
    const { t } = useTranslation()
    const isManagedScope = user?.role === 'admin' || user?.role === 'zev_owner'
    const [validityFilter, setValidityFilter] = useState<TariffValidityFilter>('valid')
    // Shared with the validity badge on each card, so the filter and the badge
    // can never disagree about whether a tariff is in force.
    const today = useMemo(() => todayIso(), [])

    // One query, not three: the series endpoint already groups versions, names
    // the active one, detects gaps, and nests each version's price bands. The
    // flat lists below are derived from it so nothing can drift out of step
    // after a mutation.
    const seriesQuery = useQuery({
        queryKey: queryKeys.tariffs.series(selectedZevId || undefined),
        queryFn: () => fetchTariffSeries(isManagedScope ? selectedZevId || undefined : undefined),
    })

    const allSeries = useMemo(
        () => (seriesQuery.data ?? []).filter(
            (series) => !isManagedScope || !selectedZevId || series.zev === selectedZevId,
        ),
        [seriesQuery.data, isManagedScope, selectedZevId],
    )

    const tariffs = useMemo<Tariff[]>(
        () => allSeries.flatMap((series) => series.versions),
        [allSeries],
    )

    const periods = useMemo(
        () => allSeries.flatMap((series) => series.versions.flatMap((version) => version.periods)),
        [allSeries],
    )

    const periodsByTariff = useMemo(() => {
        const grouped = new Map<string, TariffPeriod[]>()

        periods.forEach((period) => {
            const existing = grouped.get(period.tariff) ?? []
            existing.push(period)
            grouped.set(period.tariff, existing)
        })

        grouped.forEach((tariffPeriods) => {
            tariffPeriods.sort((left, right) => {
                const periodTypeOrder = { flat: 0, high: 1, low: 2 }
                const typeDelta = periodTypeOrder[left.period_type] - periodTypeOrder[right.period_type]
                if (typeDelta !== 0) return typeDelta

                const fromDelta = (left.time_from ?? '').localeCompare(right.time_from ?? '')
                if (fromDelta !== 0) return fromDelta

                return (left.time_to ?? '').localeCompare(right.time_to ?? '')
            })
        })

        return grouped
    }, [periods])

    const tariffNameById = useMemo(() => {
        return new Map((tariffs || []).map((tariff) => [tariff.id, tariff.name]))
    }, [tariffs])

    const energyTariffs = useMemo(() => {
        return tariffs.filter((tariff) => tariff.billing_mode === 'energy')
    }, [tariffs])

    // Percentage-of-energy tariffs price any energy type as a fraction of the
    // active GRID energy tariff(s) — mirrors the resolution used for billing
    // (backend/invoices/engine.py) and the ZEV contract PDF, using the same
    // "prefer flat, else HT, else first period" representative price per tariff.
    const percentageBasePricing = useMemo(() => {
        const gridTariffsByZev = new Map<string, Tariff[]>()
        tariffs
            .filter((tariff) => tariff.billing_mode === 'energy' && tariff.energy_type === 'grid')
            .forEach((tariff) => {
                const existing = gridTariffsByZev.get(tariff.zev) ?? []
                existing.push(tariff)
                gridTariffsByZev.set(tariff.zev, existing)
            })

        const result = new Map<string, number>()
        tariffs
            .filter((tariff) => tariff.billing_mode === 'percentage_of_energy')
            .forEach((pctTariff) => {
                const candidateGridTariffs = (gridTariffsByZev.get(pctTariff.zev) ?? []).filter(
                    (gridTariff) =>
                        gridTariff.valid_from <= pctTariff.valid_from &&
                        (!gridTariff.valid_to || gridTariff.valid_to >= pctTariff.valid_from),
                )
                const basePrice = candidateGridTariffs.reduce((sum, gridTariff) => {
                    const representativePeriod = periodsByTariff.get(gridTariff.id)?.[0]
                    return sum + (representativePeriod ? Number(representativePeriod.price_chf_per_kwh) : 0)
                }, 0)
                if (basePrice > 0) {
                    result.set(pctTariff.id, basePrice)
                }
            })
        return result
    }, [tariffs, periodsByTariff])

    const tariffsWithPeriodsCount = useMemo(
        () => tariffs.filter((tariff) => (periodsByTariff.get(tariff.id)?.length ?? 0) > 0).length,
        [tariffs, periodsByTariff],
    )

    // "Valid only" now hides whole series that have no version in force, which is
    // what collapses a pile of superseded tariffs down to what is current.
    // Resolved client-side with the same helper the validity badge uses, so the
    // filter and the badge cannot disagree.
    const visibleSeries = useMemo(
        () => (validityFilter === 'all'
            ? allSeries
            : allSeries.filter((series) => series.versions.some(
                (version) => isTariffCurrentlyValid(version, today),
            ))),
        [allSeries, validityFilter, today],
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
        tariffs,
        periods,
        energyTariffs,
        tariffNameById,
        queryClient,
        pushToast,
        confirm,
        t,
    })

    const versions = useTariffVersions({ selectedZevId, queryClient, pushToast, t })

    if (seriesQuery.isLoading) {
        return <div className="card">{t('common.loading')}</div>
    }

    if (seriesQuery.isError) {
        return <div className="card error-banner">{t('common.error')}</div>
    }

    return (
        <div className="page-stack">
            <header>
                <h2>{t('pages.tariffs.title')}</h2>
                <p className="muted">{t('pages.tariffs.description')}</p>
            </header>

            <TariffToolbar
                tariffCount={tariffs.length}
                energyTariffCount={energyTariffs.length}
                tariffsWithPeriodsCount={tariffsWithPeriodsCount}
                periodCount={periods.length}
                validityFilter={validityFilter}
                onValidityFilterChange={setValidityFilter}
                onOpenCreateTariffModal={openCreateTariffModal}
            />

            <TariffFormModal
                isOpen={showTariffModal}
                title={editingTariffId ? t('pages.tariffs.editTitle') : t('pages.tariffs.createTitle')}
                onClose={closeTariffModal}
                onSubmit={submitTariff}
                initialTariff={editingTariff}
                selectedZevId={selectedZevId || ''}
                settings={settings}
                isPending={tariffPending}
            />

            <TariffVersionModal
                dialog={versions.dialog}
                settings={settings}
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
                energyTariffs={energyTariffs}
                isPending={periodPending}
            />

            {tariffs.length === 0 ? (
                <TariffEmptyState onOpenCreateTariffModal={openCreateTariffModal} />
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
                    tariffSections={tariffSections}
                    allSeries={allSeries}
                    percentageBasePricing={percentageBasePricing}
                    settings={settings}
                    deleteTariffDisabled={deleteTariffPending || dialogLoading}
                    deletePeriodDisabled={deletePeriodPending || dialogLoading}
                    onEditTariff={startTariffEdit}
                    onDeleteTariff={confirmDeleteTariff}
                    onOpenCreatePeriodModal={openCreatePeriodModal}
                    onEditPeriod={startPeriodEdit}
                    onDeletePeriod={confirmDeletePeriod}
                    onNewVersion={versions.openNewVersion}
                    onDuplicate={versions.openDuplicate}
                    onRenameSeries={versions.openRename}
                />
            )}

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
        </div>
    )
}
