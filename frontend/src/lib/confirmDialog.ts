import { useRef, useState } from 'react'

interface ConfirmOptions {
    title: string
    message: string
    confirmLabel?: string
    danger?: boolean
}

interface DialogState {
    title: string
    message: string
    confirmText: string
    isDangerous: boolean
    isLoading: boolean
    onConfirm: () => void
    onCancel: () => void
}

export function useConfirmDialog() {
    const [dialogState, setDialogState] = useState<DialogState | null>(null)
    const resolverRef = useRef<((value: boolean) => void) | null>(null)

    function confirm(options: ConfirmOptions): Promise<boolean> {
        return new Promise<boolean>((resolve) => {
            resolverRef.current = resolve
            setDialogState({
                title: options.title,
                message: options.message,
                confirmText: options.confirmLabel ?? 'Confirm',
                isDangerous: options.danger ?? false,
                isLoading: false,
                onConfirm: () => {
                    setDialogState(null)
                    resolve(true)
                },
                onCancel: () => {
                    setDialogState(null)
                    resolve(false)
                },
            })
        })
    }

    return { confirm, dialogProps: dialogState }
}
