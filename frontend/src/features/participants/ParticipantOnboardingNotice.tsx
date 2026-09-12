import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCopy, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { copyToClipboard } from '../../lib/clipboard'
import { useToast } from '../../lib/toast'

export type ParticipantOnboardingNoticeData = {
  participantName: string
  onboardingUrl: string
  message: string
}

type ParticipantOnboardingNoticeProps = {
  notice: ParticipantOnboardingNoticeData
  onDismiss: () => void
}

/**
 * Shows the onboarding link after it was sent or copied.
 *
 * Unlike the credentials it replaces, nothing here is secret in the sense a
 * password is — but it is still a bearer link, so it is shown once and left
 * to the operator to dismiss, the same way a temporary password was.
 */
export function ParticipantOnboardingNotice({ notice, onDismiss }: ParticipantOnboardingNoticeProps) {
  const { t } = useTranslation()
  const { pushToast } = useToast()

  async function copyLink() {
    const ok = await copyToClipboard(notice.onboardingUrl)
    pushToast(
      ok ? t('pages.participants.messages.linkCopied') : t('pages.participants.messages.copyFailed'),
      ok ? 'success' : 'error',
    )
  }

  return (
    <section className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div>
          <h3 style={{ marginTop: 0, marginBottom: '0.5rem' }}>{t('pages.participants.onboardingLinkTitle')}</h3>
          <p className="muted" style={{ marginTop: 0 }}>{notice.message}</p>
          <p style={{ marginBottom: '0.35rem' }}><strong>{notice.participantName}</strong></p>
          <p style={{ margin: '0.2rem 0', wordBreak: 'break-all' }}>{notice.onboardingUrl}</p>
        </div>
        <div className="actions-row actions-row-wrap actions-row-end">
          <button className="button button-secondary button-compact" type="button" onClick={() => void copyLink()}>
            <FontAwesomeIcon icon={faCopy} fixedWidth />
            {t('pages.participants.copyOnboardingLink')}
          </button>
          <button className="button button-secondary button-compact" type="button" onClick={onDismiss}>
            <FontAwesomeIcon icon={faXmark} fixedWidth />
            {t('pages.participants.dismiss')}
          </button>
        </div>
      </div>
    </section>
  )
}
