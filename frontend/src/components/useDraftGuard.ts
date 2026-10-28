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
  /**
   * The open form has unsaved changes. A function is read at the moment of
   * asking, for forms whose state lives in the DOM rather than in React.
   */
  dirty: boolean | (() => boolean)
  /** A save is in flight: leaving does not stop it. */
  saving?: boolean
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
 * The guard without the router: asks before an action in the pane or dialog
 * (`run`) drops unsaved input, and lets the browser warn on a reload or closed
 * tab (`beforeunload`, its own prompt, no recovery afterwards).
 */
export function useDraftConfirm({ dirty, saving = false, confirm, bypass }: DraftGuardParams) {
  const { t } = useTranslation()
  const dirtyRef = useRef(dirty)
  const savingRef = useRef(saving)

  useLayoutEffect(() => {
    dirtyRef.current = dirty
    savingRef.current = saving
  }, [dirty, saving])

  function isActive() {
    const current = dirtyRef.current
    return (typeof current === 'function' ? current() : current) || savingRef.current
  }

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
    if (isActive()) ask(action)
    else allowNavigation(bypass, action)
  }

  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => { if (isActive()) event.preventDefault() }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [])

  return { run, ask, isActive }
}

/** The router half: browser Back/Forward and links elsewhere in the app. Needs a data router. */
export function useRouterDraftBlock({ ask, isActive, bypass }: {
  ask: ReturnType<typeof useDraftConfirm>['ask']
  isActive: () => boolean
  bypass: RefObject<boolean>
}) {
  const blocker = useBlocker(() => isActive() && !bypass.current)
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    ask(() => blocker.proceed(), () => blocker.reset())
    // eslint-disable-next-line react-hooks/exhaustive-deps -- asking once per block
  }, [blocker.state])
}

/**
 * Asks before unsaved input is dropped (SPEC-2026-10-ui-patterns §6.1, §6.2):
 * by an action in the pane (`run`), by browser Back/Forward or a link elsewhere
 * in the app (the router blocker), and by a reload or closed tab
 * (`beforeunload`). Staying leaves the draft and the selection as they were.
 */
export function useDraftGuard(params: DraftGuardParams) {
  const confirmed = useDraftConfirm(params)
  useRouterDraftBlock({ ask: confirmed.ask, isActive: confirmed.isActive, bypass: params.bypass })
  return { run: confirmed.run }
}
