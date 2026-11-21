import { useTranslation } from 'react-i18next'
import { Disclosure } from '../../components/Disclosure'
import type { DynamicTariffSource } from '../../types/api'
import { formatDynamicFetchError } from './errors'

/** The translated fetch failure, with the stored English cause kept on demand. */
export function DynamicFetchFailure({ source, className }: {
    source: Pick<DynamicTariffSource, 'last_fetch_diagnostics' | 'last_fetch_error'>
    className: string
}) {
    const { t } = useTranslation()
    return <>
        <p className={`${className} m-0`}>{formatDynamicFetchError(source, t)}</p>
        {source.last_fetch_error && (
            <Disclosure lazy className="disclosure-sm" summary={t('importDiagnostics.technicalDetails')}>
                {source.last_fetch_error}
            </Disclosure>
        )}
    </>
}
