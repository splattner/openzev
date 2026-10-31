import { useTranslation } from 'react-i18next'
import { LIVE_STATE_BADGE_CLASS } from '../../lib/supplementary'
import type { LiveState } from '../../types/api'

/** The freshness of a live source as a badge: live, not recent, or no data yet. */
export function LiveStateBadge({ state }: { state: LiveState }) {
    const { t } = useTranslation()
    return <span className={LIVE_STATE_BADGE_CLASS[state]}>{t(`live.state.${state}`)}</span>
}
