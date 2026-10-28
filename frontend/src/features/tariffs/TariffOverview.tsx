import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Disclosure } from '../../components/Disclosure'
import type { AppSettings, TariffSeries } from '../../types/api'
import { TariffCategorySections } from './TariffCategorySections'
import { seriesKeyOf } from './useTariffDisplay'
import type { TariffOverview as TariffOverviewGroups } from './validity'

type TariffOverviewProps = {
    groups: TariffOverviewGroups
    settings: AppSettings
    /** The series and version shown in the detail pane, so its row can be highlighted. */
    selected: { seriesKey: string, versionId: string } | null
    onOpenDetail: (series: TariffSeries, versionId: string) => void
}

/**
 * What is in force, what is coming, and, folded away, what has ended. The
 * group says what a row's dates mean, so rows carry no status of their own.
 */
export function TariffOverview({ groups, settings, selected, onOpenDetail }: TariffOverviewProps) {
    const { t } = useTranslation()
    const selectedKey = selected ? `${selected.seriesKey}:${selected.versionId}` : null
    const selectedInHistory = groups.history.some((row) => `${seriesKeyOf(row.series)}:${row.version.id}` === selectedKey)
    const [historyOpen, setHistoryOpen] = useState(false)
    const [seenSelection, setSeenSelection] = useState<string | null>(null)

    // A linked or reloaded past version must not sit in a folded group.
    if (selectedKey !== seenSelection) {
        setSeenSelection(selectedKey)
        if (selectedInHistory) setHistoryOpen(true)
    }

    return (
        <div className="tariff-overview">
            <section aria-labelledby="tariff-overview-current">
                <h2 id="tariff-overview-current" className="tariff-overview-title">{t('pages.tariffs.overview.current')}</h2>
                {groups.current.length > 0 ? (
                    <TariffCategorySections rows={groups.current} kind="current" settings={settings} selected={selected} onOpenDetail={onOpenDetail} />
                ) : (
                    <p className="muted">{t('pages.tariffs.overview.nothingCurrent')}</p>
                )}
            </section>

            {groups.upcoming.length > 0 && (
                <section aria-labelledby="tariff-overview-upcoming">
                    <h2 id="tariff-overview-upcoming" className="tariff-overview-title">{t('pages.tariffs.overview.upcoming')}</h2>
                    <TariffCategorySections rows={groups.upcoming} kind="upcoming" settings={settings} selected={selected} onOpenDetail={onOpenDetail} />
                </section>
            )}

            {groups.history.length > 0 && (
                <Disclosure
                    className="tariff-overview-history"
                    open={historyOpen}
                    onOpenChange={setHistoryOpen}
                    summary={<h2 className="tariff-overview-title">{t('pages.tariffs.overview.history')}</h2>}
                >
                    <TariffCategorySections rows={groups.history} kind="history" settings={settings} selected={selected} onOpenDetail={onOpenDetail} />
                </Disclosure>
            )}
        </div>
    )
}
