import { useTranslation } from 'react-i18next'
import type { EmailField } from '../lib/emailTemplateFields'

export function EmailFieldReference({ fields, variant = 'table' }: { fields: EmailField[]; variant?: 'table' | 'aside' | 'details' }) {
    const { t } = useTranslation()
    const table = (
        <table className="data-table email-field-reference">
            <thead>
                <tr>
                    <th>{t('admin.emailTemplates.variable')}</th>
                    <th>{t('admin.emailTemplates.fieldDescription')}</th>
                </tr>
            </thead>
            <tbody>
                {fields.map(({ variable, descriptionKey }) => (
                    <tr key={variable}>
                        <td title={variable}>
                            <code>{variable}</code>
                        </td>
                        <td className="muted">{t(descriptionKey)}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    )
    if (variant === 'aside') {
        return (
            <aside className="card page-stack field-reference-aside" tabIndex={0} aria-label={t('admin.fieldReference')}>
                <h4>{t('admin.availableFields')}</h4>
                <p className="muted">{t('admin.emailTemplates.variableHint')}</p>
                {table}
            </aside>
        )
    }
    if (variant === 'details') {
        return (
            <details open className="field-reference-details">
                <summary>{t('admin.availableFields')}</summary>
                <div className="field-reference-details-content">{table}</div>
            </details>
        )
    }
    return table
}
