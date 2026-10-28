import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload } from '@fortawesome/free-solid-svg-icons'

export type YearDownloadCardProps = {
    titleKey: string
    descriptionKey: string
    busy: boolean
    error: string | null
    onDownload: () => void
    actionLabelKey?: string
}

export function YearDownloadCard({
    titleKey,
    descriptionKey,
    busy,
    error,
    onDownload,
    actionLabelKey,
}: YearDownloadCardProps) {
    const { t } = useTranslation()

    return (
        <section className="card">
            <h3 className="mt-0">{t(titleKey)}</h3>
            <p className="muted mb-1">{t(descriptionKey)}</p>
            <div className="actions-row">
                <button
                    type="button"
                    className="button button-primary"
                    disabled={busy}
                    onClick={onDownload}
                >
                    <FontAwesomeIcon icon={faDownload} fixedWidth />
                    {busy ? t('pages.reports.downloading') : t(actionLabelKey ?? 'pages.reports.download')}
                </button>
            </div>
            {error && (
                <p className="error-text mt-05" role="alert">
                    {error}
                </p>
            )}
        </section>
    )
}
