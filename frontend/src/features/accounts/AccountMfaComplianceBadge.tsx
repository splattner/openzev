import { useTranslation } from 'react-i18next'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import type { MfaCompliance } from '../../types/api'
import { IssueText } from '../../components/IssueText'

/** How an account stands against the MFA policy — shown next to its second-factor badges when the policy names its role. */
export function AccountMfaComplianceBadge({ compliance }: { compliance: MfaCompliance | null }) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()

    if (compliance === null || compliance.status === 'compliant') return null

    const deadline = formatShortDate(compliance.deadline, settings)
    return (
        <IssueText tone={compliance.status === 'overdue' ? 'error' : 'warning'}>
            {compliance.status === 'overdue'
                ? t('pages.accounts.mfa.complianceOverdue')
                : t('pages.accounts.mfa.complianceGrace', { date: deadline })}
        </IssueText>
    )
}
