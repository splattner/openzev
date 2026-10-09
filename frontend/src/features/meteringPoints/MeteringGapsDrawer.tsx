import { useEffect, useId, useState } from 'react'
import { Drawer } from '@mantine/core'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faFileImport } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { useCommunityAccess } from '../../lib/communityAccess'
import type { MeteringPointDataQuality } from '../../types/api'

export function MeteringGapsDrawer({ point, period, onClose, onGoToImports }: {
    point: MeteringPointDataQuality | null
    period: { from: string; to: string }
    onClose: () => void
    onGoToImports: () => void
}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { canWriteSelectedCommunity } = useCommunityAccess()
    const [showAll, setShowAll] = useState(false)
    // Keep the details visible until Mantine finishes sliding the drawer out.
    const [lastPoint, setLastPoint] = useState<MeteringPointDataQuality | null>(null)
    useEffect(() => { if (point) setLastPoint(point) }, [point])
    const displayPoint = point ?? lastPoint
    const listId = useId()
    const visibleGaps = displayPoint ? (showAll ? displayPoint.gaps : displayPoint.gaps.slice(0, 3)) : []
    useEffect(() => { setShowAll(false) }, [point?.id])

    return (
        <Drawer
            opened={Boolean(point)}
            onClose={onClose}
            position="right"
            size="min(100vw, 32rem)"
            title={t('meteringDataQuality.gaps')}
            closeButtonProps={{ 'aria-label': t('common.close') }}
        >
            {displayPoint && <div className="page-stack metering-gaps-drawer">
                <div>
                    <strong className="metering-gaps-meter">{displayPoint.meter_id}</strong>
                    {displayPoint.participant_name && <p>{displayPoint.participant_name}</p>}
                    <p className="muted">
                        {formatShortDate(period.from, settings)} – {formatShortDate(period.to, settings)}
                    </p>
                </div>
                <div>
                    <ul id={listId} className="metering-gaps-list">
                        {visibleGaps.map(gap => (
                            <li key={gap.start_date}>
                                <span>
                                    {formatShortDate(gap.start_date, settings)}
                                    {gap.start_date !== gap.end_date && <> – {formatShortDate(gap.end_date, settings)}</>}
                                </span>
                                {' '}
                                <span className="muted">{t('meteringDataQuality.gapDays', { count: gap.duration_days })}</span>
                            </li>
                        ))}
                    </ul>
                    {displayPoint.gaps.length > 3 && (
                        <button
                            type="button"
                            className="table-inline-link"
                            aria-expanded={showAll}
                            aria-controls={listId}
                            onClick={() => setShowAll(previous => !previous)}
                        >
                            {showAll
                                ? t('meteringDataQuality.showFewerGaps')
                                : t('meteringDataQuality.moreGaps', { count: displayPoint.gaps.length - 3 })}
                        </button>
                    )}
                </div>
                <div>
                    <p className="muted">{t(canWriteSelectedCommunity ? 'meteringDataQuality.importGapsHint' : 'meteringDataQuality.importGapsHintViewer')}</p>
                    <button type="button" className="button button-primary" onClick={onGoToImports}>
                        <FontAwesomeIcon icon={faFileImport} fixedWidth />
                        {t('meteringDataQuality.goToImports')}
                    </button>
                </div>
            </div>}
        </Drawer>
    )
}
