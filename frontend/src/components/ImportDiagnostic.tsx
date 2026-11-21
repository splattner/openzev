import { useTranslation } from 'react-i18next'
import { Disclosure } from './Disclosure'
import { useOptionalAppSettings } from '../lib/appSettings'
import { formatImportDiagnostic, keepsTechnicalDetails } from '../lib/importDiagnostics'

export function ImportDiagnostic({ text, diagnostic, message, fallback }: {
  text: string
  diagnostic?: unknown
  /** Already translated text, e.g. field errors; takes precedence over `diagnostic`. */
  message?: string
  fallback: string
}) {
  const { t } = useTranslation()
  const settings = useOptionalAppSettings() ?? undefined
  const translated = message || formatImportDiagnostic(diagnostic, t, settings)
  return <>
    {translated || fallback}
    {text && (!translated || keepsTechnicalDetails(diagnostic, t)) && (
      <Disclosure lazy className="disclosure-sm" summary={t('importDiagnostics.technicalDetails')}>
        {text}
      </Disclosure>
    )}
  </>
}
