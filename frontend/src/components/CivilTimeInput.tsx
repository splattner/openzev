import { TimePicker } from '@mantine/dates'
import { useTranslation } from 'react-i18next'

interface CivilTimeInputProps {
    /** Time of day as `HH:mm` or `HH:mm:ss` (the API sends seconds); empty or null clears the field. */
    value: string | null
    /** `HH:mm`, or `''` when cleared. */
    onChange: (time: string) => void
    clearable?: boolean
    disabled?: boolean
}

/**
 * The app's time-of-day field. A native `<input type="time">` follows the
 * browser's locale, so it would show "07:00 AM" to someone whose system is set
 * to 12 hours, while every time the app writes is 24-hour (`HH:mm`, see the
 * date-time formats in the regional settings). This one is always 24-hour and
 * keeps the value as the plain `HH:mm` string the API takes.
 */
export function CivilTimeInput({ value, onChange, clearable = true, disabled = false }: CivilTimeInputProps) {
    const { t } = useTranslation()
    return (
        <TimePicker
            format="24h"
            value={value ? value.slice(0, 5) : ''}
            onChange={(next) => onChange(next ? next.slice(0, 5) : '')}
            clearable={clearable}
            disabled={disabled}
            hoursInputLabel={t('common.timeHours')}
            minutesInputLabel={t('common.timeMinutes')}
        />
    )
}
