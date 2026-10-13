import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { useTranslation } from 'react-i18next'
import type { MeteringPoint } from '../../types/api'
import { METER_TYPE_ICON } from './MeteringPointRow'

const LEGEND_ORDER: MeteringPoint['meter_type'][] = ['consumption', 'production', 'bidirectional']

/** Names the type icons in front of the meter IDs; lists only the types the page shows. */
export function MeteringPointTypeLegend({ meteringPoints }: { meteringPoints: MeteringPoint[] }) {
  const { t } = useTranslation()
  const present = LEGEND_ORDER.filter((type) => meteringPoints.some((point) => point.meter_type === type))
  if (present.length === 0) return null
  return (
    <ul className="metering-type-legend muted" aria-label={t('pages.meteringPoints.typeLegend')}>
      {present.map((type) => (
        <li key={type}>
          <span className="metering-point-type" aria-hidden="true">
            <FontAwesomeIcon icon={METER_TYPE_ICON[type]} fixedWidth />
          </span>
          {t(`pages.meteringPoints.meterTypes.${type}`)}
        </li>
      ))}
    </ul>
  )
}
