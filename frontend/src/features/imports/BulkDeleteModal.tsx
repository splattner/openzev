import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faArrowLeft, faTrash, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { CivilDateInput } from '../../components/CivilDateInput'
import { FormModal } from '../../components/FormModal'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'

export type BulkDeleteMode = 'period' | 'all'

interface BulkDeleteModalProps {
    open: boolean
    mode: BulkDeleteMode
    dateFrom: string
    dateTo: string
    armed: boolean
    visibleCount: number
    /** In-scope logs with rows_overwritten > 0: the server rejects the whole
     * selection while any of these is included. */
    protectedCount: number
    /** Preformatted "filename — datetime" labels identifying the blockers. */
    protectedExamples: string[]
    pending: boolean
    /** Selected ZEV name; null deletes across all visible ZEVs. */
    zevName: string | null
    onClose: () => void
    onModeChange: (mode: BulkDeleteMode) => void
    onDateFromChange: (value: string) => void
    onDateToChange: (value: string) => void
    onReview: () => void
    onBack: () => void
    onConfirm: () => void
}

export function BulkDeleteModal(props: BulkDeleteModalProps) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { open, mode, dateFrom, dateTo, armed, visibleCount, protectedCount, protectedExamples, pending, zevName } = props
    const formattedDateFrom = formatShortDate(dateFrom, settings)
    const formattedDateTo = formatShortDate(dateTo, settings)
    const blocked = protectedCount > 0

    return (
        <FormModal isOpen={open} title={t('pages.imports.delete.bulkModalTitle')} onClose={props.onClose} maxWidth="640px">
            <div className="page-stack" style={{ gap: '1rem' }}>
                <p className="muted">{t('pages.imports.delete.overwriteProtected')}</p>
                {!armed ? (
                    <>
                        <p className="muted" style={{ margin: 0 }}>
                            {zevName
                                ? t('pages.imports.delete.bulkDescription', { zevName })
                                : t('pages.imports.delete.bulkDescriptionAll')}
                        </p>

                        <label>
                            <span>{t('pages.imports.delete.modeLabel')}</span>
                            <select value={mode} onChange={(event) => props.onModeChange(event.target.value as BulkDeleteMode)}>
                                <option value="period">{t('pages.imports.delete.modePeriod')}</option>
                                <option value="all">{t('pages.imports.delete.modeAll')}</option>
                            </select>
                        </label>

                        {mode === 'period' && (
                            <>
                                <div className="inline-form grid grid-2">
                                    <label>
                                        <span>{t('pages.imports.delete.dateFrom')}</span>
                                        <CivilDateInput value={dateFrom} onChange={(value) => props.onDateFromChange(value ?? '')} />
                                    </label>
                                    <label>
                                        <span>{t('pages.imports.delete.dateTo')}</span>
                                        <CivilDateInput value={dateTo} onChange={(value) => props.onDateToChange(value ?? '')} />
                                    </label>
                                </div>
                                <p className="muted" style={{ margin: 0, fontSize: '0.85rem' }}>
                                    {t('pages.imports.delete.utcNote')}
                                </p>
                            </>
                        )}

                        <p className="muted" style={{ margin: 0 }}>
                            {t('pages.imports.delete.visibleImpact', { count: visibleCount })}
                        </p>

                        {blocked && (
                            <div>
                                <p className="muted" style={{ margin: '0 0 0.5rem' }}>
                                    {t('pages.imports.delete.blockedNotice', { count: protectedCount })}
                                </p>
                                <ul style={{ margin: '0 0 0.5rem 1.25rem' }}>
                                    {protectedExamples.map((label) => (
                                        <li key={label} className="muted">{label}</li>
                                    ))}
                                </ul>
                                {protectedCount > protectedExamples.length && (
                                    <p className="muted" style={{ margin: 0 }}>
                                        {t('pages.imports.delete.blockedMore', { count: protectedCount - protectedExamples.length })}
                                    </p>
                                )}
                            </div>
                        )}

                        <div className="actions-row actions-row-end">
                            <button className="button button-secondary" type="button" onClick={props.onClose}>
                                <FontAwesomeIcon icon={faXmark} fixedWidth />
                                {t('common.cancel')}
                            </button>
                            <button className="button button-danger" type="button" onClick={props.onReview} disabled={pending || blocked}>
                                <FontAwesomeIcon icon={faTrash} fixedWidth />
                                {t('pages.imports.delete.reviewAction')}
                            </button>
                        </div>
                    </>
                ) : (
                    <>
                        <p style={{ margin: 0 }}>
                            {mode === 'period'
                                ? zevName
                                    ? t('pages.imports.delete.bulkPeriodMessage', { from: formattedDateFrom, to: formattedDateTo, zevName })
                                    : t('pages.imports.delete.bulkPeriodMessageAll', { from: formattedDateFrom, to: formattedDateTo })
                                : zevName
                                    ? t('pages.imports.delete.bulkAllMessage', { zevName })
                                    : t('pages.imports.delete.bulkAllMessageAll')}
                        </p>
                        <p className="muted" style={{ margin: 0 }}>
                            {t('pages.imports.delete.visibleImpact', { count: visibleCount })}{' '}
                            {t('pages.imports.delete.readingImpactUnknown')}
                        </p>
                        {blocked && (
                            <p className="muted" style={{ margin: 0 }}>
                                {t('pages.imports.delete.blockedNotice', { count: protectedCount })}
                            </p>
                        )}

                        <div className="actions-row actions-row-end">
                            <button className="button button-secondary" type="button" onClick={props.onBack}>
                                <FontAwesomeIcon icon={faArrowLeft} fixedWidth />
                                {t('pages.imports.wizard.back')}
                            </button>
                            <button className="button button-danger" type="button" onClick={props.onConfirm} disabled={pending || blocked}>
                                <FontAwesomeIcon icon={faTrash} fixedWidth />
                                {t('pages.imports.delete.confirmAction')}
                            </button>
                        </div>
                    </>
                )}
            </div>
        </FormModal>
    )
}
