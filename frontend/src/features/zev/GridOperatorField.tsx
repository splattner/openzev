import { useMemo } from 'react'
import { Autocomplete } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchGridOperators } from '../../lib/api/zev'
import { queryKeys } from '../../lib/api/queryKeys'

type GridOperatorFieldProps = {
  /** The operator name as stored on the ZEV — free text, not an id. */
  value: string
  /** ElCom id when the name came from the list, null when it was typed. */
  elcomId?: number | null
  onChange: (next: { grid_operator: string; grid_operator_elcom_id: number | null }) => void
  label: string
}

/**
 * Grid operator (VNB) input, suggesting from the official ElCom list.
 *
 * An `Autocomplete` rather than a `Select`: the list is a suggestion source,
 * not a constraint. A utility missing from ElCom's tariff cube — a recent
 * merger, a small municipal works — must still be enterable, so any text is
 * accepted and `grid_operator_elcom_id` is simply null for it.
 *
 * The id is derived from the name on every change rather than tracked
 * separately, so the two can never disagree: editing a picked name by one
 * character drops the id, which is the honest outcome.
 */
export function GridOperatorField({ value, elcomId, onChange, label }: GridOperatorFieldProps) {
  const { t } = useTranslation()

  const operatorsQuery = useQuery({
    queryKey: queryKeys.zev.gridOperators(),
    queryFn: fetchGridOperators,
    // Reference data refreshed once a tariff year and shipped as a fixture —
    // never worth refetching within a session.
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
  })

  const idsByName = useMemo(() => {
    const map = new Map<string, number>()
    for (const operator of operatorsQuery.data?.operators ?? []) {
      map.set(operator.name, operator.id)
    }
    return map
  }, [operatorsQuery.data])

  const names = useMemo(
    () => (operatorsQuery.data?.operators ?? []).map((operator) => operator.name),
    [operatorsQuery.data],
  )

  return (
    <Autocomplete
      label={label}
      value={value}
      data={names}
      limit={20}
      // The list load is best-effort: if it fails the field keeps working as
      // the plain text input it replaced, which is what a ZEV wizard needs.
      description={
        operatorsQuery.isError
          ? t('pages.zevSettings.fields.gridOperatorUnavailable')
          : elcomId != null
            ? t('pages.zevSettings.fields.gridOperatorMatched')
            : t('pages.zevSettings.fields.gridOperatorHint')
      }
      onChange={(next) =>
        onChange({ grid_operator: next, grid_operator_elcom_id: idsByName.get(next) ?? null })
      }
    />
  )
}
