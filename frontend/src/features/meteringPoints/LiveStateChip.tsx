import { useTranslation } from 'react-i18next'
import { LIVE_STATE_BADGE_CLASS } from '../../lib/supplementary'
import type { LiveState } from '../../types/api'

interface Props {
    state: LiveState
    /** Opens the live data of the point (managers of a ZEV-operated meter); without it the chip is plain text. */
    onClick?: () => void
}

/** A quiet marker on a metering point that has a live source: live, not recent or no data yet. */
export function LiveStateChip({ state, onClick }: Props) {
    const { t } = useTranslation()
    const label = t(`supplementary.live.chip.${state}`)
    if (!onClick) return <span className={LIVE_STATE_BADGE_CLASS[state]} title={t('supplementary.live.chipHint')}>{label}</span>
    return (
        <button type="button" className={`${LIVE_STATE_BADGE_CLASS[state]} badge-button`} onClick={onClick} aria-haspopup="dialog" title={t('supplementary.live.chipOpenHint')}>
            {label}
        </button>
    )
}
