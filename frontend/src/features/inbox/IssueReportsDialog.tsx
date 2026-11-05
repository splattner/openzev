import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faPaperPlane } from '@fortawesome/free-solid-svg-icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { YearPicker } from '../../components/YearPicker'
import { formatApiError } from '../../lib/api/errors'
import { issueAnnualStatements, issueFinancialSummaries, issueTariffOverview } from '../../lib/api/inbox'
import { queryKeys } from '../../lib/api/queryKeys'
import { todayBusinessIso } from '../../lib/dates'
import type { DeliveryResult, Participant } from '../../types/api'
import { AudienceFields, type Audience } from './AudienceFields'
import { DeliveryResultNotice } from './DeliveryResultNotice'
import './inbox.css'

export type ReportKind = 'annual_statement' | 'financial_summary' | 'tariff_overview'
const REPORT_KINDS: readonly ReportKind[] = ['annual_statement', 'financial_summary', 'tariff_overview']

type IssueReportsDialogProps = {
  isOpen: boolean
  onClose: () => void
  zevId: string
  participants: readonly Participant[]
}

/** Issue the year's statements or summaries, or the tariff overview, into participants' inboxes (spec §7.2). */
export function IssueReportsDialog({ isOpen, onClose, zevId, participants }: IssueReportsDialogProps) {
  const { t } = useTranslation()
  return (
    <FormModal isOpen={isOpen} title={t('inbox.issue.title')} onClose={onClose} size="md">
      {isOpen ? <IssueForm onClose={onClose} zevId={zevId} participants={participants} /> : null}
    </FormModal>
  )
}

/** The years a report can be issued for: this one and the five before it. */
export function issueYears(today = todayBusinessIso()): number[] {
  const current = Number(today.slice(0, 4))
  return Array.from({ length: 6 }, (_, index) => current - index)
}

function IssueForm({ onClose, zevId, participants }: Omit<IssueReportsDialogProps, 'isOpen'>) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const years = issueYears()
  const [kind, setKind] = useState<ReportKind>('annual_statement')
  // What is usually issued is the year just ended.
  const [year, setYear] = useState(years[1])
  const [audience, setAudience] = useState<Audience>('all')
  const [selected, setSelected] = useState<string[]>([])
  const [result, setResult] = useState<DeliveryResult | null>(null)

  const mutation = useMutation({
    mutationFn: () => {
      const input = { zev: zevId, participantIds: audience === 'selected' ? selected : undefined }
      if (kind === 'tariff_overview') return issueTariffOverview(input)
      return (kind === 'annual_statement' ? issueAnnualStatements : issueFinancialSummaries)({ ...input, year })
    },
    onSuccess: (data) => {
      setResult(data)
      void queryClient.invalidateQueries({ queryKey: queryKeys.inbox.all })
    },
  })

  const invalid = audience === 'selected' && selected.length === 0
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (invalid || mutation.isPending) return
    mutation.mutate()
  }

  if (result) {
    return (
      <div className="grid">
        <DeliveryResultNotice result={result} />
        <div className="dialog-actions">
          <button type="button" className="button button-primary" onClick={onClose}>{t('common.close')}</button>
        </div>
      </div>
    )
  }

  return (
    <form className="inline-form grid" onSubmit={submit} noValidate>
      <label className="grid-span-full">
        <span>{t('inbox.issue.report')}</span>
        <select value={kind} onChange={(event) => setKind(event.target.value as ReportKind)} disabled={mutation.isPending}>
          {REPORT_KINDS.map((value) => <option key={value} value={value}>{t(`inbox.kind.${value}`)}</option>)}
        </select>
        <small className="muted">{t(`inbox.issue.hint.${kind}`)}</small>
      </label>
      {kind !== 'tariff_overview' && (
        <YearPicker years={years} value={year} onChange={setYear} label={t('inbox.issue.year')} className="grid-span-full" disabled={mutation.isPending} />
      )}
      <AudienceFields
        name="inbox-issue-audience"
        audience={audience}
        onAudienceChange={setAudience}
        participants={participants}
        selected={selected}
        onSelectedChange={setSelected}
        allLabel={t(`inbox.issue.audienceAll.${kind}`)}
        disabled={mutation.isPending}
      />
      <p className="muted grid-span-full m-0">{t('inbox.issue.reissueNote')}</p>
      {mutation.isError && (
        <p role="alert" className="text-error grid-span-full m-0">{formatApiError(mutation.error, t('common.error'))}</p>
      )}
      <FormModalFooter
        onCancel={onClose}
        isPending={mutation.isPending}
        disabled={invalid}
        submitIcon={<FontAwesomeIcon icon={faPaperPlane} fixedWidth />}
        submitLabel={t('inbox.issue.submit')}
      />
    </form>
  )
}
