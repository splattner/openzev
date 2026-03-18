import { useTranslation } from 'react-i18next'

interface LanguageSelectorProps {
    variant?: 'sidebar' | 'menu'
}

export function LanguageSelector({ variant = 'sidebar' }: LanguageSelectorProps) {
    const { i18n, t } = useTranslation()
    const isMenu = variant === 'menu'

    return (
        <div className={`language-selector language-selector-${variant}`}>
            <label className={`language-selector-label${isMenu ? ' menu' : ''}`}>
                {t('common.language')}
            </label>
            <div className="language-selector-options">
                {(['en', 'de', 'fr', 'it'] as const).map((lang) => (
                    <button
                        key={lang}
                        type="button"
                        onClick={() => void i18n.changeLanguage(lang)}
                        className={`language-selector-button${i18n.language === lang ? ' active' : ''}${isMenu ? ' menu' : ''}`}
                    >
                        {lang.toUpperCase()}
                    </button>
                ))}
            </div>
        </div>
    )
}
