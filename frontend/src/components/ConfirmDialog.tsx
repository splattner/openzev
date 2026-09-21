import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useToast } from '../lib/toast'
import { Z_MODAL } from '../lib/zLayers'
import { focusables, isTopModal, modalDepth, useModalStack } from './FormModal'

interface ConfirmDialogOptions {
    title: string
    message: string
    confirmText?: string
    cancelText?: string
    isDangerous?: boolean
    confirmDisabled?: boolean
    children?: ReactNode
    onConfirm: () => void | Promise<void>
    onCancel?: () => void
}

export function useConfirmDialog() {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const [dialog, setDialog] = useState<ConfirmDialogOptions | null>(null)
    const [isLoading, setIsLoading] = useState(false)

    const confirm = (options: ConfirmDialogOptions) => {
        setDialog(options)
    }

    const handleConfirm = async () => {
        setIsLoading(true)
        try {
            const result = dialog?.onConfirm()
            if (result instanceof Promise) {
                await result
            }
            setDialog(null)
        } catch {
            pushToast(t('common.error'), 'error')
            setDialog(null)
        } finally {
            setIsLoading(false)
        }
    }

    const handleCancel = () => {
        dialog?.onCancel?.()
        setDialog(null)
    }

    return { dialog, confirm, handleConfirm, handleCancel, isLoading }
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
}: ConfirmDialogOptions & { isLoading?: boolean; onConfirm: () => void; onCancel: () => void }) {
    const { t } = useTranslation()
    const stackId = useModalStack()
    const titleId = useId()
    const dialogRef = useRef<HTMLDivElement>(null)
    const restoreRef = useRef<HTMLElement | null>(null)
    const onCancelRef = useRef(onCancel)
    useEffect(() => {
        onCancelRef.current = onCancel
    }, [onCancel])
    // Top-most only: Escape/Tab belong to this dialog while it sits above
    // other modals (e.g. overwrite confirmation over the import wizard).
    // Auto-focus keeps keyboard users inside the confirmation.
    useEffect(() => {
        // StrictMode replays effects while the dialog already has focus.
        // Preserve the original opener instead of remembering the dialog itself.
        if (document.activeElement instanceof HTMLElement && !dialogRef.current?.contains(document.activeElement)) {
            restoreRef.current = document.activeElement
        }
        dialogRef.current?.focus()
        const onKeyDown = (event: KeyboardEvent) => {
            if (!isTopModal(stackId) || event.defaultPrevented) return
            if (event.key === 'Escape') {
                event.preventDefault()
                onCancelRef.current()
                return
            }
            if (event.key !== 'Tab' || !dialogRef.current) return
            const items = focusables(dialogRef.current)
            if (items.length === 0) return
            const first = items[0]
            const last = items[items.length - 1]
            const active = document.activeElement as Node | null
            const inside = active !== null && dialogRef.current.contains(active)
            if (event.shiftKey && (!inside || document.activeElement === first)) {
                event.preventDefault()
                last.focus()
            } else if (!event.shiftKey && (!inside || document.activeElement === last)) {
                event.preventDefault()
                first.focus()
            }
        }
        document.addEventListener('keydown', onKeyDown)
        return () => {
            document.removeEventListener('keydown', onKeyDown)
            const active = document.activeElement
            if (active instanceof HTMLElement && active !== document.body && document.contains(active)) return
            if (restoreRef.current && document.contains(restoreRef.current)) restoreRef.current.focus()
        }
    }, [stackId])
    const depth = Math.max(0, modalDepth(stackId))
    return (
        <div
            style={{
                position: 'fixed',
                inset: 0,
                backgroundColor: 'rgba(0, 0, 0, 0.5)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: Z_MODAL + depth,
            }}
            onClick={onCancel}
        >
            <div
                ref={dialogRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                tabIndex={-1}
                className="card"
                style={{
                    maxWidth: '400px',
                    padding: '2rem',
                    animation: 'fadeIn 0.2s ease',
                    outline: 'none',
                }}
                onClick={(e) => e.stopPropagation()}
            >
                <h3 id={titleId} style={{ marginBottom: '1rem' }}>{title}</h3>
                <p style={{ marginBottom: '1.5rem', color: 'var(--text-body)', lineHeight: '1.5' }}>{message}</p>
                {children ? <div className="form-grid" style={{ marginBottom: '1.5rem' }}>{children}</div> : null}
                <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                    <button
                        className="button button-secondary"
                        onClick={onCancel}
                        disabled={isLoading}
                        type="button"
                    >
                        {cancelText || t('common.cancel')}
                    </button>
                    <button
                        className={`button ${isDangerous ? 'danger' : ''}`}
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
