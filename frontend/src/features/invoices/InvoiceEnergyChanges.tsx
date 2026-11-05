import { useTranslation } from 'react-i18next'
import { formatKwh } from '../../lib/numbers'
import type { Invoice } from '../../types/api'

type EnergyTotals = Pick<Invoice, 'total_local_kwh' | 'total_grid_kwh' | 'total_feed_in_kwh'>

export function InvoiceEnergyChanges({ before, after }: { before: EnergyTotals; after: EnergyTotals }) {
    const { t } = useTranslation()
    const label = (kind: 'local' | 'grid' | 'feed_in') => t(`pages.invoiceDetail.${kind === 'feed_in' ? 'feedIn' : kind}`)
    // Invoice quantities have four decimal places; compare their integer units.
    const localDelta = before.total_local_kwh == null ? 0 : Math.round((Number(after.total_local_kwh) - Number(before.total_local_kwh)) * 10000)
    const gridDelta = before.total_grid_kwh == null ? 0 : Math.round((Number(after.total_grid_kwh) - Number(before.total_grid_kwh)) * 10000)
    if (localDelta && localDelta === -gridDelta && before.total_feed_in_kwh != null
        && Number(before.total_feed_in_kwh) === Number(after.total_feed_in_kwh)) {
        return <p className="m-0">{t('pages.invoices.dataReview.energyShift', {
            amount: formatKwh(Math.abs(localDelta) / 10000, { maxDecimals: 4 }),
            from: label(localDelta < 0 ? 'local' : 'grid'), to: label(localDelta < 0 ? 'grid' : 'local'),
        })}</p>
    }
    return <>{(['local', 'grid', 'feed_in'] as const).map(kind => {
        const field = `total_${kind}_kwh` as const
        if (before[field] == null || after[field] == null || Number(before[field]) === Number(after[field])) return null
        return <p className="m-0" key={kind}>{t('pages.invoices.dataReview.energyChanged', {
            label: label(kind), from: formatKwh(Number(before[field]), { maxDecimals: 4 }), to: formatKwh(Number(after[field]), { maxDecimals: 4 }),
        })}</p>
    })}</>
}
