import { useCallback, useLayoutEffect, useRef } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

/**
 * URL edits shared by routed hubs and query controls. Callers own tab policy.
 * Each update starts from the last committed location: combine related edits
 * in one callback rather than issuing multiple updates before navigation commits.
 */
export function usePageNavigation() {
    const location = useLocation()
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const committedLocation = useRef(location)
    useLayoutEffect(() => { committedLocation.current = location }, [location])

    const updateParams = useCallback((
        edit: (params: URLSearchParams) => void,
        { pathname, replace = true, clearHash }: { pathname?: string; replace?: boolean; clearHash?: string } = {},
    ) => {
        const current = committedLocation.current
        const params = new URLSearchParams(current.search)
        edit(params)
        navigate({ pathname: pathname ?? current.pathname, search: params.toString(), hash: current.hash === clearHash ? '' : current.hash }, { replace, state: current.state })
    }, [navigate])

    const navigateTab = useCallback((pathname: string) => {
        updateParams(() => {}, { pathname })
    }, [updateParams])

    return { searchParams, updateParams, navigateTab }
}
