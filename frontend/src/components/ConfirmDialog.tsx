import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useToast } from '../lib/toast'
import { Z_MODAL } from '../lib/zLayers'
import { useDialogBehavior } from './useDialogBehavior'

interface ConfirmDialogOptions {
    title: string
    message: string
    confirmText?: string
    cancelText?: string
    isDangerous?: boolean
    /** Initial submission guard; changing typed input must be validated in onConfirm. */
    confirmDisabled?: boolean
    children?: ReactNode
    /**
     * Return false to keep the dialog open when submission validation fails.
     * Callers must report failures after dismissal; the hook only reports active failures.
     * Consume rejections already reported by the caller with consumeReportedError.
     */
    onConfirm: () => void | false | Promise<void | false>
    onCancel?: () => void
}

type ConfirmDialogProps = Omit<ConfirmDialogOptions, 'onConfirm' | 'onCancel'> & {
    isLoading?: boolean
    /** Disables the rendered button; onConfirm still validates current typed input. */
    confirmDisabled?: boolean
    onConfirm: () => void
    onCancel: () => void
}

/** Consume a rejection only when the operation already reports its own error. */
export function consumeReportedError(operation: Promise<unknown>): Promise<void> {
    return operation.then(() => undefined, () => undefined)
}

export function useConfirmDialog() {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const [state, setState] = useState<{ options: ConfirmDialogOptions; isLoading: boolean } | null>(null)
    const activeRef = useRef<typeof state>(null)

    useEffect(() => () => { activeRef.current = null }, [])

    const confirm = useCallback((options: ConfirmDialogOptions) => {
        // Each opening owns its completion, even when callers reuse options.
        const next = { options: { ...options }, isLoading: false }
        activeRef.current = next
        setState(next)
    }, [])

    const handleConfirm = async () => {
        if (!state || activeRef.current !== state || state.isLoading || state.options.confirmDisabled) return
        const pending = { ...state, isLoading: true }
        activeRef.current = pending
        setState(pending)
        try {
            const result = state.options.onConfirm()
            const outcome = result === undefined || result === false ? result : await result
            // Validation refusal keeps the dialog open without reporting an error.
            if (outcome === false && activeRef.current === pending) {
                activeRef.current = state
                setState(state)
            }
        } catch {
            if (activeRef.current === pending) pushToast(t('common.error'), 'error')
        } finally {
            if (activeRef.current === pending) {
                activeRef.current = null
                setState(null)
            }
        }
    }

    const handleCancel = () => {
        if (!state || activeRef.current?.options !== state.options) return
        activeRef.current = null
        setState(null)
        state.options.onCancel?.()
    }

    return { dialog: state?.options ?? null, confirm, handleConfirm, handleCancel, isLoading: state?.isLoading ?? false }
}

export function ConfirmDialog({
    title,
    message,
    confirmText,
    cancelText,
    isDangerous = false,
    confirmDisabled = false,
    children,
    isLoading = false,
    onConfirm,
    onCancel,
}: ConfirmDialogProps) {
    const { t } = useTranslation()
    const titleId = useId()
    const { dialogRef, depth, isTop } = useDialogBehavior({ onClose: onCancel })

    return (
        <div
            className="dialog-scrim"
            style={{ zIndex: Z_MODAL + depth }}
            onClick={() => { if (isTop()) onCancel() }}
        >
            <div
                ref={dialogRef}
                role="dialog"
                aria-modal={isTop() || undefined}
                aria-labelledby={titleId}
                tabIndex={-1}
                className="card confirm-dialog"
                onClick={(e) => e.stopPropagation()}
            >
                <h3 id={titleId} className="mb-1">{title}</h3>
                <p className="confirm-dialog-message">{message}</p>
                <p role="status" className={isLoading ? 'confirm-dialog-message' : 'visually-hidden'}>
                    {isLoading ? t('common.actionContinues') : ''}
                </p>
                {children ? <div className="form-grid mb-15">{children}</div> : null}
                <div className="actions-row actions-row-wrap actions-row-end actions-row-gap-lg">
                    <button
                        className="button button-secondary"
                        onClick={onCancel}
                        type="button"
                    >
                        {isLoading ? t('common.close') : (cancelText || t('common.cancel'))}
                    </button>
                    <button
                        className={`button ${isDangerous ? 'button-danger' : 'button-primary'}`}
                        onClick={onConfirm}
                        disabled={isLoading || confirmDisabled}
                        type="button"
                    >
                        {isLoading ? t('common.processing') : (confirmText || t('common.confirm'))}
                    </button>
                </div>
            </div>
        </div>
    )
}
