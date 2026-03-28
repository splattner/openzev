import dayjs, { type Dayjs } from 'dayjs'
import { Box, Button, Stack, Typography } from '@mui/material'
import { AdapterDayjs } from '@mui/x-date-pickers/AdapterDayjs'
import { DatePicker } from '@mui/x-date-pickers/DatePicker'
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider'
import {
    quickRangeToDates,
    QUICK_RANGE_OPTIONS,
    type QuickRangePreset,
} from '../lib/dateRangePresets'
import { toDayJsDateFormat, useAppSettings } from '../lib/appSettings'

interface DateRangeShortcutPickerProps {
    label?: string
    from: string
    to: string
    onChange: (next: { from: string; to: string }) => void
}

const shortcutOptions = QUICK_RANGE_OPTIONS.filter((option) => option.value !== 'custom')

export function DateRangeShortcutPicker({ label = 'Period', from, to, onChange }: DateRangeShortcutPickerProps) {
    const fromValue = from ? dayjs(from) : null
    const toValue = to ? dayjs(to) : null

    const { settings } = useAppSettings()

    const updateRange = (nextFrom: Dayjs | null, nextTo: Dayjs | null) => {
        if (!nextFrom || !nextTo || !nextFrom.isValid() || !nextTo.isValid()) {
            return
        }
        onChange({
            from: nextFrom.format('YYYY-MM-DD'),
            to: nextTo.format('YYYY-MM-DD'),
        })
    }

    return (
        <label>
            <span>{label}</span>
            <LocalizationProvider dateAdapter={AdapterDayjs}>
                <Stack spacing={1} sx={{ mt: 0.5 }}>
                    <Stack
                        direction="row"
                        spacing={1}
                        alignItems="center"
                        sx={{
                            flexWrap: 'wrap',
                            p: 1,
                            border: '1px solid',
                            borderColor: 'divider',
                            borderRadius: 1,
                            backgroundColor: 'background.paper',
                        }}
                    >
                        <Box sx={{ minWidth: 150, flex: '1 1 160px' }}>
                            <DatePicker
                                format={toDayJsDateFormat(settings.date_format_short)}
                                value={fromValue}
                                onChange={(nextFrom) => updateRange(nextFrom, toValue)}
                                slotProps={{
                                    textField: {
                                        size: 'small',
                                        fullWidth: true,
                                    },
                                }}
                            />
                        </Box>
                        <Typography variant="body2" color="text.secondary">
                            {'->'}
                        </Typography>
                        <Box sx={{ minWidth: 150, flex: '1 1 160px' }}>
                            <DatePicker
                                format={toDayJsDateFormat(settings.date_format_short)}
                                value={toValue}
                                onChange={(nextTo) => updateRange(fromValue, nextTo)}
                                slotProps={{
                                    textField: {
                                        size: 'small',
                                        fullWidth: true,
                                    },
                                }}
                            />
                        </Box>
                    </Stack>
                </Stack>
                <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap', gap: 1 }}>
                    {shortcutOptions.map((option) => (
                        <Button
                            key={option.value}
                            size="small"
                            variant="outlined"
                            color="inherit"
                            sx={{
                                borderRadius: 999,
                                textTransform: 'none',
                                px: 1.5,
                            }}
                            onClick={() => {
                                const range = quickRangeToDates(option.value as Exclude<QuickRangePreset, 'custom'>)
                                onChange(range)
                            }}
                        >
                            {option.label}
                        </Button>
                    ))}
                </Stack>
            </LocalizationProvider>
        </label>
    )
}
