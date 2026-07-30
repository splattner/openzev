import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faChevronDown,
    faChevronUp,
    faPen,
    faPlus,
    faTrash,
} from '@fortawesome/free-solid-svg-icons'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../lib/appSettings'
import type { AppSettings, Tariff, TariffPeriod } from '../../types/api'
import { todayIso, validityState, type ValidityState } from './validity'

type TariffSection = {
    category: Tariff['category']
    tariffs: Tariff[]
}

// Amber rather than blue for scheduled: blue is already the billing-mode badge
// sitting right next to it, and two adjacent blue badges read as one group.
const VALIDITY_BADGE_CLASS: Record<ValidityState, string> = {
    active: 'badge badge-success',
    scheduled: 'badge badge-warning',
    expired: 'badge badge-neutral',
}

type TariffCategorySectionsProps = {
    tariffSections: TariffSection[]
    periodsByTariff: Map<string, TariffPeriod[]>
    percentageBasePricing: Map<string, number>
    settings: AppSettings
    deleteTariffDisabled: boolean
    deletePeriodDisabled: boolean
    onEditTariff: (tariff: Tariff) => void
    onDeleteTariff: (tariff: Tariff) => void
    onOpenCreatePeriodModal: (tariffId: string) => void
    onEditPeriod: (period: TariffPeriod) => void
    onDeletePeriod: (period: TariffPeriod) => void
}

export function TariffCategorySections({
    tariffSections,
    periodsByTariff,
    percentageBasePricing,
    settings,
    deleteTariffDisabled,
    deletePeriodDisabled,
    onEditTariff,
    onDeleteTariff,
    onOpenCreatePeriodModal,
    onEditPeriod,
    onDeletePeriod,
}: TariffCategorySectionsProps) {
    const { t } = useTranslation()
    const [expandedTariffIds, setExpandedTariffIds] = useState<Set<string>>(new Set())
    const today = todayIso()

    const toggleExpanded = (tariffId: string) => {
        setExpandedTariffIds((current) => {
            const next = new Set(current)
            if (next.has(tariffId)) {
                next.delete(tariffId)
            } else {
                next.add(tariffId)
            }
            return next
        })
    }

    return (
        <div className="tariff-category-sections">
            {tariffSections.map((section) => (
                <section
                    key={section.category}
                    className={`tariff-category-section tariff-category-section-${section.category.replace(/_/g, '-')}`}
                >
                    <div className="tariff-category-header">
                        <div className="tariff-category-title-row">
                            <h3>{t(`pages.tariffs.categories.${section.category}` as Parameters<typeof t>[0])}</h3>
                            <span className="badge badge-neutral">{section.tariffs.length}</span>
                        </div>
                    </div>

                    <div className="tariff-card-list">
                        {section.tariffs.map((tariff) => {
                            const tariffPeriods = periodsByTariff.get(tariff.id) ?? []
                            const usesPeriods = tariff.billing_mode === 'energy'
                            const energyTypeLabel = t(`pages.tariffs.energyTypes.${tariff.energy_type || 'local'}` as Parameters<typeof t>[0])
                            const basePrice = percentageBasePricing.get(tariff.id)
                            const pricingLabel = tariff.billing_mode === 'energy'
                                ? energyTypeLabel
                                : tariff.billing_mode === 'percentage_of_energy'
                                    ? basePrice
                                        ? `${tariff.percentage ?? '0'}% · ${energyTypeLabel} · ${t('pages.tariffs.approxPrice', { price: (basePrice * Number(tariff.percentage ?? 0) / 100).toFixed(3) })}`
                                        : `${tariff.percentage ?? '0'}% · ${energyTypeLabel}`
                                    : `CHF ${tariff.fixed_price_chf || '0.00'}`
                            const pricingTooltip = tariff.billing_mode === 'percentage_of_energy' && basePrice
                                ? t('pages.tariffs.approxPriceTooltip', {
                                    percentage: tariff.percentage ?? '0',
                                    basePrice: basePrice.toFixed(3),
                                    effectivePrice: (basePrice * Number(tariff.percentage ?? 0) / 100).toFixed(3),
                                })
                                : undefined
                            const notes = tariff.notes?.trim()
                            const isExpanded = expandedTariffIds.has(tariff.id)

                            // The badge names the date that matters for the
                            // tariff's current state, so the state is carried by
                            // the wording as well as the colour. The full window
                            // stays available as a tooltip.
                            const validity = validityState(tariff, today)
                            const validFrom = formatShortDate(tariff.valid_from, settings)
                            const validTo = tariff.valid_to ? formatShortDate(tariff.valid_to, settings) : null
                            const validityLabel = validity === 'scheduled'
                                ? t('pages.tariffs.validity.starts', { date: validFrom })
                                : validity === 'expired'
                                    ? t('pages.tariffs.validity.ended', { date: validTo })
                                    : validTo
                                        ? t('pages.tariffs.validity.until', { date: validTo })
                                        : t('pages.tariffs.validity.since', { date: validFrom })
                            const validityTooltip = `${validFrom} - ${validTo ?? t('pages.tariffs.openEnded')}`

                            return (
                                <article key={tariff.id} className="tariff-card">
                                    <div className="tariff-card-header">
                                        <div className="tariff-card-title">
                                            <div className="tariff-card-heading">
                                                <strong>{tariff.name}</strong>
                                                <div className="tariff-name-badges">
                                                    <span className="badge badge-info">
                                                        {t(`pages.tariffs.billingModes.${tariff.billing_mode}` as Parameters<typeof t>[0], { defaultValue: tariff.billing_mode })}
                                                    </span>
                                                    {tariff.energy_type && (
                                                        <span className="badge badge-success">
                                                            {t(`pages.tariffs.energyTypes.${tariff.energy_type}` as Parameters<typeof t>[0])}
                                                        </span>
                                                    )}
                                                    <span className={VALIDITY_BADGE_CLASS[validity]} title={validityTooltip}>
                                                        {validityLabel}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>

                                        <div className="tariff-card-actions">
                                            <button className="button button-primary button-compact" type="button" onClick={() => onEditTariff(tariff)}>
                                                <FontAwesomeIcon icon={faPen} fixedWidth />
                                                {t('common.edit')}
                                            </button>
                                            <button
                                                className="button button-danger button-compact"
                                                type="button"
                                                disabled={deleteTariffDisabled}
                                                onClick={() => onDeleteTariff(tariff)}
                                            >
                                                <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                {t('common.delete')}
                                            </button>
                                            <button
                                                className="button button-secondary button-compact"
                                                type="button"
                                                aria-expanded={isExpanded}
                                                onClick={() => toggleExpanded(tariff.id)}
                                            >
                                                <FontAwesomeIcon icon={isExpanded ? faChevronUp : faChevronDown} fixedWidth />
                                                {isExpanded ? t('common.hideDetails') : t('common.showDetails')}
                                            </button>
                                        </div>
                                    </div>

                                    <div className="tariff-card-summary-row">
                                        {!usesPeriods && (
                                            <div className="tariff-detail-card">
                                                <span className="tariff-detail-label">{t('pages.tariffs.col.pricing')}</span>
                                                <span className="tariff-detail-value" title={pricingTooltip}>{pricingLabel}</span>
                                            </div>
                                        )}
                                        {usesPeriods && (
                                            <span className="badge badge-neutral">
                                                {t('pages.tariffs.periodCountSummary', { count: tariffPeriods.length })}
                                            </span>
                                        )}
                                    </div>

                                    {isExpanded && (
                                        <>
                                            {/* Validity moved to a badge on the header; notes are all
                                                that is left here, so the block is skipped when empty. */}
                                            {notes && (
                                                <div className="tariff-card-details">
                                                    <div className="tariff-detail-card tariff-detail-card-wide">
                                                        <span className="tariff-detail-label">{t('pages.tariffs.form.notes')}</span>
                                                        <span className="tariff-detail-value">{notes}</span>
                                                    </div>
                                                </div>
                                            )}

                                            {usesPeriods && (
                                                <div className="tariff-period-section">
                                                    <div className="tariff-period-section-header">
                                                        <div className="tariff-period-section-title-row">
                                                            <h4>{t('pages.tariffs.tariffPeriods')}</h4>
                                                            {tariffPeriods.length > 0 && (
                                                                <span className="badge badge-neutral">{tariffPeriods.length}</span>
                                                            )}
                                                        </div>
                                                        <button
                                                            className="button button-secondary button-compact"
                                                            type="button"
                                                            onClick={() => onOpenCreatePeriodModal(tariff.id)}
                                                        >
                                                            <FontAwesomeIcon icon={faPlus} fixedWidth />
                                                            {t('pages.tariffs.addPeriod')}
                                                        </button>
                                                    </div>

                                                    {tariffPeriods.length === 0 ? (
                                                        <p className="muted tariff-period-empty">{t('pages.tariffs.noPeriods')}</p>
                                                    ) : (
                                                        <div className="tariff-period-list">
                                                            {tariffPeriods.map((period) => (
                                                                <div key={period.id} className="tariff-period-row">
                                                                    <div className="tariff-period-main">
                                                                        <div className="tariff-period-line">
                                                                            <span className="badge badge-neutral">
                                                                                {t(`pages.tariffs.periodTypes.${period.period_type}` as Parameters<typeof t>[0], { defaultValue: period.period_type })}
                                                                            </span>
                                                                            <strong>CHF {period.price_chf_per_kwh}/kWh</strong>
                                                                        </div>
                                                                        <div className="muted tariff-period-meta">
                                                                            {period.period_type === 'flat'
                                                                                ? `${t('pages.tariffs.allDay')} · ${t('pages.tariffs.allWeekdays')}`
                                                                                : `${period.time_from || '--'} - ${period.time_to || '--'} · ${period.weekdays || t('pages.tariffs.allWeekdays')}`}
                                                                        </div>
                                                                    </div>

                                                                    <div className="tariff-period-actions">
                                                                        <button className="button button-secondary button-compact" type="button" onClick={() => onEditPeriod(period)}>
                                                                            <FontAwesomeIcon icon={faPen} fixedWidth />
                                                                            {t('common.edit')}
                                                                        </button>
                                                                        <button
                                                                            className="button button-danger button-compact"
                                                                            type="button"
                                                                            disabled={deletePeriodDisabled}
                                                                            onClick={() => onDeletePeriod(period)}
                                                                        >
                                                                            <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                                            {t('common.delete')}
                                                                        </button>
                                                                    </div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </>
                                    )}
                                </article>
                            )
                        })}
                    </div>
                </section>
            ))}
        </div>
    )
}
