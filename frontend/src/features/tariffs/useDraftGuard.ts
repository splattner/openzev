import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react'
import { useBlocker } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

type ConfirmOptions = {
  title: string
  message: string
  confirmText: string
  cancelText: string
  isDangerous: boolean
  onConfirm: () => void
  onCancel: () => void
}

type DraftGuardParams = {
  /** The open form has unsaved changes. */
  dirty: boolean
  /** A save is in flight: leaving does not stop it. */
  saving: boolean
  confirm: (options: ConfirmOptions) => void
  /** Raised while the page performs a navigation of its own, which must not be asked about. */
  bypass: RefObject<boolean>
}

/** Let `change` navigate without the guard asking; the guard resumes right after. */
export function allowNavigation(bypass: RefObject<boolean>, change: () => void) {
  bypass.current = true
  try {
    change()
  } finally {
    queueMicrotask(() => { bypass.current = false })
  }
}

/**
 * Asks before unsaved input is dropped (SPEC-2026-10-ui-patterns §6.2): by an
 * action in the pane (`run`), by browser Back/Forward or a link elsewhere in
 * the app (the router blocker), and by a reload or closed tab
 * (`beforeunload`, the browser's own prompt, no recovery afterwards). Staying
 * leaves the draft and the selection as they were.
 */
export function useDraftGuard({ dirty, saving, confirm, bypass }: DraftGuardParams) {
  const { t } = useTranslation()
  const active = dirty || saving
  const activeRef = useRef(active)
  const savingRef = useRef(saving)

  useLayoutEffect(() => {
    activeRef.current = active
    savingRef.current = saving
  }, [active, saving])

  function ask(onDiscard: () => void, onStay?: () => void) {
    confirm({
      title: t('common.unsavedChanges.title'),
      message: t(savingRef.current ? 'common.unsavedChanges.messageSaving' : 'common.unsavedChanges.message'),
      confirmText: t('common.unsavedChanges.discard'),
      cancelText: t('common.unsavedChanges.keepEditing'),
      isDangerous: true,
      onConfirm: () => allowNavigation(bypass, onDiscard),
      onCancel: () => onStay?.(),
    })
  }

  /** Run `action` now, or once the user has agreed to discard the draft. */
  function run(action: () => void) {
    if (activeRef.current) ask(action)
    else allowNavigation(bypass, action)
  }

  const blocker = useBlocker(() => activeRef.current && !bypass.current)
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    ask(() => blocker.proceed(), () => blocker.reset())
    // eslint-disable-next-line react-hooks/exhaustive-deps -- asking once per block
  }, [blocker.state])

  useEffect(() => {
    if (!active) return
    const onBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [active])

  return { run, active }
}
