import { useMemo, useState } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faArrowLeft, faArrowRight, faChevronDown } from '@fortawesome/free-solid-svg-icons'
import { Popover } from '@mantine/core'
import { DatePicker } from '@mantine/dates'
import { useTranslation } from 'react-i18next'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import {
    type BillingInterval,
    getCurrentBillingPeriod,
    isBillingAlignedPeriod,
    recentBillingPeriods,
    shiftBillingPeriod,
} from '../lib/billingPeriod'
import { quickRangeToDates, type QuickRangePreset } from '../lib/dateRangePresets'

type PeriodRange = { from: string; to: string }

type PeriodSelectorProps = {
    interval: BillingInterval
    from: string
    to: string
    onChange: (next: PeriodRange) => void
    /** Rendered above the date range, e.g. the ZEV name on the invoices page. */
    title?: string
    /** When false, only whole billing periods are offered — no calendar. */
    allowCustomRange?: boolean
    /** Community start (aligned floor): the previous button stops here. */
    minFrom?: string
}

const QUICK_PRESETS: Array<{ preset: Exclude<QuickRangePreset, 'custom'>; labelKey: string }> = [
    { preset: 'this_month', labelKey: 'thisMonth' },
    { preset: 'last_month', labelKey: 'lastMonth' },
    { preset: 'this_quarter', labelKey: 'thisQuarter' },
    { preset: 'last_quarter', labelKey: 'lastQuarter' },
    { preset: 'this_year', labelKey: 'thisYear' },
    { preset: 'last_year', labelKey: 'lastYear' },
]

/** How many past billing periods to offer when the calendar is disabled. */
const PAST_BILLING_PERIODS = 5

export function PeriodSelector({
    interval,
    from,
    to,
    onChange,
    title,
    allowCustomRange = true,
    minFrom,
}: PeriodSelectorProps) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()

    const [opened, setOpened] = useState(false)
    const [draft, setDraft] = useState<[string | null, string | null]>([from || null, to || null])

    const formatDate = (iso: string) => formatShortDate(iso, settings)

    // Prev stops at the community's earliest billable period — never a pre-start range.
    const aligned = isBillingAlignedPeriod(from, to, interval)
    const previous = from ? shiftBillingPeriod(from, interval, -1) : null
    const canGoPrevious = !!previous && aligned && (!minFrom || previous.from >= minFrom)
    const canGoNext = !!from && aligned
    const canNavigate = canGoNext

    const presets = useMemo<Array<{ id: string; label: string; hint?: string; range: PeriodRange }>>(() => {
        const current = getCurrentBillingPeriod(interval)

        if (!allowCustomRange) {
            // Invoices bill whole periods, so offer recent ones instead of a
            // calendar — none predating the community's first period.
            return recentBillingPeriods(interval, PAST_BILLING_PERIODS, minFrom).map((range, index) => ({
                id: range.from,
                label: `${formatShortDate(range.from, settings)} → ${formatShortDate(range.to, settings)}`,
                hint: index === 0 ? t('common.periodSelector.currentPeriod') : undefined,
                range,
            }))
        }

        return [
            { id: 'current', label: t('common.periodSelector.currentPeriod'), range: current },
            ...QUICK_PRESETS.map(({ preset, labelKey }) => ({
                id: preset,
                label: t(`common.periodSelector.${labelKey}`),
                range: quickRangeToDates(preset),
            })),
        ]
    }, [interval, allowCustomRange, minFrom, t, settings])

    function apply(next: PeriodRange) {
        onChange(next)
        setOpened(false)
    }

    function openPopover() {
        setDraft([from || null, to || null])
        setOpened((previous) => !previous)
    }

    return (
        <div className="period-selector">
            <button
                className="button button-secondary"
                type="button"
                onClick={() => previous && onChange(previous)}
                disabled={!canGoPrevious}
            >
                <FontAwesomeIcon icon={faArrowLeft} fixedWidth />
                {t('pages.invoices.prevPeriod')}
            </button>

            <Popover
                opened={opened}
                onChange={setOpened}
                position="bottom"
                withinPortal
                trapFocus
                returnFocus
                shadow="md"
            >
                <Popover.Target>
                    <button
                        className="period-selector-trigger"
                        type="button"
                        onClick={openPopover}
                        disabled={!from}
                    >
                        <span className="period-selector-text">
                            {title && <span className="period-selector-title">{title}</span>}
                            <span className="period-selector-range">
                                {from && to ? `${formatDate(from)} → ${formatDate(to)}` : '—'}
                            </span>
                            {aligned ? (
                                <span className="muted period-selector-interval">
                                    {t('pages.invoices.billingInterval')}{' '}
                                    {t(`pages.zevs.billingIntervals.${interval}`)}
                                </span>
                            ) : (
                                <span className="badge badge-info">{t('common.periodSelector.custom')}</span>
                            )}
                        </span>
                        <FontAwesomeIcon
                            icon={faChevronDown}
                            className="period-selector-caret"
                            data-open={opened || undefined}
                        />
                    </button>
                </Popover.Target>

                <Popover.Dropdown className="period-selector-dropdown">
                    <div className="period-selector-presets">
                        {presets.map((preset) => {
                            const active = preset.range.from === from && preset.range.to === to
                            return (
                                <button
                                    key={preset.id}
                                    className={`period-selector-preset${active ? ' active' : ''}`}
                                    type="button"
                                    onClick={() => apply(preset.range)}
                                >
                                    {preset.label}
                                    {preset.hint && <small>{preset.hint}</small>}
                                </button>
                            )
                        })}
                    </div>

                    {allowCustomRange && (
                        <DatePicker
                            type="range"
                            value={draft}
                            onChange={([nextFrom, nextTo]) => {
                                setDraft([nextFrom, nextTo])
                                // Mantine reports the range twice: once with only the start set.
                                if (nextFrom && nextTo) {
                                    apply({ from: nextFrom, to: nextTo })
                                }
                            }}
                        />
                    )}
                </Popover.Dropdown>
            </Popover>

            <button
                className="button button-secondary"
                type="button"
                onClick={() => onChange(shiftBillingPeriod(from, interval, 1))}
                disabled={!canNavigate}
            >
                {t('pages.invoices.nextPeriod')}
                <FontAwesomeIcon icon={faArrowRight} fixedWidth />
            </button>
        </div>
    )
}
