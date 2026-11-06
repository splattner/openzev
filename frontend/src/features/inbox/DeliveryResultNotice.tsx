import { useTranslation } from 'react-i18next'
import type { DeliveryResult } from '../../types/api'

/** What a delivery did: how many rows, and how many recipients cannot see them yet. */
export function DeliveryResultNotice({ result }: { result: DeliveryResult }) {
  const { t } = useTranslation()
  return (
    <div role="status" className="inbox-result">
      <p className="m-0"><strong>{t('inbox.result.delivered', { count: result.delivered })}</strong></p>
      {result.emailed > 0 && <p className="muted m-0">{t('inbox.result.emailed', { count: result.emailed })}</p>}
      {result.without_email > 0 && (
        <p className="muted m-0">{t('inbox.result.withoutEmail', { count: result.without_email })}</p>
      )}
      {result.without_account > 0 && (
        <p className="muted m-0">{t('inbox.result.withoutAccount', { count: result.without_account })}</p>
      )}
    </div>
  )
}
