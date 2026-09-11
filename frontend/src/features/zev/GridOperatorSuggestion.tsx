import { useMemo, useState } from 'react'
import { useDebouncedValue } from '@mantine/hooks'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faFlask } from '@fortawesome/free-solid-svg-icons'
import { fetchGridOperatorSuggestions } from '../../lib/api/zev'
import { previewVseTariffImport } from '../../lib/api/tariffs'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import type { GridOperator } from '../../types/api'

/** Suggested operators the form has not already accepted — exported for testing in isolation from the query/rendering. */
export function unacceptedOperators(operators: GridOperator[], currentElcomId: number | null | undefined): GridOperator[] {
  return operators.filter((operator) => operator.id !== currentElcomId)
}

/**
 * Which operator's `tariff_url` to offer, if any: the one already accepted,
 * else — only when the postal code resolved to exactly one candidate — that
 * one. A postal code with several operators withholds the URL suggestion
 * until the owner has picked which of them applies; suggesting one at
 * random would be worse than suggesting none.
 */
export function urlSuggestionCandidate(
  operators: GridOperator[],
  currentElcomId: number | null | undefined,
): GridOperator | undefined {
  const matched = operators.find((operator) => operator.id === currentElcomId)
  return matched ?? (operators.length === 1 ? operators[0] : undefined)
}

type GridOperatorSuggestionProps = {
  /** The ZEV's own postal code (grid connection site), not a participant's address. */
  postalCode: string
  /** The form's current elcom id, so a suggestion already accepted stops being offered as one. */
  currentElcomId?: number | null
  /** Current tariff_source_url form value — the URL suggestion is withheld once this is non-blank, so accepting it can never silently overwrite what the owner already set. */
  currentTariffUrl?: string
  /**
   * The ZEV being edited, when there is one. Undefined in the creation
   * wizard and self-setup: those have no zev id yet, so there is nothing to
   * run the validating fetch against, and the URL suggestion is withheld
   * entirely rather than offered unvalidated.
   */
  zevId?: string
  onApplyOperator: (operator: GridOperator) => void
  onApplyTariffUrl: (url: string) => void
}

/**
 * Suggests a grid operator, and — once one is identified and only for an
 * existing ZEV — its published tariff URL, from a postal code.
 *
 * Both are offers, not facts: the postal-code map and the `tariff_url` it
 * carries are ElCom's own register, refreshed once a season and shipped as a
 * fixture (see `zev.grid_operators`). The register can be stale — an
 * operator's own re-upload moves the file faster than ElCom's next refresh —
 * so a URL is never handed to `onApplyTariffUrl` without first being fetched
 * and confirmed to actually contain a tariff document (see #691).
 */
export function GridOperatorSuggestion({
  postalCode,
  currentElcomId,
  currentTariffUrl,
  zevId,
  onApplyOperator,
  onApplyTariffUrl,
}: GridOperatorSuggestionProps) {
  const { t } = useTranslation()
  const [debouncedPostalCode] = useDebouncedValue(postalCode.trim(), 400)

  const suggestionsQuery = useQuery({
    queryKey: queryKeys.zev.gridOperatorSuggestions(debouncedPostalCode),
    queryFn: () => fetchGridOperatorSuggestions(debouncedPostalCode),
    enabled: debouncedPostalCode.length > 0,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })

  const operators = suggestionsQuery.data?.operators ?? []
  const unaccepted = unacceptedOperators(operators, currentElcomId)
  const urlCandidate = urlSuggestionCandidate(operators, currentElcomId)

  const [testedUrl, setTestedUrl] = useState<string | null>(null)
  const testMutation = useMutation({
    mutationFn: (url: string) => {
      if (!zevId) throw new Error('no zev id')
      return previewVseTariffImport({ zev: zevId, url })
    },
    onSuccess: (_result, url) => setTestedUrl(url),
  })

  const showUrlSuggestion = useMemo(
    () => Boolean(zevId && urlCandidate?.tariff_url && !currentTariffUrl?.trim()),
    [zevId, urlCandidate, currentTariffUrl],
  )

  if (unaccepted.length === 0 && !showUrlSuggestion) {
    return null
  }

  return (
    <div className="info-banner" style={{ display: 'grid', gap: '0.6rem' }}>
      {unaccepted.length > 0 && (
        <div>
          <div>
            {unaccepted.length === 1
              ? t('pages.zevSettings.fields.gridOperatorSuggestion.operatorHintOne', { name: unaccepted[0].name })
              : t('pages.zevSettings.fields.gridOperatorSuggestion.operatorHintMany', { count: unaccepted.length })}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginTop: '0.4rem' }}>
            {unaccepted.map((operator) => (
              <button
                key={operator.id}
                type="button"
                className="button button-secondary button-compact"
                onClick={() => onApplyOperator(operator)}
              >
                <FontAwesomeIcon icon={faCheck} fixedWidth />
                {operator.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {showUrlSuggestion && urlCandidate && (
        <div>
          <div>
            {t('pages.zevSettings.fields.gridOperatorSuggestion.urlHint', { name: urlCandidate.name })}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.4rem' }}>
            {testedUrl === urlCandidate.tariff_url ? (
              <button
                type="button"
                className="button button-primary button-compact"
                onClick={() => onApplyTariffUrl(urlCandidate.tariff_url)}
              >
                <FontAwesomeIcon icon={faCheck} fixedWidth />
                {t('pages.zevSettings.fields.gridOperatorSuggestion.useThisUrl')}
              </button>
            ) : (
              <button
                type="button"
                className="button button-secondary button-compact"
                disabled={testMutation.isPending}
                onClick={() => {
                  setTestedUrl(null)
                  testMutation.mutate(urlCandidate.tariff_url)
                }}
              >
                <FontAwesomeIcon icon={faFlask} fixedWidth />
                {testMutation.isPending
                  ? t('pages.zevSettings.fields.gridOperatorSuggestion.testing')
                  : t('pages.zevSettings.fields.gridOperatorSuggestion.testUrl')}
              </button>
            )}
            {testMutation.isError && (
              <span className="error-text">
                {t('pages.zevSettings.fields.gridOperatorSuggestion.testFailed', {
                  error: formatApiError(testMutation.error),
                })}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
