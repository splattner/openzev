import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge } from './Badge'

const SOURCE_LABEL_KEYS = {
    builtIn: 'templates.source.builtIn',
    customized: 'templates.source.customized',
    platform: 'templates.source.platform',
    zev: 'templates.source.zev',
} as const

/** Persisted source and local draft state are deliberately separate. */
export function TemplateSourceStatus({ source, changed = false, action, description }: {
    source: 'builtIn' | 'customized' | 'platform' | 'zev'
    changed?: boolean
    action?: ReactNode
    description?: string
}) {
    const { t } = useTranslation()
    const label = t(SOURCE_LABEL_KEYS[source])

    return (
        <div className="template-source">
            <div className="template-source-main">
                <Badge tone={source === 'customized' || source === 'zev' ? 'info' : 'neutral'}>
                    {label}
                </Badge>
                {changed && <span className="muted" role="status">{t('templates.source.unsavedChanges')}</span>}
                {action}
            </div>
            {description && <p className="muted">{description}</p>}
        </div>
    )
}
