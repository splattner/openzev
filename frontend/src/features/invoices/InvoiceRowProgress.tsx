import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    type IconDefinition,
    faChartColumn,
    faClipboardCheck,
    faEnvelope,
    faLink,
    faLock,
    faMoneyBillWave,
    faReceipt,
} from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { invoiceStepReasonText } from './invoiceRowText'
import { InvoiceLink } from '../../components/InvoicePresentation'
import { ProgressIcon, ProgressLegend } from '../../components/ProgressIcon'
import type { InvoicePeriodParticipantRow } from '../../types/api'
import {
    INVOICE_PROGRESS_STEPS,
    invoiceRowProgress,
    type InvoiceProgressStep,
    type InvoiceRowStep,
    type InvoiceRowWork,
    type InvoiceStepReason,
    type InvoiceStepState,
} from './invoiceRowState'

/** Match metering and invoice icons to the sidebar. */
const STEP_ICONS: Record<InvoiceProgressStep, IconDefinition> = {
    metering: faChartColumn,
    invoice: faReceipt,
    approved: faClipboardCheck,
    sent: faEnvelope,
    paid: faMoneyBillWave,
}

function StepIcon({ step, state, reason }: { step: InvoiceProgressStep; state: InvoiceStepState; reason?: InvoiceStepReason }) {
    // A blocked invoice step is locked by another invoice, not merely late.
    return <ProgressIcon icon={<FontAwesomeIcon icon={reason === 'conflict' ? faLock : STEP_ICONS[step]} fixedWidth />} state={state} />
}

type InvoiceRowProgressProps = {
    row: InvoicePeriodParticipantRow
    /** The period the page shows; links keep it for the way back. */
    period: { period_start: string; period_end: string }
    work?: InvoiceRowWork
}

/** Five workflow steps, or a representative link for an already billed period. */
export function InvoiceRowProgress({ row, period, work }: InvoiceRowProgressProps) {
    const { t } = useTranslation()
    const steps = invoiceRowProgress(row, work)

    if (!steps) {
        const covering = row.generation_eligibility
        return (
            <span className="invoice-progress-covered" title={t('pages.invoices.covered.hint')}>
                <FontAwesomeIcon icon={faLink} fixedWidth aria-hidden="true" />
                {t('pages.invoices.covered.label')}{' '}
                {covering?.invoice_id && covering.invoice_number ? (
                    <InvoiceLink
                        invoice={{ id: covering.invoice_id, invoice_number: covering.invoice_number }}
                        from="/billing/invoices"
                        period={period}
                    />
                ) : null}
            </span>
        )
    }

    // Say what the step means for this row: "Invoice created",
    // "Not approved yet" — or what is under way or wrong.
    const labelOf = ({ step, state, reason }: InvoiceRowStep) => reason
        ? invoiceStepReasonText(t, reason, row)
        : t(`pages.invoices.progress.${state === 'done' ? 'done' : 'open'}.${step}`)
    // A card has room for words, not for a legend to decode five icons. A
    // problem already reads as red text under the name; this is the next step.
    const next = steps.find(({ state }) => state === 'open' || state === 'active')

    return (
        <div className="invoice-progress-wrap">
            <ol className="invoice-progress" aria-label={t('pages.invoices.progress.label')}>
                {steps.map((entry) => {
                    const label = labelOf(entry)
                    return (
                        <li key={entry.step} className="invoice-progress-step" title={label} data-step={entry.step} data-state={entry.state}>
                            <StepIcon step={entry.step} state={entry.state} reason={entry.reason} />
                            <span className="visually-hidden">{label}</span>
                        </li>
                    )
                })}
            </ol>
            {next && <span className="invoice-progress-next" aria-hidden="true">{labelOf(next)}</span>}
        </div>
    )
}

/** Names the steps and completion marks. */
export function InvoiceProgressLegend() {
    const { t } = useTranslation()
    return (
        <ProgressLegend
            steps={INVOICE_PROGRESS_STEPS.map((step) => ({
                key: step,
                icon: <FontAwesomeIcon icon={STEP_ICONS[step]} fixedWidth />,
                label: t(`pages.invoices.progress.steps.${step}`),
            }))}
            states={(['done', 'active', 'issue'] as const).map((state) => ({ state, label: t(`pages.invoices.progress.states.${state}`) }))}
        />
    )
}
