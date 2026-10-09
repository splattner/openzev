import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCircleInfo } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { dashboardKwhStat } from '../../lib/dashboardFormatting'
import { hasOwnSystemData } from '../../lib/supplementary'
import type { GrossEnergy } from '../../types/api'

/**
 * The participant's own-system kWh figure shown under the meter value of a net-metered participant,
 * so both pictures are visible side by side. Nothing when the own system reported too little data
 * for the period (the same rule that withholds the rate): a partial sum next to a full-period
 * meter value would mislead.
 */
export function OwnSystemKwh({ gross, kind }: { gross: GrossEnergy | null | undefined; kind: 'consumption' | 'production' }) {
    const { t } = useTranslation()
    if (!gross || !hasOwnSystemData(gross)) return null
    const value = dashboardKwhStat(kind === 'consumption' ? gross.consumption_kwh : gross.production_kwh)
    const text = t('supplementary.ownSystemValue', { value })
    return (
        <small className="muted own-system-kwh" title={t('supplementary.rateHint')} aria-label={`${text}: ${t('supplementary.rateHint')}`}>
            <FontAwesomeIcon icon={faCircleInfo} fixedWidth /> {text}
        </small>
    )
}
