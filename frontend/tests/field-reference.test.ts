import { act, createElement, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it } from 'vitest'
import {
  catalogSyntax,
  countCatalogOccurrences,
  extractTemplateTokens,
  insertTemplateToken,
  tokenInner,
  tokenLookupKey,
  useTemplateTokenInsertionAtElement,
} from '../src/components/FieldReference'
import type { TemplateFieldGroup } from '../src/types/api'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

function textarea(initial: string, selectionStart = 0, selectionEnd = 0): HTMLTextAreaElement {
  const el = document.createElement('textarea')
  el.value = initial
  el.setSelectionRange(selectionStart, selectionEnd)
  return el
}

function ControlledTextareaHarness({ initialValue, variable }: { initialValue: string; variable: string }) {
  const [value, setValue] = useState(initialValue)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const insert = useTemplateTokenInsertionAtElement(textareaRef, setValue)
  const setTextareaRef = (element: HTMLTextAreaElement | null) => {
    textareaRef.current = element
  }
  return createElement(
    'div',
    null,
    // eslint-disable-next-line react-hooks/refs -- React attaches this callback ref after commit.
    createElement('textarea', { ref: setTextareaRef, value, onChange: (event) => setValue(event.target.value) }),
    createElement('button', { type: 'button', onMouseDown: (event) => event.preventDefault(), onClick: () => insert(variable, false) }, 'insert'),
  )
}

describe('controlled textarea insertion', () => {
  it('restores the caret after the controlled value updates', () => {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    try {
      act(() => root.render(createElement(ControlledTextareaHarness, { initialValue: 'Hello ', variable: '{{ name }}' })))
      const editor = container.querySelector('textarea')!
      const button = container.querySelector('button')!
      editor.focus()
      editor.setSelectionRange(6, 6)
      act(() => button.click())

      expect(editor.value).toBe('Hello {{ name }}')
      expect(editor.selectionStart).toBe(6 + '{{ name }}'.length)
      expect(document.activeElement).toBe(editor)
    } finally {
      act(() => root.unmount())
      container.remove()
    }
  })

  it('moves the caret when replacing a selection with the same token', () => {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    try {
      act(() => root.render(createElement(ControlledTextareaHarness, { initialValue: '{{ name }}', variable: '{{ name }}' })))
      const editor = container.querySelector('textarea')!
      editor.focus()
      editor.setSelectionRange(0, editor.value.length)
      act(() => container.querySelector('button')!.click())

      expect(editor.value).toBe('{{ name }}')
      expect(editor.selectionStart).toBe(editor.value.length)
    } finally {
      act(() => root.unmount())
      container.remove()
    }
  })
})

describe('extractTemplateTokens', () => {
  it('finds django tokens nested in css without matching style braces', () => {
    const content = `.info-list li {
            color: var(--ink-soft);
        }
        .page-meta .meta-center::after {
            content: "{{ tr.page_label }} " counter(page) " {{ tr.page_of }} " counter(pages);
        }`
    expect(extractTemplateTokens(content, 'django')).toEqual(['{{ tr.page_label }}', '{{ tr.page_of }}'])
  })

  it('matches django output and loop tags', () => {
    const content = '{{ participant.full_name }}\n{% for row in local_tariff_rows %}\n…\n{% endfor %}'
    expect(extractTemplateTokens(content, 'django')).toEqual([
      '{{ participant.full_name }}',
      '{% for row in local_tariff_rows %}',
      '{% endfor %}',
    ])
  })

  it('matches email placeholders but not css declarations', () => {
    const content = 'Invoice {invoice_number}\na { color: red; }'
    expect(extractTemplateTokens(content, 'email')).toEqual(['{invoice_number}'])
  })

  it('derives the syntax from the catalog groups', () => {
    const djangoGroups: TemplateFieldGroup[] = [{
      group_key: 'translations',
      group_title_key: null,
      fields: [{ variable: '{{ tr.page_label }}', description_key: 'admin.fields.trDescription', example: null }],
    }]
    const emailGroups: TemplateFieldGroup[] = [{
      group_key: 'invoiceEmail',
      group_title_key: null,
      fields: [{ variable: '{invoice_number}', description_key: 'admin.emailTemplates.fields.invoiceNumber', example: 'INV-1' }],
    }]
    expect(catalogSyntax(djangoGroups)).toBe('django')
    expect(catalogSyntax(emailGroups)).toBe('email')
  })
})

describe('countCatalogOccurrences', () => {
  const translationGroups: TemplateFieldGroup[] = [{
    group_key: 'translations',
    group_title_key: null,
    fields: [
      { variable: '{{ tr.page_label }}', description_key: 'admin.fields.trDescription', example: null },
      { variable: '{{ tr.page_of }}', description_key: 'admin.fields.trDescription', example: null },
    ],
  }]

  it('badges fields nested in css', () => {
    const content = `.page-meta .meta-center::after {
            content: "{{ tr.page_label }} " counter(page) " {{ tr.page_of }} " counter(pages);
        }`
    const counts = countCatalogOccurrences(content, translationGroups)
    expect(counts.get('{{ tr.page_label }}')).toBe(1)
    expect(counts.get('{{ tr.page_of }}')).toBe(1)
  })

  it('counts pdf output tokens regardless of whitespace inside the braces', () => {
    const groups: TemplateFieldGroup[] = [{
      group_key: 'participant',
      group_title_key: null,
      fields: [{ variable: '{{ participant.full_name }}', description_key: 'admin.fields.fullName', example: 'Hans Beispiel' }],
    }]
    const counts = countCatalogOccurrences('{{ participant.full_name }}\nHi {{participant.full_name}}', groups)
    expect(counts.get('{{ participant.full_name }}')).toBe(2)
  })

  it('counts email tokens per field', () => {
    const groups: TemplateFieldGroup[] = [{
      group_key: 'invoiceEmail',
      group_title_key: null,
      fields: [{ variable: '{invoice_number}', description_key: 'admin.emailTemplates.fields.invoiceNumber', example: 'INV-1' }],
    }]
    expect(countCatalogOccurrences('Invoice {invoice_number} for {invoice_number}', groups).get('{invoice_number}')).toBe(2)
    expect(countCatalogOccurrences('nothing here', groups).get('{invoice_number}')).toBe(0)
  })

  it('counts a token when the editor uses a filter variation', () => {
    const groups: TemplateFieldGroup[] = [{
      group_key: 'invoiceObject',
      group_title_key: null,
      fields: [{ variable: '{{ invoice.total_chf }}', description_key: 'admin.fields.total', example: '486.45' }],
    }]
    expect(countCatalogOccurrences('{{ invoice.total_chf|floatformat:2 }}', groups).get('{{ invoice.total_chf }}')).toBe(1)
  })

  it('does not confuse Python-format and Django token delimiters', () => {
    const groups: TemplateFieldGroup[] = [{
      group_key: 'invoiceObject',
      group_title_key: null,
      fields: [{ variable: '{{ invoice_number }}', description_key: 'admin.fields.invoiceNumber', example: 'INV-1' }],
    }]
    expect(countCatalogOccurrences('{invoice_number}', groups).get('{{ invoice_number }}')).toBe(0)
  })
})

describe('insertTemplateToken', () => {
  it('inserts a variable at the caret', () => {
    const el = textarea('Hello ', 6, 6)
    const insertion = insertTemplateToken(el, '{{ participant.full_name }}', false)
    expect(insertion.value).toBe('Hello {{ participant.full_name }}')
    expect(insertion.selectionStart).toBe(insertion.value.length)
  })

  it('replaces the selection', () => {
    const el = textarea('Hi [old] there', 3, 8)
    const insertion = insertTemplateToken(el, '{zev_name}', false)
    expect(insertion.value).toBe('Hi {zev_name} there')
  })

  it('inserts loop tags as an indented block with the caret inside', () => {
    const el = textarea('', 0, 0)
    const insertion = insertTemplateToken(el, '{% for item in group.items %}', false)
    expect(insertion.value).toBe('{% for item in group.items %}\n    \n{% endfor %}')
    expect(insertion.value.slice(insertion.selectionStart - 4, insertion.selectionStart)).toBe('    ')
  })

  it('inserts non-loop tags without an endfor block', () => {
    const el = textarea('', 0, 0)
    const insertion = insertTemplateToken(el, '{% if row.valid_to %}', false)
    expect(insertion.value).toBe('{% if row.valid_to %}')
  })

  it('inserts without moving the caret when keepFocus is set', () => {
    const el = textarea('abc', 1, 1)
    const insertion = insertTemplateToken(el, '{verify_url}', true)
    expect(insertion.value).toBe('a{verify_url}bc')
    expect(insertion.selectionStart).toBe(1)
  })
})

describe('tokenInner', () => {
  it('strips pdf braces', () => {
    expect(tokenInner('{{ participant.full_name }}')).toBe('participant.full_name')
  })

  it('strips loop-tag braces', () => {
    expect(tokenInner('{% for group in grouped_items %}')).toBe('for group in grouped_items')
  })

  it('strips single email braces', () => {
    expect(tokenInner('{expiry_date}')).toBe('expiry_date')
  })
})

describe('tokenLookupKey', () => {
  it('normalizes whitespace and optional filters', () => {
    expect(tokenLookupKey('{{ participant.full_name }}')).toBe('participant.full_name')
    expect(tokenLookupKey('{{invoice.total_chf|floatformat:2}}')).toBe('invoice.total_chf')
    expect(tokenLookupKey('{{ participant.phone|default:"—" }}')).toBe('participant.phone')
  })
})
