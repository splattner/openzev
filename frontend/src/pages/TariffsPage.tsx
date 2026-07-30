import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { TariffCategorySections } from '../features/tariffs/TariffCategorySections'
import { useTariffCrud } from '../features/tariffs/useTariffCrud'
import { TariffEmptyState } from '../features/tariffs/TariffEmptyState'
import { TariffExportModal } from '../features/tariffs/TariffExportModal'
import { TariffFormModal } from '../features/tariffs/TariffFormModal'
import { TariffImportModal } from '../features/tariffs/TariffImportModal'
import { TariffPeriodFormModal } from '../features/tariffs/TariffPeriodFormModal'
import { TariffToolbar, type TariffValidityFilter } from '../features/tariffs/TariffToolbar'
import { useTariffTransfer } from '../features/tariffs/useTariffTransfer'
import { isTariffCurrentlyValid, todayIso } from '../features/tariffs/validity'
import {
    fetchTariffPeriods,
    fetchTariffs,
} from '../lib/api/tariffs'
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

    const tariffsQuery = useQuery({
        queryKey: queryKeys.tariffs.list(selectedZevId || undefined),
        queryFn: fetchTariffs,
    })
    const periodsQuery = useQuery({ queryKey: queryKeys.tariffs.periods(), queryFn: fetchTariffPeriods })

    const tariffs = useMemo(
        () => (tariffsQuery.data?.results || []).filter((tariff) => !isManagedScope || !selectedZevId || tariff.zev === selectedZevId),
        [tariffsQuery.data?.results, isManagedScope, selectedZevId],
    )

    const allowedTariffIds = useMemo(() => new Set(tariffs.map((tariff) => tariff.id)), [tariffs])

    const periods = useMemo(
        () => (periodsQuery.data?.results || []).filter((period) => allowedTariffIds.has(period.tariff)),
        [periodsQuery.data?.results, allowedTariffIds],
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

    const visibleTariffs = useMemo(
        () => (validityFilter === 'all' ? tariffs : tariffs.filter((tariff) => isTariffCurrentlyValid(tariff, today))),
        [tariffs, validityFilter, today],
    )

    const tariffSections = useMemo(
        () =>
            tariffCategoryOrder
                .map((category) => ({
                    category,
                    tariffs: visibleTariffs.filter((tariff) => tariff.category === category),
                }))
                .filter((section) => section.tariffs.length > 0),
        [visibleTariffs],
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

    const {
        showExportModal,
        showImportModal,
        exportPending,
        openExportModal,
        closeExportModal,
        handleExport,
        openImportModal,
        closeImportModal,
        handleImportFile,
    } = useTariffTransfer({
        selectedZevId,
        queryClient,
        pushToast,
        t,
    })

    if (tariffsQuery.isLoading || periodsQuery.isLoading) {
        return <div className="card">{t('common.loading')}</div>
    }

    if (tariffsQuery.isError || periodsQuery.isError) {
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
                onOpenExportModal={openExportModal}
                onOpenImportModal={openImportModal}
            />

            <TariffExportModal
                isOpen={showExportModal}
                onClose={closeExportModal}
                onConfirmExport={handleExport}
                isPending={exportPending}
            />

            <TariffImportModal
                isOpen={showImportModal}
                onClose={closeImportModal}
                onImportFile={handleImportFile}
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
                <TariffEmptyState
                    onOpenCreateTariffModal={openCreateTariffModal}
                    onOpenImportModal={openImportModal}
                />
            ) : visibleTariffs.length === 0 ? (
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
                    periodsByTariff={periodsByTariff}
                    percentageBasePricing={percentageBasePricing}
                    settings={settings}
                    deleteTariffDisabled={deleteTariffPending || dialogLoading}
                    deletePeriodDisabled={deletePeriodPending || dialogLoading}
                    onEditTariff={startTariffEdit}
                    onDeleteTariff={confirmDeleteTariff}
                    onOpenCreatePeriodModal={openCreatePeriodModal}
                    onEditPeriod={startPeriodEdit}
                    onDeletePeriod={confirmDeletePeriod}
                />
            )}

            {dialog && (
                <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
            )}
        </div>
    )
}
