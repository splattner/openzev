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
    if (fees.length === 0) return null
    const groups = groupFees(fees)

    return (
        <section className="tariff-progression-fees" aria-labelledby="tariff-progression-fees-title">
            <h2 id="tariff-progression-fees-title">{t('pages.tariffs.progression.fees.title')}</h2>
            <p className="muted">{t('pages.tariffs.progression.fees.intro')}</p>
            {(['month', 'year'] as const).map((unit) => groups[unit].length > 0 && (
                <div className="data-table" key={unit}>
                    <table>
                        <caption>{t(`pages.tariffs.progression.fees.${unit}`)}</caption>
                        <thead>
                            <tr>
                                <th scope="col">{t('pages.tariffs.progression.fees.name')}</th>
                                <th scope="col">{t('pages.tariffs.progression.fees.scope')}</th>
                                <th scope="col">{t('pages.tariffs.progression.fees.since')}</th>
                                <th scope="col" className="numeric">{t(`pages.tariffs.progression.fees.amount.${unit}`)}</th>
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
