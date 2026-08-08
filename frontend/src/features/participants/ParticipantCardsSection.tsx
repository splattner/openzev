import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faDownload,
    faEllipsis,
    faEnvelope,
    faPen,
    faPlus,
    faTrash,
    faTriangleExclamation,
} from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { ActionMenu, type ActionMenuItem } from '../../components/ActionMenu'
import { formatShortDate } from '../../lib/appSettings'
import type { AppSettings, Participant } from '../../types/api'
import type { ParticipantValidityState } from './types'

type ParticipantCardEntry = {
    participant: Participant
    warnings: string[]
    ownerRow: boolean
    validityState: ParticipantValidityState
    displayName: string
    address: string
}

type ParticipantCardsSectionProps = {
    participantCards: ParticipantCardEntry[]
    filteredParticipants: ParticipantCardEntry[]
    hasFilters: boolean
    settings: AppSettings
    onOpenCreateModal: () => void
    onClearFilters: () => void
    onStartEdit: (participant: Participant) => void
    onDownloadContract: (participant: Participant) => void
    onInvite: (participantId: string) => void
    onConfirmDelete: (participant: Participant, displayName: string) => void
    invitationPending: boolean
    deletePendingOrDialogLoading: boolean
}

function participantValidityBadgeClass(state: ParticipantValidityState): string {
    if (state === 'current') return 'badge badge-success'
    if (state === 'upcoming') return 'badge badge-info'
    return 'badge badge-neutral'
}

export function ParticipantCardsSection({
    participantCards,
    filteredParticipants,
    hasFilters,
    settings,
    onOpenCreateModal,
    onClearFilters,
    onStartEdit,
    onDownloadContract,
    onInvite,
    onConfirmDelete,
    invitationPending,
    deletePendingOrDialogLoading,
}: ParticipantCardsSectionProps) {
    const { t } = useTranslation()

    if (participantCards.length === 0) {
        return (
            <section className="card" style={{ display: 'grid', gap: '0.75rem' }}>
                <h3 style={{ margin: 0 }}>{t('pages.participants.emptyState.title')}</h3>
                <p className="muted" style={{ margin: 0 }}>{t('pages.participants.emptyState.description')}</p>
                <div>
                    <button className="button button-primary" type="button" onClick={onOpenCreateModal}>
                        <FontAwesomeIcon icon={faPlus} fixedWidth />
                        {t('pages.participants.emptyState.createAction')}
                    </button>
                </div>
            </section>
        )
    }

    if (filteredParticipants.length === 0) {
        return (
            <section className="card" style={{ display: 'grid', gap: '0.75rem' }}>
                <h3 style={{ margin: 0 }}>{t('pages.participants.noResults.title')}</h3>
                <p className="muted" style={{ margin: 0 }}>{t('pages.participants.noResults.description')}</p>
                {hasFilters && (
                    <div>
                        <button className="button button-secondary" type="button" onClick={onClearFilters}>
                            {t('pages.participants.filters.clear')}
                        </button>
                    </div>
                )}
            </section>
        )
    }

    return (
        <div className="table-card participant-card-list">
            {filteredParticipants.map(({ participant, warnings, ownerRow, validityState, displayName, address }) => {
                const menuItems: ActionMenuItem[] = []

                menuItems.push({
                    key: 'invitation',
                    label: t('pages.participants.sendInvitation'),
                    icon: <FontAwesomeIcon icon={faEnvelope} fixedWidth />,
                    disabled: invitationPending || !participant.email,
                    onClick: () => onInvite(participant.id),
                })

                if (!ownerRow) {
                    menuItems.push({
                        key: 'delete',
                        label: t('common.delete'),
                        icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
                        disabled: deletePendingOrDialogLoading,
                        danger: true,
                        onClick: () => onConfirmDelete(participant, displayName),
                    })
                }

                const directAction = menuItems.length === 1 && !ownerRow ? menuItems[0] : null
                const overflowItems = directAction ? [] : menuItems

                return (
                    <article key={participant.id} className="participant-card">
                        <div className="participant-card-header">
                            <div className="participant-card-title">
                                <div className="participant-card-badges">
                                    {ownerRow && <span className="badge badge-info">{t('pages.participants.owner')}</span>}
                                    <span className={participantValidityBadgeClass(validityState)}>
                                        {t(`pages.participants.validity.${validityState}`)}
                                    </span>
                                    {warnings.length > 0 && (
                                        <span className="badge badge-warning">
                                            <FontAwesomeIcon icon={faTriangleExclamation} fixedWidth />
                                            {t('pages.participants.attentionNeeded')}
                                        </span>
                                    )}
                                </div>
                                <strong>{displayName}</strong>
                            </div>

                            <div className="participant-card-actions">
                                <button className="button button-primary button-compact" type="button" onClick={() => onStartEdit(participant)}>
                                    <FontAwesomeIcon icon={faPen} fixedWidth />
                                    {t('common.edit')}
                                </button>
                                <button className="button button-secondary button-compact" type="button" onClick={() => onDownloadContract(participant)}>
                                    <FontAwesomeIcon icon={faDownload} fixedWidth />
                                    {t('pages.participants.downloadContract')}
                                </button>
                                {directAction && (
                                    <button
                                        className={`button ${directAction.danger ? 'button-danger' : 'button-secondary'} button-compact`}
                                        type="button"
                                        disabled={directAction.disabled}
                                        onClick={directAction.onClick}
                                    >
                                        {directAction.icon}
                                        {directAction.label}
                                    </button>
                                )}
                                {overflowItems.length > 0 && (
                                    <ActionMenu
                                        label={t('pages.participants.moreActions')}
                                        icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                                        items={overflowItems}
                                    />
                                )}
                            </div>
                        </div>

                        <div className="participant-card-body">
                            <div className="participant-card-grid">
                                <div className="participant-card-section">
                                    <div className="participant-card-label">{t('pages.participants.section.contact')}</div>
                                    <div>{participant.email || t('pages.participants.noEmailValue')}</div>
                                    <div className="muted">{participant.phone || t('pages.participants.noPhone')}</div>
                                </div>
                                <div className="participant-card-section">
                                    <div className="participant-card-label">{t('pages.participants.section.address')}</div>
                                    <div>{address || t('pages.participants.noAddressValue')}</div>
                                </div>
                                <div className="participant-card-section">
                                    <div className="participant-card-label">{t('pages.participants.section.validity')}</div>
                                    <div>{formatShortDate(participant.valid_from, settings)}</div>
                                    <div className="muted">{participant.valid_to ? formatShortDate(participant.valid_to, settings) : t('pages.participants.openEnded')}</div>
                                </div>
                            </div>

                            {warnings.length > 0 && (
                                <div className="participant-warning-list">
                                    {warnings.map((warning) => (
                                        <span key={warning} className="badge badge-warning">{warning}</span>
                                    ))}
                                </div>
                            )}
                        </div>
                    </article>
                )
            })}
        </div>
    )
}
