import { act, createElement, useLayoutEffect, useReducer, useRef } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useDraftGuard } from '../src/components/useDraftGuard'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

// Unsaved input is asked about before it is dropped (SPEC-2026-10-ui-patterns §6.2).

type Options = Parameters<Parameters<typeof useDraftGuard>[0]['confirm']>[0]
let guard: ReturnType<typeof useDraftGuard>
let dirty: boolean
let saving: boolean
let asked: Options | null
let root: ReturnType<typeof createRoot>
let container: HTMLDivElement
let router: ReturnType<typeof createMemoryRouter>
let refresh: () => void

function Page() {
    const [, force] = useReducer((count: number) => count + 1, 0)
    const bypass = useRef(false)
    const current = useDraftGuard({ dirty, saving, bypass, confirm: options => { asked = options } })
    useLayoutEffect(() => { refresh = force; guard = current })
    return null
}

/** Mounts the page the first time; afterwards re-reads the test's `dirty` and `saving`. */
async function render() {
    if (refresh) await act(async () => refresh())
    else await act(async () => root.render(createElement(RouterProvider, { router })))
}

beforeEach(async () => {
    refresh = undefined as unknown as () => void
    dirty = false
    saving = false
    asked = null
    router = createMemoryRouter([{ path: '/', element: createElement(Page) }, { path: '/other', element: null }])
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
    await render()
})
afterEach(() => { act(() => root.unmount()); container.remove() })

it('runs an action straight away when there is nothing to lose', () => {
    const action = vi.fn()
    act(() => guard.run(action))
    expect(action).toHaveBeenCalledOnce()
    expect(asked).toBeNull()
})

it('asks first when the form is dirty, and keeps the draft when the user stays', async () => {
    dirty = true
    await render()
    const action = vi.fn()
    act(() => guard.run(action))
    expect(action).not.toHaveBeenCalled()
    expect(asked?.title).toBe('common.unsavedChanges.title')
    expect(asked?.message).toBe('common.unsavedChanges.message')
    act(() => asked?.onCancel())
    expect(action).not.toHaveBeenCalled()
})

it('runs the action once the user agrees to discard', async () => {
    dirty = true
    await render()
    const action = vi.fn()
    act(() => guard.run(action))
    act(() => asked?.onConfirm())
    expect(action).toHaveBeenCalledOnce()
})

it('says a save in flight may still complete', async () => {
    saving = true
    await render()
    act(() => guard.run(vi.fn()))
    expect(asked?.message).toBe('common.unsavedChanges.messageSaving')
})

it('blocks in-app navigation while dirty, and lets it through after a discard', async () => {
    dirty = true
    await render()
    await act(async () => { void router.navigate('/other') })
    expect(router.state.location.pathname).toBe('/')
    expect(asked).not.toBeNull()
    await act(async () => asked?.onConfirm())
    expect(router.state.location.pathname).toBe('/other')
})

it('stays put when the user keeps editing after a blocked navigation', async () => {
    dirty = true
    await render()
    await act(async () => { void router.navigate('/other') })
    await act(async () => asked?.onCancel())
    expect(router.state.location.pathname).toBe('/')
})

it('lets the browser warn on reload only while there is something to lose', async () => {
    const event = () => { const e = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented }
    expect(event()).toBe(false)
    dirty = true
    await render()
    expect(event()).toBe(true)
})
