import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload, faFilePdf, faPlus } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { ActionMenu } from '../../components/ActionMenu'
import { FilterTabs } from '../../components/FilterTabs'
import { Toolbar } from '../../components/Toolbar'

export type TariffValidityFilter = 'valid' | 'all'

type TariffToolbarProps = {
  /** Tariff series with a version in force today. */
  validCount: number
  /** All tariff series. */
  totalCount: number
  /** Some version is not in force today, so the overview PDF can also be
   * had with every version; without one the download is a plain button. */
  hasOutOfForceVersions: boolean
  validityFilter: TariffValidityFilter
  onValidityFilterChange: (value: TariffValidityFilter) => void
  onOpenCreateTariffModal: () => void
  readOnly?: boolean
  /** Absent when no single ZEV is selected — an import needs one target. */
  onOpenImportModal?: () => void
  /** Absent when no single ZEV is selected — same reason as the import button. */
  onDownloadOverview?: (scope: TariffValidityFilter) => void
  overviewBusy?: boolean
}

export function TariffToolbar({
  validCount,
  totalCount,
  hasOutOfForceVersions,
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
            {onDownloadOverview && (hasOutOfForceVersions ? (
              <ActionMenu
                compact={false}
                label={overviewBusy ? t('pages.tariffs.overviewPdf.busy') : t('pages.tariffs.overviewPdf.action')}
                icon={<FontAwesomeIcon icon={faFilePdf} fixedWidth />}
                items={(['valid', 'all'] as const).map((scope) => ({
                  key: scope,
                  label: t(`pages.tariffs.overviewPdf.scope.${scope}`),
                  onClick: () => onDownloadOverview(scope),
                  disabled: overviewBusy,
                }))}
              />
            ) : (
              <button
                type="button"
                className="button button-secondary"
                onClick={() => onDownloadOverview('valid')}
                disabled={overviewBusy}
              >
                <FontAwesomeIcon icon={faFilePdf} fixedWidth />
                {overviewBusy ? t('pages.tariffs.overviewPdf.busy') : t('pages.tariffs.overviewPdf.action')}
              </button>
            ))}
            {!readOnly && (
              <button className="button button-primary" type="button" onClick={onOpenCreateTariffModal}>
                <FontAwesomeIcon icon={faPlus} fixedWidth />
                {t('pages.tariffs.newTariff')}
              </button>
            )}
          </>
        ) : null}
      >
        <FilterTabs
          label={t('pages.tariffs.filters.validity')}
          tabs={[
            { value: 'valid', label: t('pages.tariffs.filters.validOnly'), count: validCount },
            { value: 'all', label: t('pages.tariffs.filters.all'), count: totalCount },
          ]}
          value={validityFilter}
          onChange={onValidityFilterChange}
        />
      </Toolbar>
    </section>
  )
}
