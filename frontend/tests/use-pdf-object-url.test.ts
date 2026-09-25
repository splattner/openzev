import { act, createElement, useEffect } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePdfObjectUrl } from '../src/lib/usePdfObjectUrl'
import { deferred, flush, pdfBlob } from './pdf-test-utils'

type Fetcher = (signal: AbortSignal) => Promise<Blob>
type HookState = ReturnType<typeof usePdfObjectUrl>

type HookHarnessProps = {
  fetcher: Fetcher | null
  enabled: boolean
}

let root: Root
let container: HTMLDivElement
let objectUrlCount: number
let rootUnmounted: boolean
// The harness also records the live result: JSON cannot prove Blob identity.
const liveResultRef: { current: HookState | null } = { current: null }

function Harness({ fetcher, enabled }: HookHarnessProps) {
    const state = usePdfObjectUrl(fetcher, enabled)
    const { url, loading, error } = state
    useEffect(() => {
        liveResultRef.current = state
    })
    return createElement('output', { 'data-testid': 'hook-state' }, JSON.stringify({ url, loading, error }))
}

function readState(container: HTMLElement): HookState {
    return JSON.parse(container.querySelector('[data-testid="hook-state"]')?.textContent ?? '{}') as HookState
}

function renderHook(props: HookHarnessProps) {
    root.render(createElement(Harness, props))
}

describe('usePdfObjectUrl', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
        objectUrlCount = 0
        rootUnmounted = false
        liveResultRef.current = null
        container = document.createElement('div')
        document.body.appendChild(container)
        root = createRoot(container)

        vi.spyOn(URL, 'createObjectURL').mockImplementation(() => `blob:pdf-${++objectUrlCount}`)
        vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    })

    afterEach(() => {
        if (!rootUnmounted) act(() => root.unmount())
        container.remove()
        vi.restoreAllMocks()
    })

    it('loads a PDF and exposes its object URL', async () => {
        const fetcher = vi.fn().mockResolvedValue(pdfBlob())
        act(() => renderHook({ fetcher, enabled: true }))

        expect(readState(container)).toEqual({ url: null, loading: true, error: false })
        expect(URL.createObjectURL).not.toHaveBeenCalled()

        await flush()

        expect(readState(container)).toEqual({ url: 'blob:pdf-1', loading: false, error: false })
        expect(URL.createObjectURL).toHaveBeenCalledOnce()
    })

    it('clears and revokes the old URL before a failing replacement finishes', async () => {
        const first = vi.fn().mockResolvedValue(pdfBlob())
        const second = deferred<Blob>()
        const secondFetcher = vi.fn(() => second.promise)

        act(() => renderHook({ fetcher: first, enabled: true }))
        await flush()
        expect(readState(container).url).toBe('blob:pdf-1')

        act(() => renderHook({ fetcher: secondFetcher, enabled: true }))

        expect(readState(container)).toEqual({ url: null, loading: true, error: false })
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:pdf-1')

        await act(async () => {
            second.reject(new Error('render failed'))
            await second.promise.catch(() => undefined)
        })
        await flush()

        expect(readState(container)).toEqual({ url: null, loading: false, error: true })
        expect(URL.createObjectURL).toHaveBeenCalledOnce()
    })

    it('ignores an older request that completes after its replacement', async () => {
        const first = deferred<Blob>()
        const second = deferred<Blob>()
        const firstFetcher = vi.fn(() => first.promise)
        const secondFetcher = vi.fn(() => second.promise)

        act(() => renderHook({ fetcher: firstFetcher, enabled: true }))
        act(() => renderHook({ fetcher: secondFetcher, enabled: true }))

        await act(async () => {
            first.resolve(pdfBlob())
            await first.promise
        })
        await flush()

        expect(readState(container)).toEqual({ url: null, loading: true, error: false })
        expect(URL.createObjectURL).not.toHaveBeenCalled()

        await act(async () => {
            second.resolve(pdfBlob())
            await second.promise
        })
        await flush()

        expect(readState(container)).toEqual({ url: 'blob:pdf-1', loading: false, error: false })
        expect(URL.createObjectURL).toHaveBeenCalledOnce()
    })

    it('becomes fully idle when disabled and fetches again when re-enabled', async () => {
        const first = deferred<Blob>()
        const second = deferred<Blob>()
        const fetcher = vi.fn()
            .mockReturnValueOnce(first.promise)
            .mockReturnValueOnce(second.promise)

        act(() => renderHook({ fetcher, enabled: true }))
        act(() => renderHook({ fetcher, enabled: false }))

        expect(readState(container)).toEqual({ url: null, loading: false, error: false })

        await act(async () => {
            first.resolve(pdfBlob())
            await first.promise
        })
        await flush()
        expect(URL.createObjectURL).not.toHaveBeenCalled()

        act(() => renderHook({ fetcher, enabled: true }))
        expect(readState(container)).toEqual({ url: null, loading: true, error: false })
        expect(fetcher).toHaveBeenCalledTimes(2)

        await act(async () => {
            second.resolve(pdfBlob())
            await second.promise
        })
        await flush()
        expect(readState(container)).toEqual({ url: 'blob:pdf-1', loading: false, error: false })
    })

    it('clears an error when disabled', async () => {
        const fetcher = vi.fn().mockRejectedValue(new Error('render failed'))
        act(() => renderHook({ fetcher, enabled: true }))
        await flush()
        expect(readState(container)).toEqual({ url: null, loading: false, error: true })

        act(() => renderHook({ fetcher, enabled: false }))
        expect(readState(container)).toEqual({ url: null, loading: false, error: false })
    })

    it('revokes the active object URL on unmount', async () => {
        const fetcher = vi.fn().mockResolvedValue(pdfBlob())
        act(() => renderHook({ fetcher, enabled: true }))
        await flush()
        expect(readState(container).url).toBe('blob:pdf-1')

        act(() => root.unmount())
        rootUnmounted = true
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:pdf-1')
    })

    it('aborts the superseded request instead of merely ignoring it', async () => {
        const first = deferred<Blob>()
        const seenSignals: AbortSignal[] = []
        const firstFetcher = vi.fn((signal: AbortSignal) => {
            seenSignals.push(signal)
            return first.promise
        })
        const secondFetcher = vi.fn().mockResolvedValue(pdfBlob())

        act(() => renderHook({ fetcher: firstFetcher, enabled: true }))
        act(() => renderHook({ fetcher: secondFetcher, enabled: true }))

        expect(seenSignals).toHaveLength(1)
        expect(seenSignals[0].aborted).toBe(true)

        await act(async () => {
            first.resolve(pdfBlob())
            await first.promise
        })
        await flush()

        expect(readState(container)).toEqual({ url: 'blob:pdf-1', loading: false, error: false })
        expect(URL.createObjectURL).toHaveBeenCalledOnce()
    })

    it('treats an aborted request as a cancellation, not a failure', async () => {
        const gate = deferred<Blob>()
        const fetcher = vi.fn((signal: AbortSignal) => {
            signal.addEventListener('abort', () => gate.reject(new DOMException('Aborted', 'AbortError')))
            return gate.promise
        })

        act(() => renderHook({ fetcher, enabled: true }))
        act(() => renderHook({ fetcher, enabled: false }))

        await flush()
        expect(readState(container)).toEqual({ url: null, loading: false, error: false })
        expect(URL.createObjectURL).not.toHaveBeenCalled()
    })

    it('rejects a declared non-PDF type but accepts an empty one', async () => {
        const htmlFetcher = vi.fn().mockResolvedValue(pdfBlob('text/html'))
        act(() => renderHook({ fetcher: htmlFetcher, enabled: true }))
        await flush()
        expect(readState(container)).toEqual({ url: null, loading: false, error: true })
        expect(URL.createObjectURL).not.toHaveBeenCalled()

        const emptyTypeFetcher = vi.fn().mockResolvedValue(pdfBlob(''))
        act(() => renderHook({ fetcher: emptyTypeFetcher, enabled: true }))
        await flush()
        expect(readState(container)).toEqual({ url: 'blob:pdf-1', loading: false, error: false })
    })

    it('returns the exact Blob reference with its URL and clears it on every non-ready state', async () => {
        const blob = pdfBlob()
        const fetcher = vi.fn().mockResolvedValue(blob)
        act(() => renderHook({ fetcher, enabled: true }))
        await flush()

        expect(liveResultRef.current?.blob).toBe(blob)
        expect(liveResultRef.current?.url).toBe('blob:pdf-1')

        const gate = deferred<Blob>()
        const replacement = vi.fn(() => gate.promise)
        act(() => renderHook({ fetcher: replacement, enabled: true }))
        expect(liveResultRef.current?.blob).toBeNull()
        expect(liveResultRef.current?.url).toBeNull()
        expect(readState(container)).toEqual({ url: null, loading: true, error: false })

        await act(async () => {
            gate.reject(new Error('render failed'))
            await gate.promise.catch(() => undefined)
        })
        await flush()
        expect(liveResultRef.current?.blob).toBeNull()
        expect(readState(container)).toEqual({ url: null, loading: false, error: true })

        act(() => renderHook({ fetcher: replacement, enabled: false }))
        expect(liveResultRef.current?.blob).toBeNull()
        expect(readState(container)).toEqual({ url: null, loading: false, error: false })
    })
})
