import { useTranslation } from 'react-i18next'
import { MeteringDataLink } from './MeteringDataLink'

/**
 * What the grid operator's meter has recorded for a metering point: the readings billing is based on. Kept
 * apart from the energy data of the participant's own system, which is only shown and never billed, so the
 * link to the readings is not taken for a link to those sources' data.
 */
export function MeterDataBand({ meteringPointId }: { meteringPointId: string }) {
    const { t } = useTranslation()
    return (
        <div className="meter-data-band">
            <div className="card-title-block">
                <strong>{t('pages.myMeteringPoints.meterData.title')}</strong>
                <small className="muted">{t('pages.myMeteringPoints.meterData.hint')}</small>
            </div>
            <MeteringDataLink meteringPointId={meteringPointId} />
        </div>
    )
}
