import { useTranslation } from 'react-i18next'
import { STATUS_BADGE_CLASS, statusTone } from '../../lib/supplementary'
import type { SupplementaryStatus } from '../../types/api'

/** The state of an energy data source as a badge. A disabled source reads as "disconnected". */
export function SourceStatusBadge({ status }: { status: SupplementaryStatus }) {
    const { t } = useTranslation()
    return <span className={STATUS_BADGE_CLASS[statusTone(status)]}>{t(`supplementary.status.${status}`)}</span>
}
