import { useMemo, useState } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faArrowLeft,
    faArrowRight,
    faCalendarDays,
    faChevronDown,
    faChevronLeft,
    faChevronRight,
    faTriangleExclamation,
} from '@fortawesome/free-solid-svg-icons'
import { Popover } from '@mantine/core'
import { DatePicker } from '@mantine/dates'
import { useTranslation } from 'react-i18next'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import {
    type BillingInterval,
    adjacentBillingPeriod,
    billingPeriodName,
    billingPeriodsOfYear,
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
    /** Named period with accessible stepping chevrons. */
    compact?: boolean
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
    compact = false,
}: PeriodSelectorProps) {
    const { t, i18n } = useTranslation()
    const { settings } = useAppSettings()

    const [opened, setOpened] = useState(false)
    const [draft, setDraft] = useState<[string | null, string | null]>([from || null, to || null])

    const formatDate = (iso: string) => formatShortDate(iso, settings)
    const formatRange = (range: PeriodRange) => `${formatDate(range.from)} → ${formatDate(range.to)}`
    const locale = i18n.resolvedLanguage || i18n.language

    // Prev stops at the community's earliest billable period — never a pre-start range.
    // A custom range cannot step; a whole-period selector steps from any
    // range to the nearest whole period, so a range carried over from another
    // community's interval never strands the chevrons.
    const aligned = isBillingAlignedPeriod(from, to, interval)
    const canStep = !!from && (aligned || !allowCustomRange)
    const step = (direction: -1 | 1) => allowCustomRange
        ? shiftBillingPeriod(from, interval, direction)
        : adjacentBillingPeriod(from, interval, direction)
    const previous = canStep ? step(-1) : null
    const canGoPrevious = !!previous && (!minFrom || previous.from >= minFrom)

    const presets = useMemo<Array<{ id: string; label: string; hint?: string; range: PeriodRange }>>(() => {
        const current = getCurrentBillingPeriod(interval)

        if (!allowCustomRange) {
            // Invoices bill whole periods, so offer recent ones instead of a
            // calendar — none predating the community's first period.
            return recentBillingPeriods(interval, PAST_BILLING_PERIODS, minFrom).map((range, index) => {
                const dates = `${formatShortDate(range.from, settings)} → ${formatShortDate(range.to, settings)}`
                const currentHint = index === 0 ? t('common.periodSelector.currentPeriod') : undefined
                return {
                    id: range.from,
                    label: compact ? billingPeriodName(range.from, range.to, locale) : dates,
                    hint: compact ? [dates, currentHint].filter(Boolean).join(' · ') : currentHint,
                    range,
                }
            })
        }

        return [
            { id: 'current', label: t('common.periodSelector.currentPeriod'), range: current },
            ...QUICK_PRESETS.map(({ preset, labelKey }) => ({
                id: preset,
                label: t(`common.periodSelector.${labelKey}`),
                range: quickRangeToDates(preset),
            })),
        ]
    }, [interval, allowCustomRange, minFrom, t, settings, compact, locale])

    // A compact trigger names whole periods; anything else keeps its dates.
    const named = compact && aligned
    const year = from.slice(0, 4)
    const sizingNames = useMemo(() => named
        ? billingPeriodsOfYear(`${year}-01-01`, interval).map(period => billingPeriodName(period.from, period.to, locale))
        : [], [named, year, interval, locale])
    const triggerText = named ? (
        <span className="period-selector-text">
            <span className="period-selector-range">
                <FontAwesomeIcon icon={faCalendarDays} fixedWidth aria-hidden="true" />
                {/* Every name of the year shares one grid cell, so the trigger
                    keeps the widest one's width and the chevrons stay put. */}
                <span className="period-selector-name">
                    <span>{billingPeriodName(from, to, locale)}</span>
                    {sizingNames.map((name) => (
                        <span key={name} className="period-selector-name-sizer" aria-hidden="true">
                            {name}
                        </span>
                    ))}
                </span>
            </span>
        </span>
    ) : (
        <span className="period-selector-text">
            {title && <span className="period-selector-title">{title}</span>}
            <span className="period-selector-range">
                {from && to ? formatRange({ from, to }) : '—'}
            </span>
            {aligned ? (
                <span className="muted period-selector-interval">
                    {t('pages.invoices.billingInterval')}{' '}
                    {t(`pages.zevs.billingIntervals.${interval}`)}
                </span>
            ) : compact ? (
                // Whole periods are all this selector offers: anything else
                // came from a link and is not one of the community's periods.
                <span className="badge badge-warning">
                    <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth aria-hidden="true" />
                    {t('common.periodSelector.notBillingPeriod')}
                </span>
            ) : (
                <span className="badge badge-info">{t('common.periodSelector.custom')}</span>
            )}
        </span>
    )

    function apply(next: PeriodRange) {
        onChange(next)
        setOpened(false)
    }

    function openPopover() {
        setDraft([from || null, to || null])
        setOpened((wasOpen) => !wasOpen)
    }

    return (
        <div className={compact ? 'period-selector period-selector--compact' : 'period-selector'}>
            {/* Steppers show their arrow; the label names them (visually hidden
                beside the range, which says what is being stepped). */}
            <button
                className="button button-secondary period-selector-step"
                type="button"
                onClick={() => previous && onChange(previous)}
                disabled={!canGoPrevious}
                title={t('pages.invoices.prevPeriod')}
                {...(compact ? { 'aria-label': t('pages.invoices.prevPeriod') } : {})}
            >
                <FontAwesomeIcon icon={compact ? faChevronLeft : faArrowLeft} fixedWidth />
                {!compact && <span className="visually-hidden">{t('pages.invoices.prevPeriod')}</span>}
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
                        title={named ? formatRange({ from, to }) : undefined}
                    >
                        {triggerText}
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
                className="button button-secondary period-selector-step"
                type="button"
                onClick={() => onChange(step(1))}
                disabled={!canStep}
                title={t('pages.invoices.nextPeriod')}
                {...(compact ? { 'aria-label': t('pages.invoices.nextPeriod') } : {})}
            >
                {!compact && <span className="visually-hidden">{t('pages.invoices.nextPeriod')}</span>}
                <FontAwesomeIcon icon={compact ? faChevronRight : faArrowRight} fixedWidth />
            </button>
        </div>
    )
}
