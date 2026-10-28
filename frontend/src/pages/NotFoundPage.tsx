import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useDocumentTitle } from '../lib/useDocumentTitle'

export function NotFoundPage() {
    const { t } = useTranslation()
    useDocumentTitle(t('pages.notFound.title'))
    return (
        <div className="center-screen">
            <div className="card not-found-card">
                <h2>{t('pages.notFound.title')}</h2>
                <p className="muted">{t('pages.notFound.description')}</p>
                <Link className="button button-primary" to="/">{t('common.back')}</Link>
            </div>
        </div>
    )
}
