import type { MeteringPointStatus } from './useMeteringPointForms'

const DOT_CLASS: Record<MeteringPointStatus, string> = {
  ok: 'dot dot-success',
  warning: 'dot dot-warning',
  danger: 'dot dot-critical',
  pending: 'dot dot-pending',
  inactive: 'dot',
}

/**
 * A meter's status as a coloured dot. The colour is never the only signal: the
 * label is the dot's accessible name and its tooltip.
 */
export function MeteringPointStatusDot({ status, label }: { status: MeteringPointStatus; label?: string }) {
  // Without a label the dot only decorates text that says the same.
  if (!label) return <span className={DOT_CLASS[status]} aria-hidden="true" />
  return <span className={DOT_CLASS[status]} role="img" aria-label={label} title={label} />
}
