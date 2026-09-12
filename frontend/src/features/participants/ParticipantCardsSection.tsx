import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faBan,
    faCopy,
    faDownload,
    faEllipsis,
    faEnvelope,
    faPen,
    faPlus,
    faTrash,
    faTriangleExclamation,
} from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../components/EmptyState'
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
    settings: AppSettings
    onOpenCreateModal: () => void
    onClearFilters: () => void
    onStartEdit: (participant: Participant) => void
    onDownloadContract: (participant: Participant) => void
    onSendOnboardingLink: (participantId: string) => void
    onCopyOnboardingLink: (participantId: string) => void
    onRevokeOnboardingLink: (participantId: string) => void
    onConfirmDelete: (participant: Participant, displayName: string) => void
    onboardingLinkPending: boolean
    deletePendingOrDialogLoading: boolean
    /** Participant id to highlight (deep link `?focus=`), if still visible. */
    focusParticipantId?: string | null
}

function participantValidityBadgeClass(state: ParticipantValidityState): string {
    if (state === 'current') return 'badge badge-success'
    if (state === 'upcoming') return 'badge badge-info'
    return 'badge badge-neutral'
}

function onboardingStatusBadgeClass(status: Participant['onboarding_status']): string {
    if (status === 'active') return 'badge badge-success'
    if (status === 'sent') return 'badge badge-info'
    if (status === 'revoked') return 'badge badge-warning'
    return 'badge badge-neutral'
}

export function ParticipantCardsSection({
    participantCards,
    filteredParticipants,
    settings,
    onOpenCreateModal,
    onClearFilters,
    onStartEdit,
    onDownloadContract,
    onSendOnboardingLink,
    onCopyOnboardingLink,
    onRevokeOnboardingLink,
    onConfirmDelete,
    onboardingLinkPending,
    deletePendingOrDialogLoading,
    focusParticipantId,
}: ParticipantCardsSectionProps) {
    const { t } = useTranslation()

    // Community-wide weight total: an informational indicator only, computed
    // from every card in the section (not the filtered/searched subset) so a
    // search or filter never changes the denominator participants see.
    const totalWeight = participantCards.reduce(
        (sum, { participant }) => sum + Number(participant.allocation_weight || '1'),
        0,
    )

    if (participantCards.length === 0) {
        return (
            <EmptyState
                titleKey="pages.participants.emptyState.title"
                descriptionKey="pages.participants.emptyState.description"
                actions={[
                    {
                        labelKey: 'pages.participants.emptyState.createAction',
                        onClick: onOpenCreateModal,
                        variant: 'primary',
                        icon: faPlus,
                    },
                    { labelKey: 'pages.participants.emptyState.meteringPointsAction', to: '/metering/points', variant: 'secondary' },
                ]}
            />
        )
    }

    if (filteredParticipants.length === 0) {
        return (
            <EmptyState
                titleKey="pages.participants.noResults.title"
                descriptionKey="pages.participants.noResults.description"
                actions={[{ labelKey: 'pages.participants.filters.clear', onClick: onClearFilters, variant: 'secondary' }]}
            />
        )
    }

    return (
        <div className="table-card participant-card-list">
            {filteredParticipants.map(({ participant, warnings, ownerRow, validityState, displayName, address }) => {
                const weight = Number(participant.allocation_weight || '1')
                const weightSharePercent = totalWeight > 0 ? (weight / totalWeight) * 100 : 0
                const menuItems: ActionMenuItem[] = []

                menuItems.push({
                    key: 'send-onboarding-link',
                    label: t('pages.participants.sendOnboardingLink'),
                    icon: <FontAwesomeIcon icon={faEnvelope} fixedWidth />,
                    disabled: onboardingLinkPending || !participant.email,
                    onClick: () => onSendOnboardingLink(participant.id),
                })
                menuItems.push({
                    key: 'copy-onboarding-link',
                    label: t('pages.participants.copyOnboardingLink'),
                    icon: <FontAwesomeIcon icon={faCopy} fixedWidth />,
                    disabled: onboardingLinkPending,
                    onClick: () => onCopyOnboardingLink(participant.id),
                })
                if (participant.onboarding_status === 'sent' || participant.onboarding_status === 'active') {
                    menuItems.push({
                        key: 'revoke-onboarding-link',
                        label: t('pages.participants.revokeOnboardingLink'),
                        icon: <FontAwesomeIcon icon={faBan} fixedWidth />,
                        disabled: onboardingLinkPending,
                        onClick: () => onRevokeOnboardingLink(participant.id),
                    })
                }

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

                return (
                    <article
                        key={participant.id}
                        id={`participant-card-${participant.id}`}
                        className={`participant-card${focusParticipantId === participant.id ? ' participant-card-focus' : ''}`}
                    >
                        <div className="participant-card-header">
                            <div className="participant-card-title">
                                <div className="participant-card-badges">
                                    {ownerRow && <span className="badge badge-info">{t('pages.participants.owner')}</span>}
                                    <span className={participantValidityBadgeClass(validityState)}>
                                        {t(`pages.participants.validity.${validityState}`)}
                                    </span>
                                    <span className={onboardingStatusBadgeClass(participant.onboarding_status)}>
                                        {t(`pages.participants.onboardingStatus.${participant.onboarding_status ?? 'not_sent'}`)}
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
                                <ActionMenu
                                    label={t('pages.participants.moreActions')}
                                    icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                                    items={menuItems}
                                />
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
                                <div className="participant-card-section">
                                    <div className="participant-card-label">{t('pages.participants.form.allocationWeight')}</div>
                                    <div title={t('pages.participants.weightShareHint')}>
                                        {t('pages.participants.weightShare', {
                                            percent: weightSharePercent.toFixed(4),
                                            weight: weight.toFixed(4),
                                            total: totalWeight.toFixed(4),
                                        })}
                                    </div>
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
