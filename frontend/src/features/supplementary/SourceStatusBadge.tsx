import { useTranslation } from 'react-i18next'
import { Badge } from '../../components/Badge'
import type { SupplementaryStatus } from '../../types/api'

/** The state of an energy data source as a badge. A disabled source reads as "disconnected". */
export function SourceStatusBadge({ status }: { status: SupplementaryStatus }) {
    const { t } = useTranslation()
    return <Badge status={status} domain="supplementary">{t(`supplementary.status.${status}`)}</Badge>
}
