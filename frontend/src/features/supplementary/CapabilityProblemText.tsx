import { useTranslation } from 'react-i18next'
import { IssueText } from '../../components/IssueText'
import type { CapabilityProblem } from '../../lib/supplementary'

/** What is wrong with a capability, as text (UI patterns §10.1): a note is muted, a problem is `IssueText`; nothing while it works. */
export function CapabilityProblemText({ problem }: { problem: CapabilityProblem | null }) {
    const { t } = useTranslation()
    if (!problem) return null
    if (problem.tone === 'muted') return <span className="muted">{t(problem.labelKey)}</span>
    return <IssueText tone={problem.tone}>{t(problem.labelKey)}</IssueText>
}
