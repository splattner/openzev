import { useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faArrowLeft, faDownload, faTriangleExclamation } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { applyVseTariffImport, previewVseTariffImport } from '../../lib/api/tariffs'
import { useToast } from '../../lib/toast'
import { invalidateTariffQueries } from './invalidate'
import { MONTH_KEYS, formatSeason } from './recurrence'
import {
    defaultBillingModes,
    isSelectable,
    recommendedKeys,
    selectionFor,
    toggleKey,
    trimPrice,
} from './vseImportSelection'
import type {
    VseTariffCandidate,
    VseTariffCandidateStatus,
    VseTariffImportPreview,
    VseTariffImportResult,
} from '../../types/api'

type VseTariffImportModalProps = {
    isOpen: boolean
    onClose: () => void
    zevId: string
    /** The address already stored on the ZEV, so a yearly refresh is one click. */
    initialUrl: string
}

const CATEGORY_ORDER: VseTariffCandidate['category'][] = ['energy', 'grid_fees', 'levies', 'metering']

const STATUS_BADGE: Record<VseTariffCandidateStatus, string> = {
    new: 'badge-success',
    new_version: 'badge-info',
    duplicate: 'badge-neutral',
    conflict: 'badge-warning',
    unsupported: 'badge-danger',
}

function errorDetail(error: unknown, fallback: string): string {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    return typeof detail === 'string' && detail ? detail : fallback
}

export function VseTariffImportModal({ isOpen, onClose, zevId, initialUrl }: VseTariffImportModalProps) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()

    const [url, setUrl] = useState(initialUrl)
    const [preview, setPreview] = useState<VseTariffImportPreview | null>(null)
    const [result, setResult] = useState<VseTariffImportResult | null>(null)
    const [selected, setSelected] = useState<Set<string>>(new Set())
    // Kept apart from `selected` so clearing and re-ticking rows does not throw
    // away a decision the user already made about how a fee is billed.
    const [modeByKey, setModeByKey] = useState<Record<string, string>>({})
    const [rememberUrl, setRememberUrl] = useState(true)

    const previewMutation = useMutation({
        mutationFn: previewVseTariffImport,
        onSuccess: (data) => {
            setPreview(data)
            setSelected(recommendedKeys(data.candidates))
            setModeByKey(defaultBillingModes(data.candidates))
        },
        onError: (error) =>
            pushToast(errorDetail(error, t('pages.tariffs.import.errors.previewFailed')), 'error'),
    })

    const applyMutation = useMutation({
        mutationFn: applyVseTariffImport,
        onSuccess: (data) => {
            setResult(data)
            invalidateTariffQueries(queryClient, zevId)
            if (data.created.length > 0) {
                pushToast(t('pages.tariffs.import.messages.imported', { count: data.created.length }), 'success')
            }
        },
        onError: (error) =>
            pushToast(errorDetail(error, t('pages.tariffs.import.errors.applyFailed')), 'error'),
    })

    const grouped = useMemo(() => {
        const candidates = preview?.candidates ?? []
        return CATEGORY_ORDER.map((category) => ({
            category,
            candidates: candidates.filter((candidate) => candidate.category === category),
        })).filter((group) => group.candidates.length > 0)
    }, [preview])

    const selectable = useMemo(
        () => (preview?.candidates ?? []).filter(isSelectable),
        [preview],
    )

    function reset() {
        setPreview(null)
        setResult(null)
        setSelected(new Set())
        setModeByKey({})
        previewMutation.reset()
        applyMutation.reset()
    }

    function handleClose() {
        reset()
        onClose()
    }

    function toggle(key: string) {
        setSelected((current) => toggleKey(current, key))
    }

    function submitUrl(event: FormEvent) {
        event.preventDefault()
        previewMutation.mutate({ zev: zevId, url: url.trim() || undefined })
    }

    function submitImport() {
        if (!preview || selected.size === 0) return
        applyMutation.mutate({
            zev: zevId,
            url: preview.source_url,
            selections: preview.candidates
                .filter((candidate) => selected.has(candidate.key))
                .map((candidate) => selectionFor(candidate, modeByKey[candidate.key])),
            document_digest: preview.document_digest,
            remember_url: rememberUrl,
        })
    }

    const step: 'url' | 'preview' | 'result' = result ? 'result' : preview ? 'preview' : 'url'

    return (
        <FormModal
            isOpen={isOpen}
            title={t('pages.tariffs.import.title')}
            onClose={handleClose}
            maxWidth="1000px"
        >
            {step === 'url' && (
                <form onSubmit={submitUrl} className="page-stack">
                    <p className="muted">{t('pages.tariffs.import.intro')}</p>
                    <label>
                        <span>{t('pages.tariffs.import.urlLabel')}</span>
                        <input
                            type="url"
                            value={url}
                            placeholder="https://…/tarife.json"
                            onChange={(event) => setUrl(event.target.value)}
                            required
                        />
                        <small className="muted">{t('pages.tariffs.import.urlHint')}</small>
                    </label>
                    <div className="actions-row actions-row-end">
                        <button className="button button-secondary" type="button" onClick={handleClose}>
                            {t('common.cancel')}
                        </button>
                        <button className="button button-primary" type="submit" disabled={previewMutation.isPending}>
                            <FontAwesomeIcon icon={faDownload} fixedWidth />
                            {previewMutation.isPending
                                ? t('pages.tariffs.import.loading')
                                : t('pages.tariffs.import.load')}
                        </button>
                    </div>
                </form>
            )}

            {step === 'preview' && preview && (
                <div className="page-stack">
                    <div>
                        <p style={{ margin: 0 }}>
                            <strong>{t('pages.tariffs.import.documentFrom', { name: preview.dso_name })}</strong>
                        </p>
                        <p className="muted" style={{ margin: 0, wordBreak: 'break-all' }}>{preview.source_url}</p>
                    </div>

                    {preview.errors.length > 0 && (
                        <div className="card error-banner">
                            <p style={{ marginTop: 0 }}>
                                <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />{' '}
                                {t('pages.tariffs.import.documentErrors', { count: preview.errors.length })}
                            </p>
                            <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                                {preview.errors.map((error) => (
                                    <li key={`${error.tariff}-${error.error}`}>
                                        <strong>{error.tariff}</strong>: {error.error}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    <div className="actions-row actions-row-wrap">
                        <span className="muted">
                            {t('pages.tariffs.import.selectedCount', {
                                count: selected.size,
                                total: selectable.length,
                            })}
                        </span>
                        <button
                            className="button button-secondary"
                            type="button"
                            onClick={() =>
                                setSelected(recommendedKeys(preview.candidates))
                            }
                        >
                            {t('pages.tariffs.import.selectRecommended')}
                        </button>
                        <button className="button button-secondary" type="button" onClick={() => setSelected(new Set())}>
                            {t('pages.tariffs.import.selectNone')}
                        </button>
                    </div>

                    <p className="muted" style={{ margin: 0 }}>
                        {t('pages.tariffs.import.billingModeHint')}
                    </p>

                    {grouped.map((group) => (
                        <section key={group.category} className="card">
                            <h3 style={{ marginTop: 0 }}>{t(`pages.tariffs.categories.${group.category}`)}</h3>
                            <div className="data-table table-scroll">
                                <table>
                                    <thead>
                                        <tr>
                                            <th aria-label={t('pages.tariffs.import.columns.select')} />
                                            <th>{t('pages.tariffs.import.columns.tariff')}</th>
                                            <th>{t('pages.tariffs.import.columns.price')}</th>
                                            <th>{t('pages.tariffs.import.columns.billingMode')}</th>
                                            <th>{t('pages.tariffs.import.columns.validity')}</th>
                                            <th>{t('pages.tariffs.import.columns.status')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {group.candidates.map((candidate) => (
                                            <CandidateRow
                                                key={candidate.key}
                                                candidate={candidate}
                                                checked={selected.has(candidate.key)}
                                                onToggle={() => toggle(candidate.key)}
                                                billingMode={modeByKey[candidate.key] ?? candidate.billing_mode}
                                                onBillingModeChange={(mode) =>
                                                    setModeByKey((current) => ({ ...current, [candidate.key]: mode }))
                                                }
                                            />
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </section>
                    ))}

                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <input
                            type="checkbox"
                            checked={rememberUrl}
                            onChange={(event) => setRememberUrl(event.target.checked)}
                        />
                        <span>{t('pages.tariffs.import.rememberUrl')}</span>
                    </label>

                    <div className="actions-row actions-row-end">
                        <button className="button button-secondary" type="button" onClick={reset}>
                            <FontAwesomeIcon icon={faArrowLeft} fixedWidth />
                            {t('pages.tariffs.import.back')}
                        </button>
                        <button
                            className="button button-primary"
                            type="button"
                            onClick={submitImport}
                            disabled={selected.size === 0 || applyMutation.isPending}
                        >
                            {applyMutation.isPending
                                ? t('pages.tariffs.import.applying')
                                : t('pages.tariffs.import.apply', { count: selected.size })}
                        </button>
                    </div>
                </div>
            )}

            {step === 'result' && result && (
                <div className="page-stack">
                    <ResultList title={t('pages.tariffs.import.result.created')} empty={t('pages.tariffs.import.result.none')}>
                        {result.created.map((item) => (
                            <li key={`${item.name}-${item.valid_from}`}>
                                {item.name} — {t(`pages.tariffs.billingModes.${item.billing_mode}`)} —{' '}
                                {item.valid_from} … {item.valid_to ?? t('pages.tariffs.openEnded')}
                            </li>
                        ))}
                    </ResultList>
                    {result.skipped.length > 0 && (
                        <ResultList title={t('pages.tariffs.import.result.skipped')}>
                            {result.skipped.map((item) => (
                                <li key={`${item.name}-${item.reason}`}>
                                    <strong>{item.name}</strong>: {item.reason}
                                </li>
                            ))}
                        </ResultList>
                    )}
                    {result.errors.length > 0 && (
                        <ResultList title={t('pages.tariffs.import.result.errors')}>
                            {result.errors.map((item) => (
                                <li key={`${item.name}-${item.error}`}>
                                    <strong>{item.name}</strong>: {item.error}
                                </li>
                            ))}
                        </ResultList>
                    )}
                    <div className="actions-row actions-row-end">
                        <button className="button button-primary" type="button" onClick={handleClose}>
                            {t('common.close')}
                        </button>
                    </div>
                </div>
            )}
        </FormModal>
    )
}

function ResultList({ title, empty, children }: { title: string; empty?: string; children: React.ReactNode }) {
    const hasItems = Array.isArray(children) ? children.length > 0 : Boolean(children)
    return (
        <section>
            <h3 style={{ marginTop: 0 }}>{title}</h3>
            {hasItems ? (
                <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>{children}</ul>
            ) : (
                <p className="muted" style={{ margin: 0 }}>{empty}</p>
            )}
        </section>
    )
}

function CandidateRow({
    candidate,
    checked,
    onToggle,
    billingMode,
    onBillingModeChange,
}: {
    candidate: VseTariffCandidate
    checked: boolean
    onToggle: () => void
    billingMode: string
    onBillingModeChange: (mode: string) => void
}) {
    const { t } = useTranslation()
    const selectable = isSelectable(candidate)

    return (
        <tr>
            <td>
                <input
                    type="checkbox"
                    checked={checked}
                    disabled={!selectable}
                    onChange={onToggle}
                    aria-label={candidate.name}
                />
            </td>
            <td>
                <div>
                    {candidate.name}
                    {candidate.standard_basegroup && (
                        <span className="badge badge-info" style={{ marginLeft: '0.5rem' }}>
                            {t('pages.tariffs.import.standardBadge')}
                        </span>
                    )}
                </div>
                {candidate.source_customer_type && (
                    <small className="muted">{candidate.source_customer_type}</small>
                )}
                {candidate.warnings.map((warning) => (
                    <small key={warning} className="muted" style={{ display: 'block' }}>
                        <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth /> {warning}
                    </small>
                ))}
            </td>
            <td>
                <CandidatePrice candidate={candidate} />
            </td>
            <td>
                {candidate.billing_mode_options.length > 0 ? (
                    <select
                        value={billingMode}
                        disabled={!selectable}
                        onChange={(event) => onBillingModeChange(event.target.value)}
                        aria-label={`${t('pages.tariffs.import.columns.billingMode')} — ${candidate.name}`}
                    >
                        {candidate.billing_mode_options.map((mode) => (
                            <option key={mode} value={mode}>
                                {t(`pages.tariffs.billingModes.${mode}`)}
                            </option>
                        ))}
                    </select>
                ) : (
                    <span className="muted">{t(`pages.tariffs.billingModes.${candidate.billing_mode}`)}</span>
                )}
            </td>
            <td>
                {candidate.valid_from} … {(candidate.effective_valid_to ?? candidate.valid_to) ?? t('pages.tariffs.openEnded')}
            </td>
            <td>
                <span className={`badge ${STATUS_BADGE[candidate.status]}`}>
                    {t(`pages.tariffs.import.status.${candidate.status}`)}
                </span>
                {candidate.detail && <small className="muted" style={{ display: 'block' }}>{candidate.detail}</small>}
            </td>
        </tr>
    )
}

function CandidatePrice({ candidate }: { candidate: VseTariffCandidate }) {
    const { t } = useTranslation()
    const monthNames = MONTH_KEYS.map(
        (key) => t(`pages.tariffs.monthsShort.${key}` as Parameters<typeof t>[0]),
    )

    if (candidate.billing_mode !== 'energy') {
        return (
            <span>
                {t('pages.tariffs.import.monthlyFee', { amount: trimPrice(candidate.fixed_price_chf ?? '0') })}
            </span>
        )
    }
    return (
        <span>
            {candidate.periods.map((period, index) => (
                <span key={`${period.period_type}-${period.time_from}-${index}`} style={{ display: 'block' }}>
                    {t(`pages.tariffs.periodTypes.${period.period_type}`)}{' '}
                    {t('pages.tariffs.import.perKwh', { amount: trimPrice(period.price_chf_per_kwh) })}
                    {period.time_from && period.time_to
                        ? ` (${period.time_from.slice(0, 5)}–${period.time_to.slice(0, 5)})`
                        : ''}
                    {/* Without it, a winter and a summer price read as two
                        unexplained rows for the same band. */}
                    {formatSeason(period.months, monthNames) && ` · ${formatSeason(period.months, monthNames)}`}
                </span>
            ))}
        </span>
    )
}
