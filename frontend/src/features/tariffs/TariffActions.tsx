import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload, faFilePdf, faPlus } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { ActionMenu } from '../../components/ActionMenu'

import type { TariffValidityFilter } from './tariffOverview'

type TariffActionsProps = {
  onOpenCreateTariff: () => void
  readOnly?: boolean
  /** Absent when no single ZEV is selected — an import needs one target. */
  onOpenImportModal?: () => void
  /** Absent when no single ZEV is selected — same reason as the import button. */
  onDownloadOverview?: (scope: TariffValidityFilter) => void
  overviewBusy?: boolean
}

/** The tariff page's header actions: import, the overview PDF, and the one primary action. */
export function TariffActions({
  onOpenCreateTariff,
  readOnly = false,
  onOpenImportModal,
  onDownloadOverview,
  overviewBusy,
}: TariffActionsProps) {
  const { t } = useTranslation()

  return (
    <>
      {onOpenImportModal && (
        <button type="button" className="button button-secondary" onClick={onOpenImportModal}>
          <FontAwesomeIcon icon={faDownload} fixedWidth />
          {t('pages.tariffs.import.action')}
        </button>
      )}
      {onDownloadOverview && (
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
      )}
      {!readOnly && (
        <button className="button button-primary" type="button" onClick={onOpenCreateTariff}>
          <FontAwesomeIcon icon={faPlus} fixedWidth />
          {t('pages.tariffs.newTariff')}
        </button>
      )}
    </>
  )
}
