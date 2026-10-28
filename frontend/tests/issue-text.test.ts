import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueText, type IssueTextProps } from '../src/components/IssueText'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>

beforeEach(() => {
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
})

afterEach(() => {
    act(() => root.unmount())
    container.remove()
})

function render(props: Omit<IssueTextProps, 'children'>) {
    act(() => root.render(createElement(MemoryRouter, null, createElement(IssueText, props, 'No metering point'))))
    return container.querySelector('.issue-text') as HTMLElement
}

describe('IssueText', () => {
    it('is plain coloured text for a user who cannot fix it', () => {
        const issue = render({})
        expect(issue.tagName).toBe('SPAN')
        expect(issue.textContent).toBe('No metering point')
        expect(issue.classList.contains('issue-text--error')).toBe(true)
        expect(issue.classList.contains('badge')).toBe(false)
    })

    it('is a real link to the fix when there is a destination', () => {
        const issue = render({ to: '/metering/points' })
        expect(issue.tagName).toBe('A')
        expect(issue.getAttribute('href')).toBe('/metering/points')
    })

    it('is a button when the fix is an action on the page', () => {
        const onClick = vi.fn()
        const issue = render({ onClick, tone: 'warning' })
        expect(issue.tagName).toBe('BUTTON')
        expect(issue.classList.contains('issue-text--warning')).toBe(true)
        act(() => issue.click())
        expect(onClick).toHaveBeenCalledOnce()
    })

    it('keeps the icon out of the accessibility tree', () => {
        expect(render({}).querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
    })
})
