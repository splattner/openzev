import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faChartLine } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

/** Opens the metering chart on one meter: the participant's own readings, within the time they hold it. */
export function MeteringDataLink({ meteringPointId }: { meteringPointId: string }) {
    const { t } = useTranslation()
    return (
        <Link
            className="button button-secondary button-compact"
            style={{ textDecoration: 'none' }}
            to={`/metering/chart?metering_point=${meteringPointId}`}
        >
            <FontAwesomeIcon icon={faChartLine} fixedWidth />
            {t('pages.myMeteringPoints.viewData')}
        </Link>
    )
}
