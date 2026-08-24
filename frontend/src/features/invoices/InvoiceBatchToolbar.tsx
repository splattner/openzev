import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload, faEllipsis } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { ActionMenu, type ActionMenuItem } from '../../components/ActionMenu'

type BatchStat = {
  key: string
  label: string
  value: number
}

type InvoiceBatchToolbarProps = {
  stats: BatchStat[]
  recommendedAction: ActionMenuItem | null
  menuItems: ActionMenuItem[]
  anyBatchPending: boolean
  pdfCount: number
  onDownloadAll: () => void
}

export function InvoiceBatchToolbar({
  stats,
  recommendedAction,
  menuItems,
  anyBatchPending,
  pdfCount,
  onDownloadAll,
}: InvoiceBatchToolbarProps) {
  const { t } = useTranslation()

  // The menu never repeats the promoted recommended action.
  const menuActions = menuItems.filter((item) => item.key !== recommendedAction?.key)

  return (
    <section className="card invoice-batch-toolbar">
      <div className="invoice-batch-header">
        <div className="invoice-batch-title">{t('pages.invoices.batch.title')}</div>
        <div className="invoice-batch-summary">
          {stats.map((stat) => (
            <span key={stat.key} className="invoice-batch-stat">
              <span className="invoice-batch-stat-label">{stat.label}</span>
              <span className="invoice-batch-stat-value">{stat.value}</span>
            </span>
          ))}
        </div>
      </div>
      <div className="invoice-batch-actions">
        {recommendedAction && (
          <button
            className="button button-primary"
            type="button"
            disabled={recommendedAction.disabled}
            onClick={recommendedAction.onClick}
          >
            {recommendedAction.icon}
            {recommendedAction.label}
          </button>
        )}
        {/* Hidden rather than disabled when there is nothing to act on
            (e.g. future periods): permanently dead buttons read as a stuck
            loading state. Disabled is reserved for transient batch pending. */}
        {pdfCount > 0 && (
          <button
            className="button button-secondary button-compact"
            type="button"
            disabled={anyBatchPending}
            onClick={onDownloadAll}
          >
            <FontAwesomeIcon icon={faDownload} fixedWidth />
            {t('pages.invoices.batch.downloadAll')} ({pdfCount})
          </button>
        )}
        {(anyBatchPending || menuActions.some((item) => !item.disabled)) && (
          <ActionMenu
            label={t('pages.invoices.moreBatchActions')}
            icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
            items={menuActions}
          />
        )}
      </div>
    </section>
  )
}
