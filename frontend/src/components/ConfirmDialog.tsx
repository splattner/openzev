import { useState } from 'react'

export interface ConfirmDialogOptions {
    title: string
    message: string
    confirmText?: string
    cancelText?: string
    isDangerous?: boolean
    onConfirm: () => void | Promise<void>
    onCancel?: () => void
}

export function useConfirmDialog() {
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
    confirmText = 'Confirm',
    cancelText = 'Cancel',
    isDangerous = false,
    isLoading = false,
    onConfirm,
    onCancel,
}: ConfirmDialogOptions & { isLoading?: boolean; onConfirm: () => void; onCancel: () => void }) {
    return (
        <div
            style={{
                position: 'fixed',
                inset: 0,
                backgroundColor: 'rgba(0, 0, 0, 0.5)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 1000,
            }}
            onClick={onCancel}
        >
            <div
                className="card"
                style={{
                    maxWidth: '400px',
                    padding: '2rem',
                    animation: 'fadeIn 0.2s ease',
                }}
                onClick={(e) => e.stopPropagation()}
            >
                <h3 style={{ marginBottom: '1rem' }}>{title}</h3>
                <p style={{ marginBottom: '1.5rem', color: '#666', lineHeight: '1.5' }}>{message}</p>
                <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                    <button
                        className="button button-secondary"
                        onClick={onCancel}
                        disabled={isLoading}
                        type="button"
                    >
                        {cancelText}
                    </button>
                    <button
                        className={`button ${isDangerous ? 'danger' : ''}`}
                        onClick={onConfirm}
                        disabled={isLoading}
                        type="button"
                    >
                        {isLoading ? 'Processing...' : confirmText}
                    </button>
                </div>
            </div>
        </div>
    )
}
