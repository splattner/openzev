import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { formatShortDate, useAppSettings } from '../../../lib/appSettings'
import type { TariffProgression } from '../../../types/api'
import { MONTH_KEYS, WEEKDAY_KEYS } from '../recurrence'
import { ProgressionComposition } from './ProgressionComposition'
import { ProgressionFixedFees } from './ProgressionFixedFees'
import { TariffProgressionChart } from './TariffProgressionChart'
import { buildChartData, lineLabel, progressionIssues, type PriceBasis } from './progression'

type Props = {
    progression: TariffProgression
    basis: PriceBasis
    day: string
    lineKey: string | null
    onPickDay: (day: string) => void
    onPickLine: (lineKey: string) => void
}

/** The chart, what is missing from it, the day's composition and the fixed fees. */
export function TariffProgressionView({ progression, basis, day, lineKey, onPickDay, onPickLine }: Props) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()

    const lineNames = useMemo(() => {
        const monthNames = MONTH_KEYS.map((key) => t(`pages.tariffs.monthsShort.${key}` as Parameters<typeof t>[0]))
        const dayNames = WEEKDAY_KEYS.map((key) => t(`pages.tariffs.weekdaysShort.${key}` as Parameters<typeof t>[0]))
        return Object.fromEntries(progression.lines.map((line) => [
            line.key, lineLabel(line.rules, t as Parameters<typeof lineLabel>[1], dayNames, monthNames),
        ]))
    }, [progression.lines, t])
    const data = useMemo(() => buildChartData(progression, basis), [progression, basis])
    const issues = useMemo(() => progressionIssues(progression), [progression])

    return (
        <>
            {progression.intervals.length > 0 && (
                <section className="card" aria-labelledby="tariff-progression-chart-title">
                    <div className="card-header">
                        <h2 id="tariff-progression-chart-title">{t('pages.tariffs.progression.chartTitle')}</h2>
                        <span className="muted">{t('pages.tariffs.chfPerKwh')}</span>
                    </div>
                    <TariffProgressionChart
                        progression={progression}
                        data={data}
                        lineNames={lineNames}
                        settings={settings}
                        day={day}
                        onPickDay={onPickDay}
                    />
                    {issues.length > 0 && (
                        <ul className="tariff-progression-notices warning-banner">
                            {issues.map((issue) => (
                                <li key={`${issue.kind}|${issue.subject}|${issue.from}`}>
                                    {t(`pages.tariffs.progression.issues.${issue.kind}`, {
                                        subject: issue.kind === 'missing'
                                            ? t(`pages.tariffs.categories.${issue.subject}` as Parameters<typeof t>[0])
                                            : issue.subject,
                                        from: formatShortDate(issue.from, settings),
                                        to: formatShortDate(issue.to, settings),
                                    })}
                                </li>
                            ))}
                        </ul>
                    )}
                </section>
            )}

            {progression.intervals.length > 0 && (
                <ProgressionComposition
                    progression={progression}
                    day={day}
                    lineKey={lineKey}
                    lineNames={lineNames}
                    basis={basis}
                    settings={settings}
                    onPickLine={onPickLine}
                />
            )}

            <ProgressionFixedFees fees={progression.fixed_fees} day={day} basis={basis} settings={settings} />
        </>
    )
}
