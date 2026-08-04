import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faPlus } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'

type TariffEmptyStateProps = {
  onOpenCreateTariffModal: () => void
}

export function TariffEmptyState({ onOpenCreateTariffModal }: TariffEmptyStateProps) {
  const { t } = useTranslation()

  return (
    <section className="card tariff-empty-state">
      <h3>{t('pages.tariffs.noTariffs')}</h3>
      <p className="muted">{t('pages.tariffs.description')}</p>
      <div className="actions-row actions-row-wrap">
        <button className="button button-primary" type="button" onClick={onOpenCreateTariffModal}>
          <FontAwesomeIcon icon={faPlus} fixedWidth />
          {t('pages.tariffs.newTariff')}
        </button>
      </div>
    </section>
  )
}
