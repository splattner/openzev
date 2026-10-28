import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faArrowRightFromBracket, faPlug, faSolarPanel } from '@fortawesome/free-solid-svg-icons'
import type { IconDefinition } from '@fortawesome/fontawesome-svg-core'
import { useTranslation } from 'react-i18next'

// Where the energy comes from or goes to: the grid, the community's own
// production, or out to the grid.
const ICONS: Record<string, IconDefinition> = {
    grid: faPlug,
    local: faSolarPanel,
    feed_in: faArrowRightFromBracket,
}

/** The energy type of a tariff as an icon, named for assistive technology and as a tooltip. */
export function TariffTypeIcon({ type }: { type?: string | null }) {
    const { t } = useTranslation()
    const icon = type ? ICONS[type] : undefined
    if (!type || !icon) return null
    const label = t(`pages.tariffs.energyTypes.${type}` as Parameters<typeof t>[0])
    return (
        <span className="tariff-type-icon" role="img" aria-label={label} title={label}>
            <FontAwesomeIcon icon={icon} fixedWidth />
        </span>
    )
}
