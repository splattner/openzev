import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useManagedZev } from '../../lib/managedZev'
import type { AccountMembership } from '../../types/api'

/**
 * The communities an account belongs to, one chip each. Selecting a chip
 * switches the shell to that community and opens its Participants page —
 * memberships are managed there, not on the accounts page.
 */
export function AccountMemberships({ memberships }: { memberships: AccountMembership[] }) {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { setSelectedZevId } = useManagedZev()

    if (memberships.length === 0) {
        return <span className="muted">{t('pages.accounts.noMemberships')}</span>
    }

    return (
        <ul className="account-memberships" aria-label={t('pages.accounts.col.communities')}>
            {memberships.map((membership) => (
                <li key={membership.zev}>
                    <button
                        type="button"
                        className="account-membership-chip"
                        title={t('pages.accounts.openInCommunity', { zev: membership.zev_name })}
                        onClick={() => {
                            setSelectedZevId(membership.zev)
                            navigate(membership.participant ? `/participants?focus=${membership.participant}` : '/participants')
                        }}
                    >
                        <span className="account-membership-kind">
                            {t(membership.is_owner ? 'pages.accounts.membership.owner' : 'pages.accounts.membership.participant')}
                        </span>
                        <span>{membership.zev_name}</span>
                    </button>
                </li>
            ))}
        </ul>
    )
}
