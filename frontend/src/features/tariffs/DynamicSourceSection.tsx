import type { AppSettings, DynamicTariffSource } from '../../types/api'
import { DynamicPriceHistoryPanel, type TariffValidityContext } from './DynamicPriceHistoryModal'
import { DynamicSourceSummary } from './DynamicSourceSummary'
import { useElapsedPriceGaps } from './useElapsedPriceGaps'

/**
 * A dynamic tariff's source in the detail pane: its facts, whether prices are
 * missing, and the price chart — all visible without opening anything.
 */
export function DynamicSourceSection({ source, tariff, settings, canOperate }: {
    source: DynamicTariffSource
    tariff: TariffValidityContext
    settings: AppSettings
    canOperate: boolean
}) {
    const missing = useElapsedPriceGaps(source, tariff)
    return (
        <>
            <DynamicSourceSummary source={source} settings={settings} canOperate={canOperate} missing={missing} />
            <DynamicPriceHistoryPanel source={source} tariff={tariff} compact />
        </>
    )
}
