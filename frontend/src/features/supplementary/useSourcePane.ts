import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { allowNavigation, useDraftGuard } from '../../components/useDraftGuard'
import { useMinWidth } from '../../lib/useMinWidth'
import type { SupplementarySource } from '../../types/api'

const SOURCE_PARAM = 'source'

/** Marks the history entry that opening a source added, so X can take it back instead of leaving a Back step. */
const PANE_STATE = { sourcePane: true }

/** The source the URL asks to be open (the page checks that the user may see it). */
export function useSelectedSourceId(): string | null {
    const [searchParams] = useSearchParams()
    return searchParams.get(SOURCE_PARAM)
}

interface Options {
    /** The id from `useSelectedSourceId`. */
    selectedSourceId: string | null
    /** A source is actually shown: the id names one the user may see. */
    paneOpen: boolean
    /** Content width (rem) from which the list and the pane sit side by side; below it the pane takes the area. */
    splitMinRem: number
    confirm: Parameters<typeof useDraftGuard>[0]['confirm']
}

/**
 * The source pane beside its list (SPEC-2026-10-ui-patterns §6.2), for any page that lists sources: the open source
 * is `?source=<id>` (a reload, Back or a link reopens it; opening from the list adds one history step, switching
 * replaces it, X takes it back), focus moves to the pane's title when it opens and back to the control that opened it
 * (`data-source-open`) when it closes, the list comes back where it was scrolled, and a draft in the pane (a typed
 * key) is asked about before the pane lets go of it.
 */
export function useSourcePane({ splitMinRem, confirm, selectedSourceId, paneOpen }: Options) {
    const [, setSearchParams] = useSearchParams()
    const location = useLocation()
    const navigate = useNavigate()
    const [splitRef, fitsTwoPanes] = useMinWidth<HTMLDivElement>(splitMinRem)
    const paneTitleRef = useRef<HTMLHeadingElement>(null)
    const focusRequest = useRef<{ kind: 'pane' } | { kind: 'control'; id: string } | null>(null)
    const listScroll = useRef<number | null>(null)
    const bypassGuard = useRef(false)
    const [paneDirty, setPaneDirty] = useState(false)
    const guard = useDraftGuard({ dirty: paneDirty, confirm, bypass: bypassGuard })

    /** The pane shows `source`; `open` says whether there is one to show (the caller decides who may see which). */
    function openSource(source: Pick<SupplementarySource, 'id'>) {
        if (source.id === selectedSourceId) return
        const fromList = !selectedSourceId
        guard.run(() => {
            if (fromList) {
                focusRequest.current = { kind: 'pane' }
                if (!fitsTwoPanes) listScroll.current = window.scrollY
            }
            allowNavigation(bypassGuard, () => setSearchParams((previous) => {
                const next = new URLSearchParams(previous)
                next.set(SOURCE_PARAM, source.id)
                return next
            }, { replace: !fromList, state: fromList ? PANE_STATE : location.state }))
        })
    }

    // X takes back the step opening added; a pane reached by a link has no step of ours behind it.
    function closePane() {
        guard.run(() => {
            if (selectedSourceId) focusRequest.current = { kind: 'control', id: selectedSourceId }
            if (location.state?.sourcePane) {
                navigate(-1)
                return
            }
            setSearchParams((previous) => {
                const next = new URLSearchParams(previous)
                next.delete(SOURCE_PARAM)
                return next
            }, { replace: true })
        })
    }

    const listHidden = paneOpen && !fitsTwoPanes

    useEffect(() => {
        const request = focusRequest.current
        if (!request) return
        if (request.kind === 'pane' && paneOpen) {
            // Beside the list the pane is already in view; only one that replaces it needs scrolling to.
            paneTitleRef.current?.focus({ preventScroll: fitsTwoPanes })
        } else if (request.kind === 'control' && !paneOpen) {
            document.querySelector<HTMLElement>(`[data-source-open="${CSS.escape(request.id)}"]`)?.focus()
        } else {
            return
        }
        focusRequest.current = null
    }, [paneOpen, fitsTwoPanes])

    // The list comes back where the user left it.
    useLayoutEffect(() => {
        if (!listHidden && listScroll.current !== null) {
            window.scrollTo(0, listScroll.current)
            listScroll.current = null
        }
    }, [listHidden])

    return { splitRef, fitsTwoPanes, listHidden, paneTitleRef, setPaneDirty, openSource, closePane }
}
