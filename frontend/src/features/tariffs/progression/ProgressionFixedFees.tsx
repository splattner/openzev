import { SortableHeader, useTableSorting } from '../../../components/tableSorting'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../../lib/appSettings'
import { formatChfAmount } from '../../../lib/numbers'
import type { AppSettings, TariffProgressionFixedFee } from '../../../types/api'
import { feeVersionOn, groupFees, valueOf, type PriceBasis } from './progression'

type Props = {
    fees: TariffProgressionFixedFee[]
    day: string
    basis: PriceBasis
    settings: AppSettings
}

/**
 * Monthly and yearly fees, each in its own unit and never added to the
 * per-kWh price or to each other. A shared fee is what the community pays.
 */
export function ProgressionFixedFees({ fees, day, basis, settings }: Props) {
    const { t } = useTranslation()
    const sorting = useTableSorting(fees, {
        name: fee => fee.name,
        scope: fee => fee.scope,
        since: fee => feeVersionOn(fee, day).valid_from,
        amount: fee => Number(valueOf({ net: feeVersionOn(fee, day).amount_net, gross: feeVersionOn(fee, day).amount_gross }, basis)),
    })
    if (fees.length === 0) return null
    const groups = groupFees(sorting.rows)

    return (
        <section className="card tariff-progression-fees" aria-labelledby="tariff-progression-fees-title">
            <div className="card-header">
                <h2 id="tariff-progression-fees-title">{t('pages.tariffs.progression.fees.title')}</h2>
            </div>
            <p className="muted">{t('pages.tariffs.progression.fees.intro')}</p>
            {(['month', 'year'] as const).map((unit) => groups[unit].length > 0 && (
                <div className="table-scroll" key={unit}>
                    <table>
                        <caption>{t(`pages.tariffs.progression.fees.${unit}`)}</caption>
                        <thead>
                            <tr>
                                <SortableHeader {...sorting.header('name', groups[unit].length)} scope="col">{t('pages.tariffs.progression.fees.name')}</SortableHeader>
                                <SortableHeader {...sorting.header('scope', groups[unit].length)} scope="col">{t('pages.tariffs.progression.fees.scope')}</SortableHeader>
                                <SortableHeader {...sorting.header('since', groups[unit].length)} scope="col">{t('pages.tariffs.progression.fees.since')}</SortableHeader>
                                <SortableHeader {...sorting.header('amount', groups[unit].length)} scope="col" className="numeric">{t(`pages.tariffs.progression.fees.amount.${unit}`)}</SortableHeader>
                            </tr>
                        </thead>
                        <tbody>
                            {groups[unit].map((fee) => {
                                const version = feeVersionOn(fee, day)
                                return (
                                    <tr key={`${fee.name}-${fee.billing_mode}`}>
                                        <td>
                                            {fee.name}
                                            <span className="muted">{t(`pages.tariffs.categories.${fee.category}` as Parameters<typeof t>[0])}</span>
                                        </td>
                                        <td>
                                            {t(`pages.tariffs.progression.fees.scopes.${fee.scope}`)}
                                            {fee.split_key && (
                                                <span className="muted">{t(`pages.tariffs.progression.fees.split.${fee.split_key}`)}</span>
                                            )}
                                        </td>
                                        <td>{formatShortDate(version.valid_from, settings)}</td>
                                        <td className="numeric">{formatChfAmount(Number(valueOf({ net: version.amount_net, gross: version.amount_gross }, basis)))}</td>
                                    </tr>
                                )
                            })}
                        </tbody>
                    </table>
                </div>
            ))}
        </section>
    )
}
