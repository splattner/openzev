import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useFormModalGuard } from './FormModal'

type FormModalFooterProps = {
  /** Leaves the form; asked about first when a surrounding `FormModal` holds unsaved input. */
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

type FormModalCancelButtonProps = {
  onCancel: () => void
  disabled?: boolean
  icon?: ReactNode
}

/** A hand-written Cancel for a `FormModal`: leaving asks first when there is unsaved input. */
export function FormModalCancelButton({ onCancel, disabled, icon }: FormModalCancelButtonProps) {
  const { t } = useTranslation()
  const guard = useFormModalGuard()
  return (
    <button className="button button-secondary" type="button" onClick={() => guard(onCancel)} disabled={disabled}>
      {icon}
      {t('common.cancel')}
    </button>
  )
}

export function FormModalFooter({ onCancel, isPending, disabled, submitIcon, submitLabel, cancelIcon, compact, formId }: FormModalFooterProps) {
  const { t } = useTranslation()
  return (
    <div className={`dialog-actions grid-span-full ${compact ? 'mt-05' : 'mt-1'}`}>
      <FormModalCancelButton onCancel={onCancel} icon={cancelIcon} />
      <button className="button button-primary" type="submit" form={formId} disabled={isPending || disabled}>
        {submitIcon}
        {submitLabel ?? t('common.save')}
      </button>
    </div>
  )
}
