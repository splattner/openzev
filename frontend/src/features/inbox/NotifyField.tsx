import { useTranslation } from 'react-i18next'

type NotifyFieldProps = {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}

/** The opt-in email for a delivery; the bell notification is not optional (spec §7.2). */
export function NotifyField({ checked, onChange, disabled }: NotifyFieldProps) {
  const { t } = useTranslation()
  return (
    <div className="grid-span-full">
      <label className="checkbox-row">
        <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} disabled={disabled} />
        <span>{t('inbox.notify.label')}</span>
      </label>
      <small className="muted">{t('inbox.notify.hint')}</small>
    </div>
  )
}
