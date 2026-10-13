import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    type IconDefinition,
    faCircleCheck,
    faCircleExclamation,
    faSpinner,
} from '@fortawesome/free-solid-svg-icons'
import type { ReactNode } from 'react'

export type ProgressState = 'done' | 'open' | 'active' | 'issue'

/** The small mark on a step's corner; an open step carries none. */
const STATE_MARKS: Partial<Record<ProgressState, IconDefinition>> = {
    done: faCircleCheck,
    active: faSpinner,
    issue: faCircleExclamation,
}

/** A row's step as an icon with its state marked on the corner (the invoice progress look). */
export function ProgressIcon({ icon, state }: { icon: ReactNode; state: ProgressState }) {
    const mark = STATE_MARKS[state]
    return (
        <span className={`invoice-progress-icon invoice-progress-icon--${state}`} aria-hidden="true">
            {icon}
            {mark && (
                <span className="invoice-progress-mark">
                    <FontAwesomeIcon icon={mark} spin={state === 'active'} />
                </span>
            )}
        </span>
    )
}

/** Names the steps, then the corner marks the list uses. */
export function ProgressLegend({ steps, states }: {
    steps: Array<{ key: string; icon: ReactNode; label: string }>
    states: Array<{ state: ProgressState; label: string }>
}) {
    return (
        <div className="invoice-progress-legend">
            <ul>
                {steps.map((step) => (
                    <li key={step.key}>
                        <ProgressIcon icon={step.icon} state="open" />
                        {step.label}
                    </li>
                ))}
            </ul>
            <ul>
                {states.map(({ state, label }) => {
                    const mark = STATE_MARKS[state]
                    return (
                        <li key={state}>
                            <span className={`invoice-progress-legend-mark invoice-progress-legend-mark--${state}`} aria-hidden="true">
                                {mark && <FontAwesomeIcon icon={mark} fixedWidth />}
                            </span>
                            {label}
                        </li>
                    )
                })}
            </ul>
        </div>
    )
}
