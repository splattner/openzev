import { ZevPartiesSection } from './ZevPartiesSection'

interface Props {
    zevId: string
    /** Change roles, contacts and access. A viewer (or a disabled ZEV) only reads. */
    canManage: boolean
}

/**
 * ZEV settings → People & access (#761): who the community deals with and
 * what each of them may do in OpenZEV, on the same rows. The issuer and the
 * representative manage the ZEV through their role; landowners, contacts and
 * anyone else get access — manager or read-only — from their own row.
 */
export function ZevPeopleSection({ zevId, canManage }: Props) {
    return (
        <div className="page-stack">
            <ZevPartiesSection zevId={zevId} canManage={canManage} />
        </div>
    )
}
