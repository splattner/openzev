import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCircleInfo } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { formatPercent } from '../../lib/numbers'
import { grossRate, withheldReasonKey } from '../../lib/supplementary'
import type { GrossEnergy } from '../../types/api'

/**
 * The self-sufficiency cell of a net-metered participant. The meter cannot give the rate, so it is a
 * dash (with the reason when there is one) unless the participant's own system reported enough
 * data, in which case the figure carries an info marker saying where it comes from.
 */
export function NetMeteredRate({ gross }: { gross: GrossEnergy | null | undefined }) {
    const { t } = useTranslation()
    const rate = grossRate(gross)
    if (rate === null) {
        const reasonKey = withheldReasonKey(gross)
        return <span title={reasonKey ? t(reasonKey) : undefined}>—</span>
    }
    return (
        <span title={t('supplementary.rateHint')} aria-label={`${formatPercent(rate)}: ${t('supplementary.rateHint')}`}>
            <FontAwesomeIcon icon={faCircleInfo} fixedWidth /> {formatPercent(rate)}
        </span>
    )
}
