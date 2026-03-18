import dayjs, { type Dayjs } from 'dayjs'
import { AdapterDayjs } from '@mui/x-date-pickers/AdapterDayjs'
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider'
import { PickersShortcuts } from '@mui/x-date-pickers/PickersShortcuts'
import { DateRangePicker } from '@mui/x-date-pickers-pro/DateRangePicker'
import { SingleInputDateRangeField } from '@mui/x-date-pickers-pro/SingleInputDateRangeField'
import {
    quickRangeToDates,
    QUICK_RANGE_OPTIONS,
    type QuickRangePreset,
} from '../lib/dateRangePresets'
import { toDayJsDateFormat, useAppSettings } from '../lib/appSettings'

type DateRangeValue = [Dayjs | null, Dayjs | null]

interface DateRangeShortcutPickerProps {
    label?: string
    from: string
    to: string
    onChange: (next: { from: string; to: string }) => void
}

const shortcutOptions = QUICK_RANGE_OPTIONS.filter((option) => option.value !== 'custom')

export function DateRangeShortcutPicker({ label = 'Period', from, to, onChange }: DateRangeShortcutPickerProps) {
    const value: DateRangeValue = [from ? dayjs(from) : null, to ? dayjs(to) : null]

    const { settings } = useAppSettings()
    const shortcuts = shortcutOptions.map((option) => ({
        label: option.label,
        getValue: () => {
            const range = quickRangeToDates(option.value as Exclude<QuickRangePreset, 'custom'>)
            return [dayjs(range.from), dayjs(range.to)] as DateRangeValue
        },
    }))

    return (
        <label>
            <span>{label}</span>
            <LocalizationProvider dateAdapter={AdapterDayjs}>
                <DateRangePicker
                    format={toDayJsDateFormat(settings.date_format_short)}
                    slots={{
                        field: SingleInputDateRangeField,
                        shortcuts: PickersShortcuts,
                    }}
                    slotProps={{
                        shortcuts: {
                            items: shortcuts,
                        },
                    }}
                    value={value}
                    onChange={(nextValue) => {
                        const [nextFrom, nextTo] = nextValue
                        if (!nextFrom || !nextTo) return
                        onChange({
                            from: nextFrom.format('YYYY-MM-DD'),
                            to: nextTo.format('YYYY-MM-DD'),
                        })
                    }}
                />
            </LocalizationProvider>
        </label>
    )
}
