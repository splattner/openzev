import type { Ref } from 'react'
import { DatePickerInput } from '@mantine/dates'
import { toDayJsDateFormat, useAppSettings } from '../lib/appSettings'

interface CivilDateInputProps {
    /** Plain civil date as `YYYY-MM-DD`; empty string or null clears the field. */
    value: string | null
    onChange: (iso: string | null) => void
    /** Earliest/latest selectable civil date, as `YYYY-MM-DD`. Omit for no bound. */
    minDate?: string
    maxDate?: string
    /** Show the clear button. Turn off for a required field that must always hold a date. */
    clearable?: boolean
    /** Ref to the focusable trigger, e.g. to focus the field from a deep link. */
    inputRef?: Ref<HTMLButtonElement>
}

/**
 * The app's single date-picker for form fields (ADR 0007 data contract).
 *
 * Mantine's DatePickerInput natively works in `YYYY-MM-DD` civil-date strings
 * (`toDateString` formats via local dayjs), so values pass through unchanged:
 * no `Date` round-trip, no timezone shift in either direction. Only the
 * visible label is formatted to the user's short date format.
 */
export function CivilDateInput({ value, onChange, minDate, maxDate, clearable = true, inputRef }: CivilDateInputProps) {
    const { settings } = useAppSettings()
    return (
        <DatePickerInput
            valueFormat={toDayJsDateFormat(settings.date_format_short)}
            value={value || null}
            onChange={onChange}
            minDate={minDate}
            maxDate={maxDate}
            clearable={clearable}
            ref={inputRef}
        />
    )
}
