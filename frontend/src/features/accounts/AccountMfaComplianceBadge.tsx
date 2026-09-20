import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faTriangleExclamation } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import type { MfaCompliance } from '../../types/api'

/** How an account stands against the MFA policy — shown next to its second-factor badges when the policy names its role. */
export function AccountMfaComplianceBadge({ compliance }: { compliance: MfaCompliance | null }) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()

    if (compliance === null || compliance.status === 'compliant') return null

    const deadline = formatShortDate(compliance.deadline, settings)
    return (
        <span className={compliance.status === 'overdue' ? 'badge badge-danger' : 'badge badge-warning'}>
            <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />
            {compliance.status === 'overdue'
                ? t('pages.accounts.mfa.complianceOverdue')
                : t('pages.accounts.mfa.complianceGrace', { date: deadline })}
        </span>
    )
}
