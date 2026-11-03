import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../../lib/appSettings'
import { formatNumber } from '../../../lib/numbers'
import type { AppSettings, TariffProgression } from '../../../types/api'
import { compositionOn, valueOf, type PriceBasis } from './progression'

type Props = {
    progression: TariffProgression
    day: string
    lineKey: string | null
    lineNames: Record<string, string>
    basis: PriceBasis
    settings: AppSettings
    onPickLine: (lineKey: string) => void
}

/** CHF per kWh at the precision the API carries, never fewer than three decimals. */
function price(value: string): string {
    return formatNumber(Number(value), { minDecimals: 3, maxDecimals: 5 })
}

/**
 * What one kWh costs on a day, per category and per tariff. It is also the
 * accessible equivalent of the chart: the same numbers as text.
 */
export function ProgressionComposition({ progression, day, lineKey, lineNames, basis, settings, onPickLine }: Props) {
    const { t } = useTranslation()
    const composition = lineKey ? compositionOn(progression, day, lineKey) : null
    const lines = progression.intervals.find((interval) => interval.from <= day && day <= interval.to)?.slots ?? []

    return (
        <section className="tariff-progression-composition" aria-labelledby="tariff-progression-composition-title">
            <div className="tariff-progression-composition-header">
                <h2 id="tariff-progression-composition-title">
                    {t('pages.tariffs.progression.composition.title', { date: formatShortDate(day, settings) })}
                </h2>
                {lines.length > 1 && (
                    <label className="tariff-progression-line-picker">
                        <span>{t('pages.tariffs.progression.composition.line')}</span>
                        <select value={lineKey ?? ''} onChange={(event) => onPickLine(event.target.value)}>
                            {lines.map((slot) => (
                                <option key={slot.line} value={slot.line}>{lineNames[slot.line] ?? slot.line}</option>
                            ))}
                        </select>
                    </label>
                )}
            </div>

            {!composition ? (
                <p className="muted">{t('pages.tariffs.progression.composition.none')}</p>
            ) : (
                <div className="data-table">
                    <table>
                        <caption className="visually-hidden">
                            {t('pages.tariffs.progression.composition.caption', { line: lineNames[composition.slot.line] ?? '' })}
                        </caption>
                        <thead>
                            <tr>
                                <th scope="col">{t('pages.tariffs.progression.composition.charge')}</th>
                                <th scope="col" className="numeric">{t('pages.tariffs.chfPerKwh')}</th>
                            </tr>
                        </thead>
                        {composition.slot.categories.map((category) => (
                            <tbody key={category.category}>
                                <tr className="tariff-progression-subtotal">
                                    <th scope="rowgroup">{t(`pages.tariffs.categories.${category.category}` as Parameters<typeof t>[0])}</th>
                                    <td className="numeric">{price(valueOf(category, basis))}</td>
                                </tr>
                                {category.components.map((component) => (
                                    <tr key={component.tariff_id}>
                                        <td className="tariff-progression-component">
                                            {component.name}
                                            {component.percentage !== null && component.base_net !== null && (
                                                <span className="muted">
                                                    {t('pages.tariffs.progression.composition.percentageOf', {
                                                        percentage: formatNumber(Number(component.percentage), { maxDecimals: 2 }),
                                                        base: price(component.base_net),
                                                    })}
                                                </span>
                                            )}
                                        </td>
                                        <td className="numeric">{price(valueOf(component, basis))}</td>
                                    </tr>
                                ))}
                            </tbody>
                        ))}
                        <tfoot>
                            <tr>
                                <th scope="row">{t('pages.tariffs.progression.composition.total')}</th>
                                <td className="numeric">{price(valueOf(composition.slot, basis))}</td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            )}
        </section>
    )
}
