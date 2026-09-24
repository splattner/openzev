import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TemplateField, TemplateFieldGroup } from '../types/api'

export interface FieldReferenceProps {
    groups: TemplateFieldGroup[]
    /** Template content for usage counts. */
    content?: string
    /** Insert a token; shift-click keeps the editor focused. */
    onInsert?: (variable: string, keepFocus: boolean) => void
}

type TemplateEditorElement = HTMLInputElement | HTMLTextAreaElement

export interface TemplateTokenInsertion {
    value: string
    selectionStart: number
    selectionEnd: number
    focus: boolean
}

/** Calculate a token insertion without mutating a controlled DOM value. */
export function insertTemplateToken(
    element: HTMLTextAreaElement | HTMLInputElement,
    variable: string,
    keepFocus: boolean,
): TemplateTokenInsertion {
    const start = element.selectionStart ?? element.value.length
    const end = element.selectionEnd ?? element.value.length
    let insertText = variable
    let cursorOffset = insertText.length
    if (variable.startsWith('{%') && variable.includes(' for ')) {
        insertText = `${variable}\n    \n{% endfor %}`
        cursorOffset = variable.length + '\n    '.length
    }
    const cursor = start + cursorOffset
    return {
        value: element.value.slice(0, start) + insertText + element.value.slice(end),
        selectionStart: keepFocus ? start : cursor,
        selectionEnd: keepFocus ? start : cursor,
        focus: !keepFocus,
    }
}

export function applyTemplateTokenSelection(
    element: TemplateEditorElement,
    insertion: TemplateTokenInsertion,
): void {
    if (insertion.focus) {
        element.focus()
    }
    element.setSelectionRange(insertion.selectionStart, insertion.selectionEnd)
}

type ElementRef<T extends TemplateEditorElement> = { current: T | null }

function usePendingTokenInsertion() {
    const pendingInsertionRef = useRef<{
        element: TemplateEditorElement
        insertion: TemplateTokenInsertion
    } | null>(null)

    useLayoutEffect(() => {
        const pending = pendingInsertionRef.current
        if (pending) {
            applyTemplateTokenSelection(pending.element, pending.insertion)
            pendingInsertionRef.current = null
        }
    })

    return pendingInsertionRef
}

/** Controlled-input insertion for the source textarea used by PDF editors. */
export function useTemplateTokenInsertionAtElement(
    elementRef: ElementRef<TemplateEditorElement>,
    onChange: (value: string) => void,
): (variable: string, keepFocus: boolean) => void {
    const pendingInsertionRef = usePendingTokenInsertion()

    return useCallback((variable: string, keepFocus: boolean) => {
        const element = elementRef.current
        if (!element) {
            return
        }
        const insertion = insertTemplateToken(element, variable, keepFocus)
        if (insertion.value === element.value) {
            applyTemplateTokenSelection(element, insertion)
            return
        }
        pendingInsertionRef.current = { element, insertion }
        onChange(insertion.value)
    }, [elementRef, onChange, pendingInsertionRef])
}

/** Insert into the subject/body that most recently owned the editor caret. */
export function useTemplateTokenInsertion(
    subjectRef: ElementRef<HTMLInputElement>,
    bodyRef: ElementRef<HTMLTextAreaElement>,
    lastFocusedRef: ElementRef<TemplateEditorElement>,
    onSubjectChange: (value: string) => void,
    onBodyChange: (value: string) => void,
): (variable: string, keepFocus: boolean) => void {
    const pendingInsertionRef = usePendingTokenInsertion()

    return useCallback((variable: string, keepFocus: boolean) => {
        const active = document.activeElement
        const target =
            active === subjectRef.current || active === bodyRef.current
                ? (active as TemplateEditorElement)
                : lastFocusedRef.current ?? bodyRef.current
        if (!target) {
            return
        }
        const insertion = insertTemplateToken(target, variable, keepFocus)
        if (insertion.value === target.value) {
            applyTemplateTokenSelection(target, insertion)
            return
        }
        pendingInsertionRef.current = { element: target, insertion }
        if (target === subjectRef.current) {
            onSubjectChange(insertion.value)
        } else {
            onBodyChange(insertion.value)
        }
    }, [bodyRef, lastFocusedRef, onBodyChange, onSubjectChange, pendingInsertionRef, subjectRef])
}

export function tokenInner(variable: string): string {
    const open = variable.startsWith('{{') || variable.startsWith('{%') ? 2 : 1
    const close = variable.endsWith('}}') || variable.endsWith('%}') ? 2 : 1
    return variable.slice(open, variable.length - close).trim()
}

function tokenKind(variable: string): 'output' | 'block' | 'email' {
    if (variable.startsWith('{{')) {
        return 'output'
    }
    if (variable.startsWith('{%')) {
        return 'block'
    }
    return 'email'
}

/** Normalize token braces, whitespace, and Django filters. */
export function tokenLookupKey(variable: string): string {
    return tokenInner(variable).split('|', 1)[0].replace(/\s+/g, '')
}

export function tokenMatchKey(variable: string): string {
    return `${tokenKind(variable)}:${tokenLookupKey(variable)}`
}

export type TemplateSyntax = 'django' | 'email'

export function catalogSyntax(groups: TemplateFieldGroup[]): TemplateSyntax {
    for (const group of groups) {
        for (const field of group.fields) {
            if (field.variable.startsWith('{{') || field.variable.startsWith('{%')) {
                return 'django'
            }
        }
    }
    return 'email'
}

export function extractTemplateTokens(content: string, syntax: TemplateSyntax): string[] {
    if (syntax === 'django') {
        return content.match(/\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\}/g) ?? []
    }
    return content.match(/\{[A-Za-z0-9_]+\}/g) ?? []
}

/** Usage counts for the rendered reference, keyed by catalog variable. */
export function countCatalogOccurrences(content: string, groups: TemplateFieldGroup[]): Map<string, number> {
    const occurrences = new Map<string, number>()
    for (const token of extractTemplateTokens(content, catalogSyntax(groups))) {
        const key = tokenMatchKey(token)
        occurrences.set(key, (occurrences.get(key) ?? 0) + 1)
    }
    const map = new Map<string, number>()
    for (const group of groups) {
        for (const field of group.fields) {
            map.set(field.variable, occurrences.get(tokenMatchKey(field.variable)) ?? 0)
        }
    }
    return map
}

function translationTokenKey(variable: string): string | null {
    const inner = tokenInner(variable)
    return inner.startsWith('tr.') ? inner.slice(3) : null
}

export function fieldDescription(
    t: (key: string, options?: Record<string, string>) => string,
    field: TemplateField,
): string {
    const key = translationTokenKey(field.variable)
    return key ? t(field.description_key, { key }) : t(field.description_key)
}

export function FieldReference({ groups, content, onInsert }: FieldReferenceProps) {
    const { t } = useTranslation()
    const [query, setQuery] = useState('')

    const visibleGroups = useMemo(() => {
        const needle = query.trim().toLowerCase()
        if (!needle) {
            return groups
        }
        return groups
            .map((group) => ({
                ...group,
                fields: group.fields.filter(
                    (field) =>
                        field.variable.toLowerCase().includes(needle) ||
                        fieldDescription(t, field).toLowerCase().includes(needle),
                ),
            }))
            .filter((group) => group.fields.length > 0)
    }, [groups, query, t])

    const counts = useMemo(() => {
        if (!content) {
            return null
        }
        return countCatalogOccurrences(content, groups)
    }, [groups, content])

    return (
        <aside
            className="field-reference card page-stack"
            aria-label={t('admin.fieldReference')}
            tabIndex={0}
        >
            <h4 className="field-reference__heading">{t('admin.availableFields')}</h4>
            <input
                type="search"
                className="field-reference__search"
                aria-label={t('admin.fieldSearchPlaceholder')}
                placeholder={t('admin.fieldSearchPlaceholder')}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
            />
            {visibleGroups.length === 0 && (
                <p className="muted field-reference__empty">{t('admin.noMatchingFields')}</p>
            )}
            {visibleGroups.map((group) => (
                <div key={group.group_key}>
                    {group.group_title_key && (
                        <h5 className="field-reference__group-heading">{t(group.group_title_key)}</h5>
                    )}
                    <table className="field-reference__table">
                        <tbody>
                            {group.fields.map((field) => {
                                const count = counts?.get(field.variable)
                                const isOutputToken = !field.variable.startsWith('{%')
                                return (
                                    <tr key={field.variable}>
                                        <td className="field-reference__variable">
                                            {onInsert ? (
                                                <button
                                                    type="button"
                                                    className="field-reference-token"
                                                    onMouseDown={(event) => {
                                                        // Preserve the editor caret until insertion.
                                                        event.preventDefault()
                                                    }}
                                                    onClick={(event) => onInsert(field.variable, event.shiftKey)}
                                                    title={t('admin.clickToInsert')}
                                                >
                                                    {field.variable}
                                                </button>
                                            ) : (
                                                field.variable
                                            )}
                                        </td>
                                        <td className="muted field-reference__description">
                                            <div>{fieldDescription(t, field)}</div>
                                            {isOutputToken && field.example && (
                                                <div className="field-reference__example">
                                                    {t('admin.example')}: {field.example}
                                                </div>
                                            )}
                                        </td>
                                        {counts && (
                                            <td className="field-reference__count">
                                                {count !== undefined && count > 0 && (
                                                    <span className="badge badge-info">×{count}</span>
                                                )}
                                            </td>
                                        )}
                                    </tr>
                                )
                            })}
                        </tbody>
                    </table>
                </div>
            ))}
        </aside>
    )
}
