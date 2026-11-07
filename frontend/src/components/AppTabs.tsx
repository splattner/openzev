import { Tabs, type TabsProps } from '@mantine/core'
import { useCallback, useEffect, useRef, type Ref } from 'react'

const APP_TABS_CLASSES: Record<string, string> = {
    root: 'app-tabs',
    list: 'app-tabs-list',
    tab: 'app-tabs-tab',
    panel: 'app-tabs-panel',
}

type ExtraClassNames = Partial<Record<string, string>>

/** The shared classes first, a caller's own after them, none dropped. */
function mergeClassNames(extra: ExtraClassNames | undefined): Record<string, string> {
    const merged = { ...APP_TABS_CLASSES }
    for (const [name, value] of Object.entries(extra ?? {})) {
        if (value) merged[name] = [APP_TABS_CLASSES[name], value].filter(Boolean).join(' ')
    }
    return merged
}

/**
 * Mutually exclusive, document-like views (SPEC-2026-10-ui-patterns §7.4): the
 * Mantine `Tabs` with the app's class mapping applied once. Props, refs, keyboard
 * behaviour and the `List`/`Tab`/`Panel` parts are Mantine's; all panels sit under
 * this one root. Counted list filters are `FilterTabs`, not this.
 */
export function AppTabs({ classNames, ref, ...props }: TabsProps & { ref?: Ref<HTMLDivElement> }) {
    const merged = typeof classNames === 'function'
        ? ((...args: Parameters<typeof classNames>) => mergeClassNames(classNames(...args)))
        : mergeClassNames(classNames)
    const rootRef = useRef<HTMLDivElement | null>(null)
    const setRef = useCallback((node: HTMLDivElement | null) => {
        rootRef.current = node
        if (typeof ref === 'function') ref(node)
        else if (ref) ref.current = node
    }, [ref])
    // The strip scrolls instead of wrapping on a narrow screen: keep the active tab in view, also when a
    // tab is added after the first render (a feature switched on once its status is known).
    useEffect(() => {
        const list = rootRef.current?.querySelector('[role="tablist"]')
        if (!list) return
        const reveal = () => list.querySelector<HTMLElement>('[role="tab"][data-active]')?.scrollIntoView?.({ inline: 'nearest', block: 'nearest' })
        reveal()
        if (typeof MutationObserver === 'undefined') return
        const observer = new MutationObserver(reveal)
        observer.observe(list, { childList: true })
        return () => observer.disconnect()
    }, [props.value])
    return <Tabs ref={setRef} classNames={merged} {...props} />
}

AppTabs.List = Tabs.List
AppTabs.Tab = Tabs.Tab
AppTabs.Panel = Tabs.Panel
