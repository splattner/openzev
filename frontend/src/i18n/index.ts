import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { en } from './locales/en'
import { de } from './locales/de'
import { fr } from './locales/fr'
import { it } from './locales/it'

const langs = ['en', 'de', 'fr', 'it'] as const
type Lang = (typeof langs)[number]

const normalize = (lang?: string | null): Lang =>
    langs.includes(lang as Lang) ? (lang as Lang) : 'en'

const initial = normalize(
    localStorage.getItem('openzev.language') ?? navigator.language?.split('-')[0],
)

void i18n.use(initReactI18next).init({
    resources: {
        en: { translation: en },
        de: { translation: de },
        fr: { translation: fr },
        it: { translation: it },
    },
    lng: initial,
    fallbackLng: 'en',
    supportedLngs: [...langs],
    interpolation: { escapeValue: false },
})

const setHtmlLang = (lang: string) => {
    document.documentElement.lang = `${normalize(lang)}-CH`
}

setHtmlLang(initial)

i18n.on('languageChanged', (lang) => {
    const next = normalize(lang)
    localStorage.setItem('openzev.language', next)
    setHtmlLang(next)
})

export default i18n
