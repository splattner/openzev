import { useId, useState } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faFileImport } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { useCommunityAccess } from '../../lib/communityAccess'
import { FormModal } from '../../components/FormModal'
import type { MeteringPointDataQuality } from '../../types/api'

type MeteringGapsModalProps = {
    point: MeteringPointDataQuality | null
    period: { from: string; to: string }
    onClose: () => void
    onGoToImports: () => void
}

/**
 * The missing date ranges of one metering point, opened from a row of the
 * quality table. It has no list of its own beside it, so it is a dialog and
 * keeps the modal behaviour the drawer had (SPEC-2026-10-ui-patterns §5 rule C).
 */
export function MeteringGapsModal({ point, period, onClose, onGoToImports }: MeteringGapsModalProps) {
    const { t } = useTranslation()
    return (
        <FormModal isOpen={Boolean(point)} title={t('meteringDataQuality.gaps')} size="xs" onClose={onClose}>
            {point && <MeteringGaps key={point.id} point={point} period={period} onGoToImports={onGoToImports} />}
        </FormModal>
    )
}

function MeteringGaps({ point, period, onGoToImports }: Omit<MeteringGapsModalProps, 'point' | 'onClose'> & { point: MeteringPointDataQuality }) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { canWriteSelectedCommunity } = useCommunityAccess()
    const [showAll, setShowAll] = useState(false)
    const listId = useId()
    const visibleGaps = showAll ? point.gaps : point.gaps.slice(0, 3)

    return (
        <div className="page-stack metering-gaps">
            <div>
                <strong className="metering-gaps-meter">{point.meter_id}</strong>
                {point.participant_name && <p>{point.participant_name}</p>}
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
                {point.gaps.length > 3 && (
                    <button
                        type="button"
                        className="table-inline-link"
                        aria-expanded={showAll}
                        aria-controls={listId}
                        onClick={() => setShowAll(previous => !previous)}
                    >
                        {showAll
                            ? t('meteringDataQuality.showFewerGaps')
                            : t('meteringDataQuality.moreGaps', { count: point.gaps.length - 3 })}
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
        </div>
    )
}
