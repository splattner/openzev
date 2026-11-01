import { useTranslation } from 'react-i18next'
import { IssueText } from '../../components/IssueText'
import type { LiveState } from '../../types/api'

/**
 * The freshness of a live source as text (UI patterns §10.1): a value that is current is plain, a source
 * that has gone quiet is a problem to look at, and one that has not reported yet is a muted note.
 */
export function LiveStateBadge({ state }: { state: LiveState }) {
    const { t } = useTranslation()
    const label = t(`live.state.${state}`)
    if (state === 'stale') return <IssueText tone="warning">{label}</IssueText>
    return <span className={state === 'never' ? 'muted' : undefined}>{label}</span>
}
