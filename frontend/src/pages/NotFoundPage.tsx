import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

export function NotFoundPage() {
    const { t } = useTranslation()
    return (
        <div className="center-screen">
            <div className="card not-found-card">
                <h2>{t('pages.notFound.title')}</h2>
                <p className="muted">{t('pages.notFound.description')}</p>
                <Link className="button" to="/">{t('common.back')}</Link>
            </div>
        </div>
    )
}
