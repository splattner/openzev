import { useState } from 'react'
import { ZevAccessSection } from './ZevAccessSection'
import { ZevPartiesSection } from './ZevPartiesSection'

interface Props {
    zevId: string
    /** Change roles, contacts and access. A viewer (or a disabled ZEV) only reads. */
    canManage: boolean
}

/**
 * ZEV settings → People & access (#761): who the community deals with and who
 * may sign in to it, on one page. Roles first (the issuer and the
 * representative also manage the ZEV), then everyone with access, then the
 * contacts that are not participants — each of which can be given access from
 * its own row.
 */
export function ZevPeopleSection({ zevId, canManage }: Props) {
    const [request, setRequest] = useState<{ partyId: string } | null>(null)

    return (
        <div className="page-stack">
            <ZevPartiesSection
                zevId={zevId}
                canManage={canManage}
                onGiveAccess={(party) => {
                    setRequest({ partyId: party.id })
                    window.setTimeout(
                        () => document.getElementById('zev-access-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
                        50,
                    )
                }}
                accessSlot={<ZevAccessSection zevId={zevId} canManage={canManage} request={request} />}
            />
        </div>
    )
}
