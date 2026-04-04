import dayjs from 'dayjs'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faArrowLeft, faArrowRight } from '@fortawesome/free-solid-svg-icons'
import { DatePickerInput } from '@mantine/dates'
import { Box, Button, Stack, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toDayJsDateFormat, useAppSettings } from '../lib/appSettings'
import { type BillingInterval, getCurrentBillingPeriod, shiftBillingPeriod } from '../lib/billingPeriod'
import { quickRangeToDates } from '../lib/dateRangePresets'

interface BillingPeriodSelectorProps {
    interval: BillingInterval
    from: string
    to: string
    onChange: (next: { from: string; to: string }) => void
}

export function BillingPeriodSelector({ interval, from, to, onChange }: BillingPeriodSelectorProps) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const [isCustomOpen, setIsCustomOpen] = useState(false)
    const [draftRange, setDraftRange] = useState<[string | null, string | null]>([from || null, to || null])

    const fromValue = from ? dayjs(from) : null
    const toValue = to ? dayjs(to) : null

    useEffect(() => {
        setDraftRange([from || null, to || null])
    }, [from, to])

    const updateRange = (nextFrom: string | null, nextTo: string | null) => {
        setDraftRange([nextFrom, nextTo])
        if (!nextFrom || !nextTo) {
            return
        }
        onChange({
            from: nextFrom,
            to: nextTo,
        })
    }

    const presets = [
        {
            value: (() => {
                const range = quickRangeToDates('this_month')
                return [range.from, range.to] as [string, string]
            })(),
            label: t('common.periodSelector.thisMonth'),
        },
        {
            value: (() => {
                const range = quickRangeToDates('last_month')
                return [range.from, range.to] as [string, string]
            })(),
            label: t('common.periodSelector.lastMonth'),
        },
        {
            value: (() => {
                const range = quickRangeToDates('this_quarter')
                return [range.from, range.to] as [string, string]
            })(),
            label: t('common.periodSelector.thisQuarter'),
        },
        {
            value: (() => {
                const range = quickRangeToDates('last_quarter')
                return [range.from, range.to] as [string, string]
            })(),
            label: t('common.periodSelector.lastQuarter'),
        },
        {
            value: (() => {
                const range = quickRangeToDates('this_year')
                return [range.from, range.to] as [string, string]
            })(),
            label: t('common.periodSelector.thisYear'),
        },
        {
            value: (() => {
                const range = quickRangeToDates('last_year')
                return [range.from, range.to] as [string, string]
            })(),
            label: t('common.periodSelector.lastYear'),
        },
    ]

    return (
        <Stack
            direction="row"
            spacing={1}
            alignItems="center"
            justifyContent="center"
            sx={{
                flexWrap: 'wrap',
                p: 1,
                border: '1px solid',
                borderColor: 'divider',
                borderRadius: 1,
                backgroundColor: 'background.paper',
                gap: 1,
            }}
        >
            {!isCustomOpen && (
                <>
                    <button
                        className="button button-secondary"
                        type="button"
                        onClick={() => onChange(shiftBillingPeriod(from, interval, -1))}
                        disabled={!from}
                        style={{ flexShrink: 0, marginRight: 'auto' }}
                    >
                        <FontAwesomeIcon icon={faArrowLeft} fixedWidth />
                        {t('pages.invoices.prevPeriod')}
                    </button>

                    <Box sx={{ textAlign: 'center' }}>
                        <Typography sx={{ fontWeight: 700, fontSize: { xs: '0.85rem', sm: '1rem' } }}>
                            {from && to
                                ? `${t('common.periodSelector.period')}: ${fromValue?.format(toDayJsDateFormat(settings.date_format_short)) ?? from} → ${toValue?.format(toDayJsDateFormat(settings.date_format_short)) ?? to}`
                                : '—'}
                        </Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ fontSize: { xs: '0.75rem', sm: '0.875rem' } }}>
                            {t('pages.invoices.billingInterval')} {t(`pages.zevs.billingIntervals.${interval}`)}
                        </Typography>
                    </Box>

                    <Button
                        size="small"
                        variant="outlined"
                        color="inherit"
                        sx={{ borderRadius: 999, textTransform: 'none', px: 1.5, flexShrink: 0 }}
                        onClick={() => setIsCustomOpen(true)}
                    >
                        {t('common.periodSelector.customPeriod')}
                    </Button>

                    <button
                        className="button button-secondary"
                        type="button"
                        onClick={() => onChange(shiftBillingPeriod(from, interval, 1))}
                        disabled={!from}
                        style={{ flexShrink: 0, marginLeft: 'auto' }}
                    >
                        {t('pages.invoices.nextPeriod')}
                        <FontAwesomeIcon icon={faArrowRight} fixedWidth />
                    </button>
                </>
            )}

            {isCustomOpen && (
                <>
                    <Box sx={{ maxWidth: 400, minWidth: { xs: '100%', sm: 280 } }}>
                        <DatePickerInput
                            type="range"
                            value={draftRange}
                            onChange={([nextFrom, nextTo]) => updateRange(nextFrom, nextTo)}
                            presets={presets}
                            valueFormat={toDayJsDateFormat(settings.date_format_short)}
                            clearable={false}
                            popoverProps={{ withinPortal: true }}
                        />
                    </Box>

                    <Button
                        size="small"
                        variant="contained"
                        color="primary"
                        sx={{ borderRadius: 999, textTransform: 'none', px: 1.5, flexShrink: 0 }}
                        onClick={() => {
                            onChange(getCurrentBillingPeriod(interval))
                            setIsCustomOpen(false)
                        }}
                    >
                        {t('common.periodSelector.backToBillingPeriod')}
                    </Button>
                </>
            )}
        </Stack>
    )
}