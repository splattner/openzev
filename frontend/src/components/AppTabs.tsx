import { Tabs, type TabsProps } from '@mantine/core'
import type { Ref } from 'react'

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
    return <Tabs ref={ref} classNames={merged} {...props} />
}

AppTabs.List = Tabs.List
AppTabs.Tab = Tabs.Tab
AppTabs.Panel = Tabs.Panel
