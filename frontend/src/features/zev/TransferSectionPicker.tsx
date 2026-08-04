import { useTranslation } from 'react-i18next'
import {
  isSelectable,
  toggleSection,
  unmetRequirements,
  type TransferSection,
  type TransferSectionName,
} from './transferSections'

type TransferSectionPickerProps = {
  sections: TransferSection[]
  selected: TransferSectionName[]
  onChange: (next: TransferSectionName[]) => void
  /** Sections the archive does not contain; shown but not selectable. */
  unavailable?: TransferSectionName[]
  counts?: Record<string, number>
  disabled?: boolean
}

export function TransferSectionPicker({
  sections,
  selected,
  onChange,
  unavailable = [],
  counts,
  disabled = false,
}: TransferSectionPickerProps) {
  const { t } = useTranslation()

  return (
    <fieldset style={{ border: 'none', padding: 0, margin: 0, display: 'grid', gap: '0.5rem' }}>
      <legend className="muted" style={{ fontSize: '0.85rem', marginBottom: '0.5rem' }}>
        {t('zevTransfer.sectionsLegend')}
      </legend>

      {sections.map((section) => {
        const missing = unmetRequirements(section, selected)
        const notInArchive = unavailable.includes(section.name)
        // A section whose prerequisite is unticked is greyed out rather than
        // left clickable to fail at import time.
        const isDisabled = disabled || notInArchive || !isSelectable(section, selected)
        const count = counts?.[section.name]

        return (
          // .checkbox-row is what stops the global `input { width: 100% }`
          // from stretching the box and pushing the label to the far right.
          <label
            key={section.name}
            className="checkbox-row"
            style={{
              alignItems: 'flex-start',
              opacity: isDisabled ? 0.55 : 1,
              cursor: isDisabled ? 'not-allowed' : 'pointer',
            }}
          >
            <input
              type="checkbox"
              checked={selected.includes(section.name)}
              disabled={isDisabled}
              onChange={() => onChange(toggleSection(sections, selected, section.name))}
            />
            <span style={{ display: 'grid', gap: '0.15rem' }}>
              <span>
                {t(`zevTransfer.sections.${section.name}`)}
                {typeof count === 'number' && (
                  <span className="muted" style={{ marginLeft: '0.4rem', fontSize: '0.85rem' }}>
                    ({count})
                  </span>
                )}
              </span>
              {notInArchive && (
                <small className="muted">{t('zevTransfer.notInArchive')}</small>
              )}
              {!notInArchive && missing.length > 0 && (
                <small className="muted">
                  {t('zevTransfer.requires', {
                    sections: missing.map((name) => t(`zevTransfer.sections.${name}`)).join(', '),
                  })}
                </small>
              )}
            </span>
          </label>
        )
      })}
    </fieldset>
  )
}
