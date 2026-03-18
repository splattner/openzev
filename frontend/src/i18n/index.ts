import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { en } from './locales/en'
import { de } from './locales/de'
import { fr } from './locales/fr'
import { it } from './locales/it'

const getBrowserLanguage = (): string => {
    const browserLang = navigator.language?.split('-')[0] || 'en'
    return ['en', 'de', 'fr', 'it'].includes(browserLang) ? browserLang : 'en'
}

const savedLang = localStorage.getItem('openzev.language')
const initialLang = savedLang || getBrowserLanguage()

void i18n.use(initReactI18next).init({
    resources: {
        en: { translation: en },
        de: { translation: de },
        fr: { translation: fr },
        it: { translation: it },
    },
    lng: initialLang,
    fallbackLng: 'en',
    interpolation: { escapeValue: false },
})

// Persist language preference when changed
i18n.on('languageChanged', (lang) => {
    localStorage.setItem('openzev.language', lang)
})

export default i18n
