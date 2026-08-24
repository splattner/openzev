import { DatePickerInput } from '@mantine/dates'
import { toDayJsDateFormat, useAppSettings } from '../lib/appSettings'

interface CivilDateInputProps {
    /** Plain civil date as `YYYY-MM-DD`; empty string or null clears the field. */
    value: string | null
    onChange: (iso: string | null) => void
    clearable?: boolean
}

/**
 * The app's single date-picker for form fields (ADR 0007 data contract).
 *
 * Mantine's DatePickerInput natively works in `YYYY-MM-DD` civil-date strings
 * (`toDateString` formats via local dayjs), so values pass through unchanged:
 * no `Date` round-trip, no timezone shift in either direction. Only the
 * visible label is formatted to the user's short date format.
 */
export function CivilDateInput({ value, onChange, clearable = true }: CivilDateInputProps) {
    const { settings } = useAppSettings()
    return (
        <DatePickerInput
            clearable={clearable}
            valueFormat={toDayJsDateFormat(settings.date_format_short)}
            value={value || null}
            onChange={onChange}
        />
    )
}
