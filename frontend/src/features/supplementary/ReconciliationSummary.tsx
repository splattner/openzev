import { useTranslation } from 'react-i18next'
import { IssueText } from '../../components/IssueText'
import { formatPercent } from '../../lib/numbers'
import type { SupplementaryReconciliation } from '../../types/api'

/**
 * How the source compares with the official meter. Diagnostic only: it changes nothing,
 * and the meter stays authoritative. Says so when there is nothing to compare yet.
 */
export function ReconciliationSummary({ reconciliation }: { reconciliation: SupplementaryReconciliation | undefined }) {
    const { t } = useTranslation()
    const state = reconciliation?.state
    if (!state) return <span className="muted">{t('supplementary.reconciliation.never')}</span>

    const shift = reconciliation?.best_shift_intervals ?? 0
    // Text, not a pill (UI patterns §10.1): a match is plain, a difference is the one thing worth colouring.
    const label = t(`supplementary.reconciliation.state.${state}`)
    return (
        <span className="source-reconciliation">
            {state === 'warn' ? <IssueText tone="warning">{label}</IssueText> : <span className={state === 'insufficient' ? 'muted' : undefined}>{label}</span>}
            {state !== 'insufficient' && (
                <small className="muted">
                    {t('supplementary.reconciliation.deviation', {
                        exported: formatPercent(reconciliation?.export_deviation_pct ?? 0),
                        imported: formatPercent(reconciliation?.import_deviation_pct ?? 0),
                        days: reconciliation?.days_compared ?? 0,
                    })}
                </small>
            )}
            {state === 'warn' && shift !== 0 && (
                <small className="muted">{t('supplementary.reconciliation.shifted', { count: Math.abs(shift) })}</small>
            )}
            {state === 'insufficient' && <small className="muted">{t('supplementary.reconciliation.insufficientHint')}</small>}
        </span>
    )
}
