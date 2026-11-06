import { useEffect, useRef, type RefObject } from 'react'
import { useLocation, useNavigationType } from 'react-router-dom'

/**
 * After a pathname change, focus the new page's h1 (else `main`) — unless
 * focus is still inside the page or an open dialog, or the change is a
 * redirect while loading: a REPLACE before any user input or other
 * navigation (`/` → `/me/documents`). Navigations
 * run as transitions, so a lazy page's h1 is present when this runs.
 * Contract: SPEC-2026-04 §7.1.
 */
export function useRouteFocus(mainRef: RefObject<HTMLElement | null>) {
    const { pathname } = useLocation()
    const navigationType = useNavigationType()
    const lastPathname = useRef(pathname)
    const hasUserInput = useRef(false)
    const hasNavigated = useRef(false)

    useEffect(() => {
        const markInput = () => { hasUserInput.current = true }
        document.addEventListener('pointerdown', markInput, true)
        document.addEventListener('keydown', markInput, true)
        return () => {
            document.removeEventListener('pointerdown', markInput, true)
            document.removeEventListener('keydown', markInput, true)
        }
    }, [])

    useEffect(() => {
        if (lastPathname.current === pathname) return
        lastPathname.current = pathname
        if (navigationType === 'REPLACE' && !hasUserInput.current && !hasNavigated.current) return
        hasNavigated.current = true
        const main = mainRef.current
        if (!main) return
        const active = document.activeElement
        if (active && active !== document.body && active !== main && active.isConnected && main.contains(active)) return
        if (active?.closest('dialog, [role="dialog"], [role="alertdialog"], [aria-modal="true"]')) return
        const heading = main.querySelector<HTMLElement>('h1')
        ;(heading ?? main).focus()
    }, [pathname, navigationType, mainRef])
}
