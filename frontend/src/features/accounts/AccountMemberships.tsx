import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useManagedZev } from '../../lib/managedZev'
import { relationOf } from '../../lib/membership'
import type { Membership } from '../../types/api'

/** Why a manager manages: the role it holds there today (#761). */
const ROLE_LABELS = {
    issuer: 'pages.accounts.membership.issuer',
    representative: 'pages.accounts.membership.representative',
} as const

/**
 * The communities an account belongs to, one chip each; a manager through the
 * issuer or representative role names that role. Selecting a chip
 * switches the shell to that community and opens its Participants page —
 * memberships are managed there, not on the accounts page.
 */
export function AccountMemberships({ memberships }: { memberships: Membership[] }) {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { setSelectedZevId } = useManagedZev()

    if (memberships.length === 0) {
        return <span className="muted">{t('pages.accounts.noMemberships')}</span>
    }

    return (
        <ul className="account-memberships" aria-label={t('pages.accounts.col.communities')}>
            {memberships.map((membership) => {
                const participant = membership.participants.find((row) => row.live) ?? membership.participants[0]
                return (
                <li key={membership.zev}>
                    <button
                        type="button"
                        className="account-membership-chip"
                        title={t('pages.accounts.openInCommunity', { zev: membership.zev_name })}
                        onClick={() => {
                            setSelectedZevId(membership.zev)
                            navigate(participant ? `/participants?focus=${participant.id}` : '/participants')
                        }}
                    >
                        <span className="account-membership-kind">
                            {t(`pages.accounts.membership.${relationOf(membership)}`)}
                            {(membership.roles ?? []).map((role) => ` · ${t(ROLE_LABELS[role])}`).join('')}
                        </span>
                        <span>{membership.zev_name}</span>
                    </button>
                </li>
                )
            })}
        </ul>
    )
}
