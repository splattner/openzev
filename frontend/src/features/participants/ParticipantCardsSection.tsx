import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import {
    faArrowRight,
    faAt,
    faBan,
    faBuilding,
    faCopy,
    faDownload,
    faEllipsis,
    faEnvelope,
    faLink,
    faLinkSlash,
    faLocationDot,
    faPen,
    faPlus,
    faTrash,
} from '@fortawesome/free-solid-svg-icons'
import type { TFunction } from 'i18next'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../components/EmptyState'
import { ActionMenu, type ActionMenuItem } from '../../components/ActionMenu'
import { PlugIcon } from '../../components/IconSvg'
import { ProgressIcon, ProgressLegend, type ProgressState } from '../../components/ProgressIcon'
import { formatShortDate } from '../../lib/appSettings'
import { formatNumber } from '../../lib/numbers'
import type { AppSettings, Participant, PartyRoleName } from '../../types/api'
import type { ParticipantValidityState } from './types'
import type { ParticipantIssue } from './participantIssues'

type ParticipantCardEntry = {
    participant: Participant
    /** What the participant still lacks (`participantIssues`). */
    issues: ParticipantIssue[]
    /** The party's roles held today (#761). */
    roles: PartyRoleName[]
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
    /** Set when the default view is empty only because every participation has ended. */
    onShowEnded?: () => void
    onStartEdit: (participant: Participant) => void
    onDownloadContract: (participant: Participant) => void
    onSendOnboardingLink: (participantId: string) => void
    onCopyOnboardingLink: (participantId: string) => void
    onRevokeOnboardingLink: (participantId: string) => void
    onConfirmDelete: (participant: Participant, displayName: string) => void
    /** Admin-only: attach an existing account, or detach the linked one. */
    canLinkAccount: boolean
    canUnlinkAccount: boolean
    onLinkAccount: (participant: Participant, displayName: string) => void
    onUnlinkAccount: (participant: Participant, displayName: string) => void
    accountActionPending: boolean
    onboardingLinkPending: boolean
    deletePendingOrDialogLoading: boolean
    /** Participant id to highlight (deep link `?focus=`), if still visible. */
    focusParticipantId?: string | null
    /** A viewer reads only (#761): no create, edit, onboarding, linking or delete. */
    readOnly?: boolean
}

type StatusStep = 'email' | 'address' | 'meteringPoint' | 'invitation'

const STATUS_ICONS: Record<StatusStep, ReactNode> = {
    email: <FontAwesomeIcon icon={faAt} fixedWidth />,
    address: <FontAwesomeIcon icon={faLocationDot} fixedWidth />,
    meteringPoint: <PlugIcon />,
    invitation: <FontAwesomeIcon icon={faEnvelope} fixedWidth />,
}

function validityBadgeClass(state: ParticipantValidityState): string {
    return state === 'upcoming' ? 'badge badge-info' : 'badge badge-neutral'
}

type StatusEntry = {
    step: StatusStep
    state: ProgressState
    label: string
    /** How a writer fixes an issue: the edit dialog, or assigning a metering point. */
    fix?: 'edit' | 'meteringPoints'
}

function statusSteps(participant: Participant, issues: ParticipantIssue[], address: string, settings: AppSettings, t: TFunction): StatusEntry[] {
    const status = participant.onboarding_status ?? 'not_sent'
    const expiresAt = participant.onboarding_link_expires_at
    // The link's state, not portal access: setting a password revokes the link.
    return [
        issues.includes('noEmail')
            ? { step: 'email', state: 'issue', label: t('pages.participants.warnings.noEmail'), fix: 'edit' }
            : { step: 'email', state: 'done', label: participant.email },
        issues.includes('noAddress')
            ? { step: 'address', state: 'issue', label: t('pages.participants.warnings.noAddress'), fix: 'edit' }
            : { step: 'address', state: 'done', label: address },
        issues.includes('noMeteringPoint')
            ? { step: 'meteringPoint', state: 'issue', label: t('pages.participants.warnings.noMeteringPoint'), fix: 'meteringPoints' }
            : { step: 'meteringPoint', state: 'done', label: t('pages.participants.status.meteringPointAssigned') },
        {
            step: 'invitation',
            state: status === 'active' ? 'done' : 'open',
            label: t(`pages.participants.status.invitationState.${status}`, { date: expiresAt ? formatShortDate(expiresAt, settings) : '' }),
        },
    ]
}

/** A missing detail as the way to fix it. The icon variant repeats the red text
 * for the mouse, so it stays out of the tab order and the accessibility tree. */
function IssueControl({ entry, participant, readOnly, onStartEdit, iconOnly = false, children }: {
    entry: StatusEntry
    participant: Participant
    readOnly: boolean
    onStartEdit: (participant: Participant) => void
    iconOnly?: boolean
    children: ReactNode
}) {
    const { t } = useTranslation()
    const className = iconOnly ? 'participant-fix participant-fix--icon' : 'participant-fix'
    if (readOnly || !entry.fix) return <span className={className}>{children}</span>
    const label = `${entry.label} – ${t(`pages.participants.status.fix.${entry.fix}`)}`
    const quiet = iconOnly ? { tabIndex: -1, 'aria-hidden': true } : { title: label, 'aria-label': label }
    if (entry.fix === 'meteringPoints') {
        return <Link className={className} to="/metering/points" {...quiet}>{children}</Link>
    }
    return <button type="button" className={className} onClick={() => onStartEdit(participant)} {...quiet}>{children}</button>
}

export function ParticipantCardsSection({
    participantCards,
    filteredParticipants,
    settings,
    onOpenCreateModal,
    onClearFilters,
    onShowEnded,
    onStartEdit,
    onDownloadContract,
    onSendOnboardingLink,
    onCopyOnboardingLink,
    onRevokeOnboardingLink,
    onConfirmDelete,
    canLinkAccount,
    canUnlinkAccount,
    onLinkAccount,
    onUnlinkAccount,
    accountActionPending,
    onboardingLinkPending,
    deletePendingOrDialogLoading,
    focusParticipantId,
    readOnly = false,
}: ParticipantCardsSectionProps) {
    const { t } = useTranslation()

    // Use all current memberships, not just the visible rows.
    const currentTotalWeight = participantCards.reduce(
        (sum, { participant, validityState }) => validityState === 'current'
            ? sum + Number(participant.allocation_weight || '1')
            : sum,
        0,
    )

    const formattedTotal = formatNumber(currentTotalWeight, { maxDecimals: 4 })

    if (participantCards.length === 0) {
        return (
            <EmptyState
                titleKey="pages.participants.emptyState.title"
                descriptionKey="pages.participants.emptyState.description"
                actions={[
                    ...(readOnly ? [] : [{
                        labelKey: 'pages.participants.emptyState.createAction',
                        onClick: onOpenCreateModal,
                        variant: 'primary' as const,
                        icon: faPlus,
                    }]),
                    { labelKey: 'pages.participants.emptyState.meteringPointsAction', to: '/metering/points', variant: 'secondary' },
                ]}
            />
        )
    }

    if (filteredParticipants.length === 0 && onShowEnded) {
        return (
            <EmptyState
                titleKey="pages.participants.noCurrent.title"
                descriptionKey="pages.participants.noCurrent.description"
                actions={[{ labelKey: 'pages.participants.noCurrent.showEnded', onClick: onShowEnded, variant: 'secondary' }]}
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
        <>
            <div className="table-card invoice-rows participant-rows">
                {/* Explicit roles keep table semantics when narrow containers turn
                    the table into cards with display: block. */}
                <table role="table">
                    <thead role="rowgroup">
                        <tr role="row">
                            <th role="columnheader" scope="col">{t('pages.participants.col.participant')}</th>
                            <th role="columnheader" scope="col">{t('pages.participants.col.address')}</th>
                            <th role="columnheader" scope="col">{t('pages.participants.col.validity')}</th>
                            <th role="columnheader" scope="col">{t('pages.participants.col.status')}</th>
                            <th role="columnheader" scope="col" className="numeric" title={t('pages.participants.weightShareHint')}>
                                {t('pages.participants.form.allocationWeight')}
                            </th>
                            <th role="columnheader" scope="col" className="invoice-actions-cell">
                                <span className="visually-hidden">{t('pages.participants.col.actions')}</span>
                            </th>
                        </tr>
                    </thead>
                    <tbody role="rowgroup">
                        {filteredParticipants.map(({ participant, issues, roles, validityState, displayName, address }) => {
                            const isCurrent = validityState === 'current'
                            const weight = Number(participant.allocation_weight || '1')
                            const formattedWeight = formatNumber(weight, { maxDecimals: 4 })
                            const formattedPercent = formatNumber(currentTotalWeight > 0 ? (weight / currentTotalWeight) * 100 : 0, { maxDecimals: 2 })
                            const street = [participant.address_line1, participant.address_line2].filter(Boolean).join(', ')
                            const place = [participant.postal_code, participant.city].filter(Boolean).join(' ')
                            const steps = statusSteps(participant, issues, address, settings, t)
                            const nameLabel = (
                                <>
                                    {participant.kind === 'organisation' && (
                                        <FontAwesomeIcon
                                            icon={faBuilding}
                                            fixedWidth
                                            title={t('pages.participants.kind.organisation')}
                                            className="invoice-row-kind"
                                        />
                                    )}
                                    <strong>{displayName}</strong>
                                </>
                            )
                            const menuItems: ActionMenuItem[] = []

                            if (!readOnly) {
                                menuItems.push({
                                    key: 'edit',
                                    label: t('common.edit'),
                                    icon: <FontAwesomeIcon icon={faPen} fixedWidth />,
                                    onClick: () => onStartEdit(participant),
                                })
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

                                if (participant.user == null && canLinkAccount) {
                                    menuItems.push({
                                        key: 'link-account',
                                        label: t('pages.accounts.linkExisting'),
                                        icon: <FontAwesomeIcon icon={faLink} fixedWidth />,
                                        disabled: accountActionPending,
                                        onClick: () => onLinkAccount(participant, displayName),
                                    })
                                }
                                if (participant.user != null && canUnlinkAccount) {
                                    menuItems.push({
                                        key: 'unlink-account',
                                        label: t('pages.accounts.unlink'),
                                        icon: <FontAwesomeIcon icon={faLinkSlash} fixedWidth />,
                                        disabled: accountActionPending,
                                        onClick: () => onUnlinkAccount(participant, displayName),
                                    })
                                }

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
                                <tr
                                    key={participant.id}
                                    id={`participant-row-${participant.id}`}
                                    role="row"
                                    className={focusParticipantId === participant.id ? 'participant-row-focus' : undefined}
                                >
                                    <td role="cell" className="invoice-row-who">
                                        <span className="invoice-row-name">
                                            {/* Keep the icon inside the button so a long name wraps beside it. */}
                                            {readOnly ? nameLabel : (
                                                <button type="button" className="participant-name-button" onClick={() => onStartEdit(participant)}>
                                                    {nameLabel}
                                                </button>
                                            )}
                                            {participant.name_addition && <span className="muted">{participant.name_addition}</span>}
                                        </span>
                                        <span className="invoice-row-meta">
                                            {(roles.length > 0 || !isCurrent) && (
                                                <span className="participant-row-badges">
                                                    {roles.map((role) => (
                                                        <span key={role} className="badge badge-tag">{t(`pages.participants.roles.${role}`)}</span>
                                                    ))}
                                                    {!isCurrent && (
                                                        <span className={validityBadgeClass(validityState)}>
                                                            {t(`pages.participants.validity.${validityState}`)}
                                                        </span>
                                                    )}
                                                </span>
                                            )}
                                            {participant.email && <span>{participant.email}</span>}
                                            {participant.phone && <span>{participant.phone}</span>}
                                        </span>
                                        {issues.length > 0 && (
                                            <span className="invoice-row-issues">
                                                {steps.filter((entry) => entry.state === 'issue').map((entry) => (
                                                    <IssueControl key={entry.step} entry={entry} participant={participant} readOnly={readOnly} onStartEdit={onStartEdit}>
                                                        {entry.label}
                                                        {!readOnly && <FontAwesomeIcon icon={faArrowRight} fixedWidth aria-hidden="true" />}
                                                    </IssueControl>
                                                ))}
                                            </span>
                                        )}
                                    </td>
                                    <td role="cell" className="participant-row-address">
                                        {street && <span>{street}</span>}
                                        {place && <span className="muted">{place}</span>}
                                    </td>
                                    <td role="cell" className="participant-row-validity">
                                        <span>{formatShortDate(participant.valid_from, settings)}</span>
                                        <span className="muted">
                                            {'– '}
                                            {participant.valid_to ? formatShortDate(participant.valid_to, settings) : t('pages.participants.openEnded')}
                                        </span>
                                    </td>
                                    <td role="cell" className="invoice-row-progress">
                                        <ol className="invoice-progress" aria-label={t('pages.participants.col.status')}>
                                            {steps.map((entry) => (
                                                <li key={entry.step} className="invoice-progress-step" title={entry.label} data-step={entry.step} data-state={entry.state}>
                                                    {entry.state === 'issue' ? (
                                                        <IssueControl entry={entry} participant={participant} readOnly={readOnly} onStartEdit={onStartEdit} iconOnly>
                                                            <ProgressIcon icon={STATUS_ICONS[entry.step]} state={entry.state} />
                                                        </IssueControl>
                                                    ) : <ProgressIcon icon={STATUS_ICONS[entry.step]} state={entry.state} />}
                                                    <span className="visually-hidden">{entry.label}</span>
                                                </li>
                                            ))}
                                        </ol>
                                    </td>
                                    <td role="cell" className="numeric invoice-row-total">
                                        <span
                                            data-testid="participant-weight"
                                            title={isCurrent
                                                ? t('pages.participants.weightShare', { percent: formattedPercent, weight: formattedWeight, total: formattedTotal })
                                                : t('pages.participants.weightShareUnavailableHint')}
                                        >
                                            {isCurrent ? `${formattedPercent} %` : '–'}
                                        </span>
                                        <span className="participant-row-weight muted">
                                            {isCurrent ? `${formattedWeight} / ${formattedTotal}` : formattedWeight}
                                        </span>
                                    </td>
                                    <td role="cell" className="invoice-actions-cell">
                                        <div className="invoice-row-actions">
                                            <button className="button button-secondary button-compact" type="button" onClick={() => onDownloadContract(participant)}>
                                                <FontAwesomeIcon icon={faDownload} fixedWidth />
                                                {t('pages.participants.downloadContract')}
                                            </button>
                                            {menuItems.length > 0 && (
                                                <ActionMenu
                                                    label={t('pages.participants.moreActions')}
                                                    iconOnly
                                                    icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
                                                    items={menuItems}
                                                />
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            )
                        })}
                    </tbody>
                </table>
            </div>
            <ProgressLegend
                steps={(Object.keys(STATUS_ICONS) as StatusStep[]).map((step) => ({
                    key: step,
                    icon: STATUS_ICONS[step],
                    label: t(`pages.participants.status.${step}`),
                }))}
                states={[
                    { state: 'done', label: t('pages.participants.status.done') },
                    { state: 'issue', label: t('pages.participants.status.missing') },
                ]}
            />
        </>
    )
}
