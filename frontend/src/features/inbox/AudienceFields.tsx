import { useTranslation } from 'react-i18next'
import type { Participant } from '../../types/api'

export type Audience = 'all' | 'selected'

export function participantLabel(participant: Participant): string {
  return participant.display_name || participant.full_name || `${participant.first_name} ${participant.last_name}`.trim()
}

type AudienceFieldsProps = {
  audience: Audience
  onAudienceChange: (audience: Audience) => void
  participants: readonly Participant[]
  selected: readonly string[]
  onSelectedChange: (ids: string[]) => void
  /** Radio group name; unique per dialog on the page. */
  name: string
  allLabel: string
  disabled?: boolean
}

/** Everyone, or a chosen few: the audience choice shared by the upload and issue dialogs. */
export function AudienceFields({
  audience, onAudienceChange, participants, selected, onSelectedChange, name, allLabel, disabled,
}: AudienceFieldsProps) {
  const { t } = useTranslation()
  const toggle = (id: string) =>
    onSelectedChange(selected.includes(id) ? selected.filter((value) => value !== id) : [...selected, id])

  return (
    <fieldset className="grid-span-full inbox-fieldset" disabled={disabled}>
      <legend>{t('inbox.audience.legend')}</legend>
      <label className="checkbox-row">
        <input type="radio" name={name} checked={audience === 'all'} onChange={() => onAudienceChange('all')} />
        <span>{allLabel}</span>
      </label>
      <label className="checkbox-row">
        <input type="radio" name={name} checked={audience === 'selected'} onChange={() => onAudienceChange('selected')} />
        <span>{t('inbox.audience.selected')}</span>
      </label>
      {audience === 'selected' && (
        <ul className="inbox-audience-list" aria-label={t('inbox.audience.participants')}>
          {participants.map((participant) => (
            <li key={participant.id}>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={selected.includes(participant.id)}
                  onChange={() => toggle(participant.id)}
                />
                <span>{participantLabel(participant)}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </fieldset>
  )
}
