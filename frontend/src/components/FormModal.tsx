import { useEffect, useId, useRef, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Z_MODAL } from '../lib/zLayers'

interface FormModalProps {
    isOpen: boolean
    title: string
    children: ReactNode
    onClose: () => void
    maxWidth?: string
}

// Open-modal stack: with nested modals (e.g. the import wizard's overwrite
// confirmation on top of the wizard) only the top-most dialog may claim
// Escape, and closing it returns focus to the dialog below.
// Module-level state is intentional: all modal instances share one Escape/focus stack.
const modalStack: string[] = []
const modalNodes = new Map<string, HTMLElement>()

export function useModalStack(isOpen = true): string {
    const id = useId()
    useEffect(() => {
        if (!isOpen) return
        modalStack.push(id)
        return () => {
            const index = modalStack.indexOf(id)
            if (index >= 0) modalStack.splice(index, 1)
        }
    }, [id, isOpen])
    return id
}

export function isTopModal(id: string): boolean {
    return modalStack.length > 0 && modalStack[modalStack.length - 1] === id
}

export function focusables(root: HTMLElement): HTMLElement[] {
    return Array.from(
        root.querySelectorAll<HTMLElement>(
            'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
    )
}

export function modalDepth(id: string): number {
    return modalStack.indexOf(id)
}

export function FormModal({ isOpen, title, children, onClose, maxWidth = '600px' }: FormModalProps) {
    const { t } = useTranslation()
    const titleId = useId()
    const stackId = useModalStack(isOpen)
    const dialogRef = useRef<HTMLDivElement>(null)
    const restoreRef = useRef<HTMLElement | null>(null)
    const onCloseRef = useRef(onClose)

    useEffect(() => {
        onCloseRef.current = onClose
    }, [onClose])

    useEffect(() => {
        if (!isOpen) return
        if (document.activeElement instanceof HTMLElement && !dialogRef.current?.contains(document.activeElement)) {
            restoreRef.current = document.activeElement
        }
        dialogRef.current?.focus()
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                if (!isTopModal(stackId) || event.defaultPrevented) return
                event.preventDefault()
                onCloseRef.current()
                return
            }
            // Only the top-most dialog traps Tab; background modals must not
            // steal focus while a confirmation sits on top of the wizard.
            if (event.key !== 'Tab' || !dialogRef.current) return
            if (!isTopModal(stackId) || event.defaultPrevented) return
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
        if (dialogRef.current) modalNodes.set(stackId, dialogRef.current)
        return () => {
            document.removeEventListener('keydown', onKeyDown)
            modalNodes.delete(stackId)
            const active = document.activeElement
            // Focus already moved to a live element (e.g. a child dialog
            // took it): leave it alone. body means focus was lost with the
            // removed dialog, so fall through to restore.
            if (active instanceof HTMLElement && active !== document.body && document.contains(active)) return
            // Otherwise return focus to the dialog below, or the opener.
            const below = modalStack.filter((entry) => entry !== stackId)
            const belowNode = below.length > 0 ? modalNodes.get(below[below.length - 1]) : undefined
            if (belowNode && document.contains(belowNode)) belowNode.focus()
            else restoreRef.current?.focus()
        }
    }, [isOpen, stackId])

    if (!isOpen) return null

    return (
        <div
            style={{
                position: 'fixed',
                inset: 0,
                backgroundColor: 'rgba(0, 0, 0, 0.5)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: Z_MODAL,
            }}
            onClick={onClose}
        >
            <div
                ref={dialogRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                tabIndex={-1}
                style={{
                    backgroundColor: 'var(--surface-card)',
                    borderRadius: '0.5rem',
                    boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1)',
                    maxWidth,
                    width: '90%',
                    maxHeight: '90vh',
                    overflow: 'auto',
                    padding: '2rem',
                    outline: 'none',
                }}
                onClick={(e) => e.stopPropagation()}
            >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                    <h2 id={titleId} style={{ margin: 0 }}>{title}</h2>
                    <button
                        onClick={onClose}
                        aria-label={t('common.close')}
                        style={{
                            background: 'none',
                            border: 'none',
                            fontSize: '1.5rem',
                            cursor: 'pointer',
                            color: 'var(--text-muted)',
                            padding: '0',
                            width: '2rem',
                            height: '2rem',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                        }}
                    >
                        <span aria-hidden="true">✕</span>
                    </button>
                </div>
                {children}
            </div>
        </div>
    )
}
