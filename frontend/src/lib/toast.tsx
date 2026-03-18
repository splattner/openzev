import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

type ToastType = 'success' | 'error' | 'info'

interface ToastMessage {
    id: number
    message: string
    type: ToastType
}

interface ToastContextValue {
    pushToast: (message: string, type?: ToastType) => void
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined)

export function ToastProvider({ children }: { children: ReactNode }) {
    const [toasts, setToasts] = useState<ToastMessage[]>([])

    const pushToast = useCallback((message: string, type: ToastType = 'info') => {
        const id = Date.now() + Math.floor(Math.random() * 1000)
        setToasts((current) => [...current, { id, message, type }])
        window.setTimeout(() => {
            setToasts((current) => current.filter((toast) => toast.id !== id))
        }, 3500)
    }, [])

    const value = useMemo<ToastContextValue>(() => ({ pushToast }), [pushToast])

    return (
        <ToastContext.Provider value={value}>
            {children}
            <div className="toast-stack">
                {toasts.map((toast) => (
                    <div key={toast.id} className={`toast toast-${toast.type}`}>
                        {toast.message}
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    )
}

export function useToast() {
    const context = useContext(ToastContext)
    if (!context) {
        throw new Error('useToast must be used within ToastProvider')
    }
    return context
}