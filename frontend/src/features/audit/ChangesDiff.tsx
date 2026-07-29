import { useTranslation } from 'react-i18next'

/** One field's before/after pair, as produced by the backend's `build_diff`. */
type FieldChange = { before: unknown; after: unknown }

/**
 * `changes_json` is a JSONField, so nothing guarantees its shape — hand-written
 * call sites happen to follow `{field: {before, after}}` today, but old rows may
 * hold anything. Only render the diff table when every entry actually matches;
 * otherwise fall back to the raw JSON so no event becomes unreadable.
 */
function asFieldChanges(value: unknown): Record<string, FieldChange> | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null

    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length === 0) return null

    const conforms = entries.every(([, change]) =>
        Boolean(change)
        && typeof change === 'object'
        && !Array.isArray(change)
        && 'before' in (change as object)
        && 'after' in (change as object),
    )

    return conforms ? (value as Record<string, FieldChange>) : null
}

function formatValue(value: unknown): string {
    if (value === null || value === undefined || value === '') return '—'
    if (typeof value === 'boolean') return value ? 'true' : 'false'
    if (typeof value === 'object') return JSON.stringify(value)
    return String(value)
}

export function ChangesDiff({ changes }: { changes: unknown }) {
    const { t } = useTranslation()
    const fieldChanges = asFieldChanges(changes)

    if (!fieldChanges) {
        const isEmpty = !changes
            || (typeof changes === 'object' && Object.keys(changes as object).length === 0)
        if (isEmpty) return <p className="muted">{t('pages.auditLogs.detail.noChanges')}</p>
        return <pre style={{ overflowX: 'auto' }}>{JSON.stringify(changes, null, 2)}</pre>
    }

    return (
        <table className="audit-diff">
            <thead>
                <tr>
                    <th>{t('pages.auditLogs.detail.diffField')}</th>
                    <th>{t('pages.auditLogs.detail.diffBefore')}</th>
                    <th>{t('pages.auditLogs.detail.diffAfter')}</th>
                </tr>
            </thead>
            <tbody>
                {Object.entries(fieldChanges).map(([field, change]) => (
                    <tr key={field}>
                        <td><code>{field}</code></td>
                        <td className="audit-diff-before">{formatValue(change.before)}</td>
                        <td className="audit-diff-after">{formatValue(change.after)}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    )
}
