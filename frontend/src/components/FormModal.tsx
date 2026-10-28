import { createContext, useContext, useId, useRef, useState, type ReactNode, type RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import { UNSAFE_DataRouterContext } from 'react-router-dom'
import { Z_MODAL } from '../lib/zLayers'
import { ConfirmDialog } from './ConfirmDialog'
import { useDialogBehavior } from './useDialogBehavior'
import { useDraftConfirm, useRouterDraftBlock } from './useDraftGuard'
import { useUnsavedInput } from './useUnsavedInput'

/** Named widths, chosen for content (SPEC-2026-10-ui-patterns §6.1). Responsive bounds stay in CSS. */
export type FormModalSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl'

interface FormModalProps {
    isOpen: boolean
    title: string
    children: ReactNode
    onClose: () => void
    /** One to three fields: xs. The default sm suits most forms; md/lg for wide forms; xl for wide read-mostly content. */
    size?: FormModalSize
    /** @deprecated Use `size`; removed once the last caller has moved (UI patterns phase 4). */
    maxWidth?: string
    /**
     * Overrides the unsaved-input check, which reads the form controls. Pass
     * false for a step with nothing to lose (a finished wizard) and true when
     * the draft lives outside the controls.
     */
    dirty?: boolean
    returnFocusRef?: RefObject<HTMLElement | null>
}

type FormModalGuard = {
    /** Run `action` (usually leaving the dialog) now, or once the user has agreed to discard the draft. */
    guard: (action: () => void) => void
}

const FormModalGuardContext = createContext<FormModalGuard | null>(null)

/**
 * For a Cancel or Close control written by hand inside a `FormModal`: wrap what
 * it does in the returned function so unsaved input is asked about. Outside a
 * dialog the action runs as is. `FormModalFooter` does this for its Cancel.
 */
export function useFormModalGuard() {
    return useContext(FormModalGuardContext)?.guard ?? ((action: () => void) => action())
}

function RouterDraftBlock(props: Parameters<typeof useRouterDraftBlock>[0]) {
    useRouterDraftBlock(props)
    return null
}

export function FormModal({ isOpen, ...props }: FormModalProps) {
    return isOpen ? <OpenFormModal {...props} /> : null
}

function OpenFormModal({ title, children, onClose, size = 'sm', maxWidth, dirty, returnFocusRef }: Omit<FormModalProps, 'isOpen'>) {
    const { t } = useTranslation()
    const titleId = useId()
    const hasDataRouter = useContext(UNSAFE_DataRouterContext) !== null
    // Only the discard question is ever asked, so no confirm hook (and no toast context) is needed.
    const [discard, setDiscard] = useState<Parameters<Parameters<typeof useDraftConfirm>[0]['confirm']>[0] | null>(null)
    const bypass = useRef(false)

    // Escape, scrim and X reach the same guard as Cancel.
    const { dialogRef, depth, isTop } = useDialogBehavior({ onClose: requestClose, returnFocusRef })
    const readsDirty = useUnsavedInput(dialogRef)
    const guard = useDraftConfirm({ dirty: dirty === undefined ? readsDirty : dirty, confirm: setDiscard, bypass })
    function requestClose() {
        guard.run(onClose)
    }

    return (
        <>
            <FormModalGuardContext.Provider value={{ guard: guard.run }}>
                <div
                    className="dialog-scrim"
                    style={{ zIndex: Z_MODAL + depth }}
                    onClick={() => { if (isTop()) requestClose() }}
                >
                    <div
                        ref={dialogRef}
                        role="dialog"
                        aria-modal={isTop() || undefined}
                        aria-labelledby={titleId}
                        tabIndex={-1}
                        className={`form-modal form-modal-${size}`}
                        style={maxWidth ? { maxWidth } : undefined}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="form-modal-header">
                            <h2 id={titleId}>{title}</h2>
                            <button
                                type="button"
                                onClick={requestClose}
                                aria-label={t('common.close')}
                                className="form-modal-close"
                            >
                                <span aria-hidden="true">✕</span>
                            </button>
                        </div>
                        {children}
                    </div>
                </div>
            </FormModalGuardContext.Provider>
            {hasDataRouter && <RouterDraftBlock ask={guard.ask} isActive={guard.isActive} bypass={bypass} />}
            {discard && (
                <ConfirmDialog
                    {...discard}
                    onConfirm={() => { setDiscard(null); discard.onConfirm() }}
                    onCancel={() => { setDiscard(null); discard.onCancel() }}
                />
            )}
        </>
    )
}
