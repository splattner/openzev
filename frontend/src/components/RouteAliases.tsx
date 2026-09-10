import { Navigate, useLocation, useParams } from 'react-router-dom'

export function AliasNavigate({ to }: { to: string }) {
  const { search, hash } = useLocation()
  if (!search && !hash) return <Navigate to={to} replace />
  const [pathname, existingSearch] = to.split('?')
  const params = new URLSearchParams(existingSearch ?? '')
  // The target's own params win: an alias pins its destination (e.g. the
  // settings tab), so incoming keys only fill gaps instead of hijacking it.
  new URLSearchParams(search).forEach((v, k) => {
    if (!params.has(k)) params.set(k, v)
  })
  const qs = params.toString()
  return <Navigate to={`${pathname}${qs ? `?${qs}` : ''}${hash}`} replace />
}

export function InvoiceDetailAlias() {
  const { invoiceId } = useParams<{ invoiceId: string }>()
  const { search, hash } = useLocation()
  return <Navigate to={`/billing/invoices/${encodeURIComponent(invoiceId ?? '')}${search}${hash}`} replace />
}

// Convert legacy tab queries into guarded routes; preserve other filters.
// NOTE: participant with a legacy ?tab=quality bookmark bounces to / and
// loses filters (pinned in route-guard-matrix.test.ts). Accepted — quality
// was never a participant surface.
export function MeteringDataAlias() {
  const { search, hash } = useLocation()
  const params = new URLSearchParams(search)
  const tab = params.get('tab')
  params.delete('tab')
  const qs = params.toString()
  return <Navigate to={`/metering/${tab === 'quality' ? 'quality' : 'chart'}${qs ? `?${qs}` : ''}${hash}`} replace />
}
