import { useTranslation } from 'react-i18next'
import { IssueText } from '../../components/IssueText'
import type { LiveState } from '../../types/api'

interface Props {
    state: LiveState
    /** Opens the live data of the point (managers of a ZEV-operated meter); without it the chip is plain text. */
    onClick?: () => void
}

/**
 * A quiet marker on a metering point that has a live source (UI patterns §10.1): a tag while the values
 * come in, an issue while they are not recent. Never a coloured pill for the normal case.
 */
export function LiveStateChip({ state, onClick }: Props) {
    const { t } = useTranslation()
    const label = t(`supplementary.live.chip.${state}`)
    if (state === 'stale') {
        return <IssueText tone="warning" onClick={onClick} title={t(onClick ? 'supplementary.live.chipOpenHint' : 'supplementary.live.chipHint')}>{label}</IssueText>
    }
    if (!onClick) return <span className="badge badge-tag" title={t('supplementary.live.chipHint')}>{label}</span>
    return (
        <button type="button" className="badge badge-tag badge-button" onClick={onClick} aria-haspopup="dialog" title={t('supplementary.live.chipOpenHint')}>
            {label}
        </button>
    )
}
