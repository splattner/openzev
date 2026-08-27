import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter } from 'react-router-dom'
import { PageSkeleton } from '../src/components/PageSkeleton'
import { EmptyState } from '../src/components/EmptyState'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}))

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>

beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: (query: string) => ({
            matches: false,
            media: query,
            onchange: null,
            addListener: () => undefined,
            removeListener: () => undefined,
            addEventListener: () => undefined,
            removeEventListener: () => undefined,
            dispatchEvent: () => false,
        }),
    })
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
})

afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.clearAllMocks()
})

function wrap(children: React.ReactElement) {
    return createElement(MantineProvider, null, createElement(MemoryRouter, null, children))
}

function setReducedMotion(matches: boolean) {
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: (query: string) => ({
            matches,
            media: query,
            onchange: null,
            addListener: () => undefined,
            removeListener: () => undefined,
            addEventListener: () => undefined,
            removeEventListener: () => undefined,
            dispatchEvent: () => false,
        }),
    })
}

describe('PageSkeleton', () => {
    it('renders table variant with skeleton blocks and respects card wrapper', () => {
        act(() => {
            root.render(wrap(createElement(PageSkeleton, { variant: 'table' })))
        })
        const skeletons = container.querySelectorAll('.mantine-Skeleton-root, .skeleton-block')
        // table variant renders title skeleton + 5 row skeletons
        expect(skeletons.length).toBeGreaterThanOrEqual(6)
        const card = container.querySelector('.card')
        expect(card).toBeTruthy()
    })

    it('renders tableRows without outer .card', () => {
        act(() => {
            root.render(wrap(createElement(PageSkeleton, { variant: 'tableRows' })))
        })
        const skeletons = container.querySelectorAll('.mantine-Skeleton-root, .skeleton-block')
        // tableRows has no title block: 5 row skeletons
        expect(skeletons.length).toBe(5)
        expect(container.querySelector('.card')).toBeFalsy()
    })

    it('renders kpiRow with 4 stat-cards, each with 2 or 3 blocks', () => {
        act(() => {
            root.render(wrap(createElement(PageSkeleton, { variant: 'kpiRow' })))
        })
        const statCards = container.querySelectorAll('.stat-card')
        expect(statCards.length).toBe(4)
        // kpiRow uses withHint=true → 3 blocks per card
        expect(statCards[0]?.querySelectorAll('.mantine-Skeleton-root, .skeleton-block').length).toBe(3)
    })

    it('renders cardList with 3 cards in participant-card-list wrapper', () => {
        act(() => {
            root.render(wrap(createElement(PageSkeleton, { variant: 'cardList' })))
        })
        const list = container.querySelector('.participant-card-list')
        expect(list).toBeTruthy()
        // 3 cards × 4 blocks each
        expect(list?.querySelectorAll('.card').length).toBe(3)
        expect(
            container.querySelectorAll('.mantine-Skeleton-root, .skeleton-block').length,
        ).toBe(12)
    })

    it('renders card variant with 4 blocks in a single .card', () => {
        act(() => {
            root.render(wrap(createElement(PageSkeleton, { variant: 'card' })))
        })
        expect(container.querySelectorAll('.card').length).toBe(1)
        expect(container.querySelectorAll('.mantine-Skeleton-root, .skeleton-block').length).toBe(4)
    })

    it('renders page variant with eyebrow + title + kpiRow + 2 cards', () => {
        act(() => {
            root.render(wrap(createElement(PageSkeleton, { variant: 'page' })))
        })
        // page-stack container
        expect(container.querySelector('.page-stack')).toBeTruthy()
        // kpiRow + 2 trailing CardSkeleton
        expect(container.querySelectorAll('.kpi-row').length).toBe(1)
        expect(container.querySelectorAll('.card').length).toBe(2)
        // 3 (eyebrow+title+description) + 4×2 (kpiRow noHint) + 3×2 (cards) = 17
        expect(
            container.querySelectorAll('.mantine-Skeleton-root, .skeleton-block').length,
        ).toBe(17)
    })

    it('disables animation when prefers-reduced-motion matches', () => {
        setReducedMotion(true)
        act(() => {
            root.render(wrap(createElement(PageSkeleton, { variant: 'table' })))
        })
        const skeleton = container.querySelector('.mantine-Skeleton-root')
        // Mantine Skeleton accepts animate prop; with animate={false} the
        // internal data-animate attribute is omitted or set to false.
        expect(skeleton?.getAttribute('data-animate')).not.toBe('true')
    })
})

describe('EmptyState', () => {
    it('renders title/description and actions as link vs button with aria-labelledby', () => {
        const onClick = vi.fn()
        act(() => {
            root.render(
                wrap(
                    createElement(EmptyState, {
                        titleKey: 'pages.zevs.emptyState.title',
                        descriptionKey: 'pages.zevs.emptyState.description',
                        actions: [
                            { labelKey: 'pages.zevs.emptyState.createAction', onClick, variant: 'primary' },
                            { labelKey: 'pages.participants.emptyState.meteringPointsAction', to: '/metering-points', variant: 'secondary' },
                        ],
                    }),
                ),
            )
        })
        const section = container.querySelector('section.empty-state')
        expect(section).toBeTruthy()
        const titleId = section?.getAttribute('aria-labelledby')
        expect(titleId).toBeTruthy()
        const title = titleId ? container.querySelector(`#${CSS.escape(titleId)}`) : null
        expect(title?.textContent).toBe('pages.zevs.emptyState.title')
        expect(container.textContent).toContain('pages.zevs.emptyState.description')
        const link = container.querySelector('a[href="/metering-points"]')
        expect(link).toBeTruthy()
        expect(link?.textContent).toContain('pages.participants.emptyState.meteringPointsAction')
        const button = container.querySelector('button.button-primary')
        expect(button).toBeTruthy()
        expect(button?.textContent).toContain('pages.zevs.emptyState.createAction')
        act(() => {
            button?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        expect(onClick).toHaveBeenCalledTimes(1)
    })

    it('links description via aria-describedby', () => {
        act(() => {
            root.render(
                wrap(
                    createElement(EmptyState, {
                        titleKey: 'pages.zevs.emptyState.title',
                        descriptionKey: 'pages.zevs.emptyState.description',
                    }),
                ),
            )
        })
        const section = container.querySelector('section.empty-state')
        const descId = section?.getAttribute('aria-describedby')
        expect(descId).toBeTruthy()
        const desc = descId ? container.querySelector(`#${CSS.escape(descId)}`) : null
        expect(desc?.tagName).toBe('P')
        expect(desc?.textContent).toBe('pages.zevs.emptyState.description')
    })

    it('renders no actions row when actions is empty or omitted', () => {
        act(() => {
            root.render(
                wrap(
                    createElement(EmptyState, {
                        titleKey: 'pages.zevs.emptyState.title',
                        descriptionKey: 'pages.zevs.emptyState.description',
                        actions: [],
                    }),
                ),
            )
        })
        expect(container.querySelector('.actions-row')).toBeFalsy()
    })
})
