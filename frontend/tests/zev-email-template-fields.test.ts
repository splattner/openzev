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

function Harness({ initialSubject = 'Subject', initialBody = 'Body', savedSubject, savedBody, readOnly = false }: {
    initialSubject?: string
    initialBody?: string
    savedSubject?: string
    savedBody?: string
    readOnly?: boolean
} = {}) {
    const [subject, setSubject] = useState(initialSubject)
    const [body, setBody] = useState(initialBody)
    return createElement(ZevEmailTemplateFields, {
        subjectTemplate: subject,
        bodyTemplate: body,
        savedSubjectTemplate: savedSubject ?? initialSubject,
        savedBodyTemplate: savedBody ?? initialBody,
        onSubjectTemplateChange: setSubject,
        onBodyTemplateChange: setBody,
        readOnly,
    })
}

function renderHarness(props?: { initialSubject?: string; initialBody?: string; savedSubject?: string; savedBody?: string; readOnly?: boolean }) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    act(() => root.render(createElement(Harness, props)))
    return { container, root }
}

function openFieldReference(container: ParentNode) {
    const toggle = Array.from(container.querySelectorAll('button'))
        .find((button) => button.textContent === 'pages.zevSettings.emailInsertField')!
    act(() => { toggle.click() })
}

describe('ZEV email template field insertion', () => {
    it.each(['subject', 'body'] as const)('keeps an inherited %s editor focused when cleared', (field) => {
        const { container, root } = renderHarness({ initialSubject: '', initialBody: '' })
        try {
            const label = field === 'subject' ? 'emailCustomizeSubject' : 'emailCustomizeBody'
            act(() => container.querySelector<HTMLButtonElement>(`button[aria-label="pages.zevSettings.${label}"]`)!.click())
            const selector = `[data-zev-field="email_${field}_template"] ${field === 'subject' ? 'input' : 'textarea'}`
            const editor = container.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector)!
            editor.focus()
            const prototype = field === 'subject' ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype
            act(() => {
                Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(editor, '')
                editor.dispatchEvent(new Event('input', { bubbles: true }))
            })
            expect(container.querySelector(selector)).toBe(editor)
            expect(document.activeElement).toBe(editor)
            act(() => {
                Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(editor, 'Replacement')
                editor.dispatchEvent(new Event('input', { bubbles: true }))
            })
            expect(editor.value).toBe('Replacement')
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })

    it('says what saving will do for only the cleared field, without repeating the unsaved state', () => {
        const { container, root } = renderHarness({ initialSubject: 'Custom subject', initialBody: 'Custom body' })
        try {
            act(() => {
                container.querySelector<HTMLButtonElement>(
                    'button[aria-label="pages.zevSettings.emailResetSubject"]',
                )!.click()
            })
            const subject = container.querySelector('[data-zev-field="email_subject_template"]')!
            const body = container.querySelector('[data-zev-field="email_body_template"]')!
            expect(subject.textContent).toContain('templates.source.zev')
            // The save bar already carries "unsaved changes"; the field only adds what saving does.
            expect(subject.textContent).not.toContain('templates.source.unsavedChanges')
            expect(subject.textContent).toContain('pages.zevSettings.emailInheritanceOnSave')
            expect(body.textContent).toContain('templates.source.zev')
            expect(body.textContent).not.toContain('pages.zevSettings.emailInheritanceOnSave')
            expect(container.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe('Custom body')
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })

    it('collapses the field reference behind Insert field but keeps it focusable', () => {
        const container = document.createElement('div')
        document.body.append(container)
        const root = createRoot(container)
        try {
            act(() => root.render(createElement(Harness)))
            expect(container.querySelector('aside')).toBeNull()
            openFieldReference(container)
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
            openFieldReference(container)
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
            expect(container.querySelector('.error-banner')).not.toBeNull()
            expect(container.textContent).not.toContain('admin.noMatchingFields')
        } finally {
            act(() => root.unmount())
            container.remove()
            queryState.current = previous
        }
    })

    it('keeps default fields editable when the platform template cannot load', () => {
        const previous = queryState.current
        queryState.current = { isError: true }
        const { container, root } = renderHarness({ initialSubject: '', initialBody: '' })
        try {
            expect(container.querySelectorAll('.error-banner')).toHaveLength(1)
            expect(container.textContent?.match(/common.error/g)).toHaveLength(1)
            const customize = container.querySelector<HTMLButtonElement>(
                'button[aria-label="pages.zevSettings.emailCustomizeSubject"]',
            )!
            expect(customize.disabled).toBe(false)
            act(() => customize.click())
            expect(container.querySelector<HTMLInputElement>('[data-zev-field="email_subject_template"] input')?.value).toBe('')
        } finally {
            act(() => root.unmount())
            container.remove()
            queryState.current = previous
        }
    })

    it('starts the default body when a token is clicked without an editor focus', () => {
        const { container, root } = renderHarness({ initialSubject: 'Custom subject', initialBody: '' })
        try {
            openFieldReference(container)
            const token = Array.from(container.querySelectorAll<HTMLButtonElement>('.field-reference-token'))
                .find((button) => button.textContent === '{invoice_number}')!
            act(() => token.click())
            expect(container.querySelector<HTMLTextAreaElement>('[data-zev-field="email_body_template"] textarea')?.value)
                .toBe('Global body\n{invoice_number}')
            expect(container.querySelector<HTMLInputElement>('[data-zev-field="email_subject_template"] input')?.value)
                .toBe('Custom subject')
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })

    it('shows the platform text with Customize while on the default', () => {
        const { container, root } = renderHarness({ initialSubject: '', initialBody: 'Custom body' })
        try {
            const badges = Array.from(container.querySelectorAll('.badge')).map((badge) => badge.textContent)
            expect(badges).toContain('templates.source.platform')
            expect(badges).toContain('templates.source.zev')
            // Default subject renders its platform text, not an editor.
            expect(container.querySelector('input')).toBeNull()
            expect(container.textContent).toContain('Global subject')
            expect(container.querySelector('button[aria-label="pages.zevSettings.emailResetSubject"]')).toBeNull()
            // Customize seeds the editor with the platform text for real editing.
            act(() => {
                container.querySelector('button[aria-label="pages.zevSettings.emailCustomizeSubject"]')!.click()
            })
            expect(container.querySelector<HTMLInputElement>('input')!.value).toBe('Global subject')
            // The body reset only stages the default; the editor unmounts.
            const bodyReset = container.querySelector('button[aria-label="pages.zevSettings.emailResetBody"]')!
            act(() => { bodyReset.click() })
            expect(container.querySelector('textarea')).toBeNull()
            expect(container.textContent).toContain('Global body')
            expect(container.querySelectorAll('.badge').length).toBe(2)
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })

    it('disables every control in read-only mode', () => {
        const { container, root } = renderHarness({ readOnly: true })
        try {
            expect(container.querySelector('input')!.disabled).toBe(true)
            expect(container.querySelector('textarea')!.disabled).toBe(true)
            expect(container.querySelector('button[aria-label="pages.zevSettings.emailResetSubject"]')).toBeNull()
            expect(container.querySelector('button[aria-label="pages.zevSettings.emailResetBody"]')).toBeNull()
            expect(container.querySelector('button[aria-label="pages.zevSettings.emailCustomizeSubject"]')).toBeNull()
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })

    it('shows default previews without actions in read-only mode', () => {
        const { container, root } = renderHarness({ initialSubject: '', initialBody: '', readOnly: true })
        try {
            expect(container.querySelector('input')).toBeNull()
            expect(container.querySelector('textarea')).toBeNull()
            expect(container.textContent).toContain('Global subject')
            expect(container.textContent).toContain('Global body')
            expect(container.querySelector('button[aria-label="pages.zevSettings.emailCustomizeSubject"]')).toBeNull()
            expect(container.querySelector('button[aria-label="pages.zevSettings.emailCustomizeBody"]')).toBeNull()
        } finally {
            act(() => root.unmount())
            container.remove()
        }
    })
})
