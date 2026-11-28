import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Badge, type BadgeProps } from '../src/components/Badge'
import { statusTreatment } from '../src/components/badgeTones'

describe('statusTreatment', () => {
    it('keeps a word that differs by workflow apart', () => {
        expect(statusTreatment('sent', 'invoice')).toEqual({ tone: 'tag' })
        expect(statusTreatment('sent', 'email')).toEqual({ tone: 'success' })
        expect(statusTreatment('queued', 'backup')).toEqual({ tone: 'neutral' })
        expect(statusTreatment('queued', 'audit')).toEqual({ tone: 'info' })
        expect(statusTreatment('current', 'assignment')).toEqual({ tone: 'success' })
        expect(statusTreatment('current', 'participantValidity')).toEqual({ tone: 'neutral' })
        // Declared change: a started audit event reads neutral everywhere, including dynamic-source activity.
        expect(statusTreatment('started', 'audit')).toEqual({ tone: 'neutral' })
    })

    it('falls back to neutral for an unknown status', () => {
        expect(statusTreatment('something-new', 'invoice')).toEqual({ tone: 'neutral' })
        expect(statusTreatment('toString', 'invoice')).toEqual({ tone: 'neutral' })
        expect(statusTreatment(undefined, 'audit')).toEqual({ tone: 'neutral' })
    })
})

describe('Badge', () => {
    const render = (props: BadgeProps) => renderToStaticMarkup(createElement(Badge, props))

    it('composes tone, quiet and a custom class', () => {
        expect(render({ tone: 'tag', children: 'Role' })).toBe('<span class="badge badge-tag">Role</span>')
        expect(render({ tone: 'warning', quiet: true, className: 'extra', children: 'Late' }))
            .toBe('<span class="badge badge-warning badge-quiet extra">Late</span>')
    })

    it('resolves a status through its domain, quiet included', () => {
        expect(render({ status: 'failed', domain: 'email', children: 'Failed' }))
            .toBe('<span class="badge badge-danger badge-quiet">Failed</span>')
        // Declared change: an unknown invoice status used to fall back to the tag style.
        expect(render({ status: 'archived', domain: 'invoice', children: 'archived' }))
            .toBe('<span class="badge badge-neutral">archived</span>')
    })

    it('forwards role, title and ARIA attributes', () => {
        const html = render({ tone: 'info', role: 'status', title: 'Hint', 'aria-label': 'Label: hint', children: 'x' })
        expect(html).toContain('role="status"')
        expect(html).toContain('title="Hint"')
        expect(html).toContain('aria-label="Label: hint"')
    })
})
