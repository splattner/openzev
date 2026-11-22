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

/** What the overview's energy-type icons mean; only the types in view are named. */
export function TariffTypeLegend({ types }: { types: ReadonlyArray<string | null | undefined> }) {
    const { t } = useTranslation()
    const shown = Object.keys(ICONS).filter((type) => types.includes(type))
    if (shown.length === 0) return null
    return (
        <p className="tariff-type-legend muted">
            {shown.map((type) => (
                <span key={type}>
                    <FontAwesomeIcon icon={ICONS[type]} fixedWidth aria-hidden="true" />
                    {t(`pages.tariffs.energyTypes.${type}` as Parameters<typeof t>[0])}
                </span>
            ))}
        </p>
    )
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
