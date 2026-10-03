import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload, faFilePdf, faPlus } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { Toolbar } from '../../components/Toolbar'

export type TariffValidityFilter = 'valid' | 'all'

type TariffToolbarProps = {
  tariffCount: number
  energyTariffCount: number
  tariffsWithPeriodsCount: number
  periodCount: number
  validityFilter: TariffValidityFilter
  onValidityFilterChange: (value: TariffValidityFilter) => void
  onOpenCreateTariffModal: () => void
  readOnly?: boolean
  /** Absent when no single ZEV is selected — an import needs one target. */
  onOpenImportModal?: () => void
  /** Absent when no single ZEV is selected — same reason as the import button. */
  onDownloadOverview?: () => void
  overviewBusy?: boolean
}

export function TariffToolbar({
  tariffCount,
  energyTariffCount,
  tariffsWithPeriodsCount,
  periodCount,
  validityFilter,
  onValidityFilterChange,
  onOpenCreateTariffModal,
  readOnly = false,
  onOpenImportModal,
  onDownloadOverview,
  overviewBusy,
}: TariffToolbarProps) {
  const { t } = useTranslation()

  return (
    <section className="card tariff-toolbar">
      <Toolbar
        actions={!readOnly || onOpenImportModal || onDownloadOverview ? (
          <>
            {onOpenImportModal && (
              <button type="button" className="button button-secondary" onClick={onOpenImportModal}>
                <FontAwesomeIcon icon={faDownload} fixedWidth />
                {t('pages.tariffs.import.action')}
              </button>
            )}
            {onDownloadOverview && (
              <button
                type="button"
                className="button button-secondary"
                onClick={onDownloadOverview}
                disabled={overviewBusy}
              >
                <FontAwesomeIcon icon={faFilePdf} fixedWidth />
                {overviewBusy ? t('pages.tariffs.overviewPdf.busy') : t('pages.tariffs.overviewPdf.action')}
              </button>
            )}
            {!readOnly && (
              <button className="button button-primary" type="button" onClick={onOpenCreateTariffModal}>
                <FontAwesomeIcon icon={faPlus} fixedWidth />
                {t('pages.tariffs.newTariff')}
              </button>
            )}
          </>
        ) : null}
      >
        <div className="tariff-summary" aria-label={t('pages.tariffs.summaryLabel')}>
          <span className="tariff-summary-stat">
            <span className="tariff-summary-label">{t('pages.tariffs.summary.total')}</span>
            <span className="tariff-summary-value">{tariffCount}</span>
          </span>
          <span className="tariff-summary-stat">
            <span className="tariff-summary-label">{t('pages.tariffs.summary.energyBased')}</span>
            <span className="tariff-summary-value">{energyTariffCount}</span>
          </span>
          <span className="tariff-summary-stat">
            <span className="tariff-summary-label">{t('pages.tariffs.summary.withPeriods')}</span>
            <span className="tariff-summary-value">{tariffsWithPeriodsCount}</span>
          </span>
          <span className="tariff-summary-stat">
            <span className="tariff-summary-label">{t('pages.tariffs.summary.totalPeriods')}</span>
            <span className="tariff-summary-value">{periodCount}</span>
          </span>
        </div>
      </Toolbar>

      <div className="tariff-filter-grid">
        <label>
          <span>{t('pages.tariffs.filters.validity')}</span>
          <select
            value={validityFilter}
            onChange={(event) => onValidityFilterChange(event.target.value as TariffValidityFilter)}
          >
            <option value="valid">{t('pages.tariffs.filters.validOnly')}</option>
            <option value="all">{t('pages.tariffs.filters.all')}</option>
          </select>
        </label>
      </div>
    </section>
  )
}
