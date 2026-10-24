import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

type FormModalFooterProps = {
  onCancel: () => void
  isPending: boolean
  /** Disables submission when the form is invalid. */
  disabled?: boolean
  submitIcon?: ReactNode
  submitLabel?: ReactNode
  cancelIcon?: ReactNode
  /** Tighter top margin for the assignment modal variant. */
  compact?: boolean
  /** The form this footer submits, when it sits outside the form element. */
  formId?: string
}

export function FormModalFooter({ onCancel, isPending, disabled, submitIcon, submitLabel, cancelIcon, compact, formId }: FormModalFooterProps) {
  const { t } = useTranslation()
  return (
    <div className={`dialog-actions grid-span-full ${compact ? 'mt-05' : 'mt-1'}`}>
      <button className="button button-secondary" type="button" onClick={onCancel}>
        {cancelIcon}
        {t('common.cancel')}
      </button>
      <button className="button button-primary" type="submit" form={formId} disabled={isPending || disabled}>
        {submitIcon}
        {submitLabel ?? t('common.save')}
      </button>
    </div>
  )
}
