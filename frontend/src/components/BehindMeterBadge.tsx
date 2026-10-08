import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCircleInfo } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import type { behindMeterHintKey } from '../lib/supplementary'

type BehindMeterBadgeProps = {
    /**
     * i18n key for the explanatory hint shown as a tooltip (and accessible
     * label) next to the badge. Omit for the plain metering-point-list badge,
     * which needs no extra explanation beyond its own label.
     */
    hintKey?: ReturnType<typeof behindMeterHintKey>
    className?: string
}

/**
 * Shared badge for a metering point (or the participant holding one) that has
 * generation behind the meter (surplus / net metering) — see
 * docs/specs/2026-09-behind-the-meter-generation.md §7.5.
 */
export function BehindMeterBadge({ hintKey, className = 'badge badge-tag' }: BehindMeterBadgeProps) {
    const { t } = useTranslation()
    const label = t('behindMeter.badge')

    if (!hintKey) {
        return <span className={className}>{label}</span>
    }

    const hint = t(hintKey)
    return (
        <span className={className} title={hint} aria-label={`${label}: ${hint}`}>
            <FontAwesomeIcon icon={faCircleInfo} fixedWidth />
            {label}
        </span>
    )
}
