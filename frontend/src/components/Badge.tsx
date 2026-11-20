import type { HTMLAttributes, ReactNode } from 'react'
import { statusTreatment, type BadgeTone, type StatusDomain } from './badgeTones'

// The `never` fields make the two modes exclusive: a status takes its treatment from the map, never a local override.
type BadgeLook =
  | { tone: BadgeTone; quiet?: boolean; status?: never; domain?: never }
  | { status: string | null | undefined; domain: StatusDomain; tone?: never; quiet?: never }

export type BadgeProps = Omit<HTMLAttributes<HTMLSpanElement>, 'children'> & BadgeLook & { children: ReactNode }

/** A pill label. Problems the user can act on use `IssueText` instead (UI patterns §10.1). */
export function Badge({ children, tone, quiet, status, domain, className, ...rest }: BadgeProps) {
  const treatment = domain ? statusTreatment(status, domain) : { tone, quiet }
  const classes = ['badge', `badge-${treatment.tone}`]
  if (treatment.quiet) classes.push('badge-quiet')
  if (className) classes.push(className)
  return <span className={classes.join(' ')} {...rest}>{children}</span>
}
