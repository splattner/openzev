import { act, createElement, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

const queryState = vi.hoisted(() => ({
    current: {
        data: {
            subject: 'Global subject',
            body: 'Global body',
            fields: [{
                group_key: 'invoiceEmail',
                group_title_key: null,
                fields: [{
                    variable: '{invoice_number}',
                    description_key: 'admin.emailTemplates.fields.invoiceNumber',
                    example: 'INV-1',
                }],
            }],
        },
    } as { data?: unknown; isError?: boolean },
}))
vi.mock('@tanstack/react-query', () => ({
    useQuery: () => queryState.current,
}))

import { ZevEmailTemplateFields } from '../src/components/ZevEmailTemplateFields'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

function Harness() {
    const [subject, setSubject] = useState('Subject')
    const [body, setBody] = useState('Body')
    return createElement(ZevEmailTemplateFields, {
        subjectTemplate: subject,
        bodyTemplate: body,
        onSubjectTemplateChange: setSubject,
        onBodyTemplateChange: setBody,
    })
}

describe('ZEV email template field insertion', () => {
    it('makes the scrollable field reference keyboard focusable', () => {
        const container = document.createElement('div')
        document.body.append(container)
        const root = createRoot(container)
        try {
            act(() => root.render(createElement(Harness)))
            expect(container.querySelector('aside')?.tabIndex).toBe(0)
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })

    it('inserts into the last focused subject when a field button takes focus', () => {
        const container = document.createElement('div')
        document.body.append(container)
        const root = createRoot(container)
        try {
            act(() => root.render(createElement(Harness)))
            const subject = container.querySelector<HTMLInputElement>('input')!
            const body = container.querySelector<HTMLTextAreaElement>('textarea')!
            const token = Array.from(container.querySelectorAll<HTMLButtonElement>('.field-reference-token'))
                .find((button) => button.textContent === '{invoice_number}')!
            expect(container.textContent).toContain('INV-1')

            subject.focus()
            subject.setSelectionRange(2, 2)
            const mouseDown = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
            act(() => { token.dispatchEvent(mouseDown) })
            expect(mouseDown.defaultPrevented).toBe(true)

            token.focus()
            act(() => token.click())
            expect(subject.value).toBe('Su{invoice_number}bject')
            expect(subject.selectionStart).toBe(2 + '{invoice_number}'.length)
            expect(body.value).toBe('Body')
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })

    it('shows a loading state instead of the field reference while the catalog loads', () => {
        const previous = queryState.current
        queryState.current = {}
        const container = document.createElement('div')
        document.body.append(container)
        const root = createRoot(container)
        try {
            act(() => root.render(createElement(Harness)))
            expect(container.querySelector('aside')).toBeNull()
            expect(container.textContent).toContain('common.loading')
        } finally {
            act(() => root.unmount())
            container.remove()
            queryState.current = previous
        }
    })

    it('shows an error banner instead of the empty-search message when the request fails', () => {
        const previous = queryState.current
        queryState.current = { isError: true }
        const container = document.createElement('div')
        document.body.append(container)
        const root = createRoot(container)
        try {
            act(() => root.render(createElement(Harness)))
            expect(container.querySelector('aside')).toBeNull()
            expect(container.textContent).toContain('common.error')
            expect(container.textContent).not.toContain('admin.noMatchingFields')
        } finally {
            act(() => root.unmount())
            container.remove()
            queryState.current = previous
        }
    })
})
