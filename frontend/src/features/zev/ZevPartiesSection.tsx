import { useId, useRef, useState, type FormEvent, type ReactNode, type RefObject } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faEllipsis, faPen, faPlus, faTrash } from '@fortawesome/free-solid-svg-icons'
import { CivilDateInput } from '../../components/CivilDateInput'
import { ActionMenu, type ActionMenuItem } from '../../components/ActionMenu'
import { ConfirmDialog, consumeReportedError, useConfirmDialog } from '../../components/ConfirmDialog'
import { Disclosure } from '../../components/Disclosure'
import { EmptyState } from '../../components/EmptyState'
import { IssueText } from '../../components/IssueText'
import { PageState } from '../../components/PageState'
import {
    assignPartyRole,
    createParty,
    deleteParty,
    endPartyRole,
    fetchBuildings,
    fetchParties,
    fetchPartyRoles,
    fetchZevAccess,
    setPartyRoleBuilding,
    updateParty,
} from '../../lib/api/zev'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { todayBusinessIso } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import type { Building, Party, PartyInput, PartyRoleName, ZevPartyRole } from '../../types/api'
import { describeAccess, GiveAccessForm, useAccessActions, type AccessDescription } from './PartyAccess'
import { PartyFormModal } from './PartyFormModal'

interface Props {
    zevId: string
    /** Change roles and contacts. A viewer (or a disabled ZEV) only reads. */
    canManage: boolean
}

const NEW_CONTACT = '__new__'
/** The give-access form opened from the header, for someone who is not on the page yet. */
const FREE_ACCESS_FORM = '__free__'

/** `context` names the row (a person can be issuer and landowner), so the give-access form opens under that row only. */
type AccessFor = (partyId: string, context: string, managingRole?: boolean) => AccessDescription

/** A role row is current on ``day`` when its window covers it. */
function activeOn(row: ZevPartyRole, day: string): boolean {
    return row.valid_from <= day && (row.valid_to === null || row.valid_to >= day)
}

/**
 * ZEV settings → Parties (#761, SPEC-2026-10-zev-parties §8.3): whom the
 * community's documents are from (issuer), who represents it toward the grid
 * operator, who owns the land, and the contacts that are not participants.
 * Roles are dated: a change takes effect from a day and ends the previous
 * holder the day before, so documents dated earlier keep naming the earlier
 * holder.
 */
export function ZevPartiesSection({ zevId, canManage }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { settings } = useAppSettings()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const [editingParty, setEditingParty] = useState<Party | null>(null)
    const [partyModalOpen, setPartyModalOpen] = useState(false)
    // Where a contact created from a role picker should be selected afterwards.
    const [pickAfterCreate, setPickAfterCreate] = useState<((id: string) => void) | null>(null)
    // Where the give-access form is open: the header's, or under one person's row.
    const [givingAccessTo, setGivingAccessTo] = useState<string | null>(null)
    const accessActions = useAccessActions(zevId)

    const partiesQuery = useQuery({
        queryKey: queryKeys.zev.parties(zevId),
        queryFn: () => fetchParties(zevId),
        enabled: Boolean(zevId),
    })
    const rolesQuery = useQuery({
        queryKey: queryKeys.zev.partyRoles(zevId, true),
        queryFn: () => fetchPartyRoles(zevId, { includeEnded: true }),
        enabled: Boolean(zevId),
    })

    const buildingsQuery = useQuery({
        queryKey: queryKeys.zev.buildings(zevId),
        queryFn: () => fetchBuildings(zevId),
        enabled: Boolean(zevId),
    })

    // Which contacts can already sign in to this ZEV, and how (the access list's rows).
    const accessQuery = useQuery({
        queryKey: queryKeys.zev.access(zevId, false),
        queryFn: () => fetchZevAccess(zevId),
        enabled: Boolean(zevId),
    })

    function afterChange() {
        void queryClient.invalidateQueries({ queryKey: ['zev', 'parties', zevId] })
        void queryClient.invalidateQueries({ queryKey: ['zev', 'partyRoles', zevId] })
        void queryClient.invalidateQueries({ queryKey: ['zev', 'access', zevId] })
        void queryClient.invalidateQueries({ queryKey: queryKeys.zev.list() })
        void queryClient.invalidateQueries({ queryKey: ['zev', 'participants'] })
    }

    const saveParty = useMutation({
        mutationFn: (input: PartyInput) => (editingParty ? updateParty(editingParty.id, input) : createParty({ ...input, zev: zevId })),
        onSuccess: (saved) => {
            setPartyModalOpen(false)
            setEditingParty(null)
            pickAfterCreate?.(saved.id)
            setPickAfterCreate(null)
            afterChange()
            pushToast(t('pages.zevSettings.parties.saved'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.zevSettings.parties.saveFailed')), 'error'),
    })

    const removeParty = useMutation({
        mutationFn: (party: Party) => deleteParty(party.id),
        onSuccess: () => {
            afterChange()
            pushToast(t('pages.zevSettings.parties.deleted'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.zevSettings.parties.saveFailed')), 'error'),
    })

    const assign = useMutation({
        mutationFn: (input: { party: string; role: PartyRoleName; valid_from: string; building?: string | null }) => assignPartyRole({ ...input, zev: zevId }),
        onSuccess: () => {
            afterChange()
            pushToast(t('pages.zevSettings.parties.roleAssigned'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.zevSettings.parties.saveFailed')), 'error'),
    })

    const setBuilding = useMutation({
        mutationFn: ({ row, building }: { row: ZevPartyRole; building: string | null }) => setPartyRoleBuilding(row.id, building),
        onSuccess: () => {
            afterChange()
            void queryClient.invalidateQueries({ queryKey: queryKeys.zev.buildings(zevId) })
            pushToast(t('pages.zevSettings.parties.landownerBuildingSaved'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.zevSettings.parties.saveFailed')), 'error'),
    })

    const end = useMutation({
        mutationFn: ({ row, lastDay }: { row: ZevPartyRole; lastDay: string }) => endPartyRole(row.id, lastDay),
        onSuccess: () => {
            afterChange()
            pushToast(t('pages.zevSettings.parties.roleEnded'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('pages.zevSettings.parties.saveFailed')), 'error'),
    })

    /**
     * The issuer and the representative manage the ZEV through their role
     * (ADR 0028, amended), so handing one over is an access change too: say
     * who gets manager access — or that nobody does — before applying it.
     */
    function assignManagingRole(role: 'issuer' | 'representative', partyId: string, validFrom: string): Promise<unknown> {
        const party = (partiesQuery.data ?? []).find((candidate) => candidate.id === partyId)
        const name = party?.display_name ?? ''
        const logins = (party?.accounts ?? []).map((account) => account.email).join(', ')
        return new Promise((resolve, reject) => {
            confirm({
                title: t(`pages.zevSettings.parties.${role}Title`),
                message: logins
                    ? t('pages.zevSettings.parties.grantsAccess', { name, accounts: logins })
                    : t('pages.zevSettings.parties.noLogin', { name }),
                confirmText: t('pages.zevSettings.parties.apply'),
                // The mutation shows its own error; the dialog closes either way.
                onConfirm: () => assign.mutateAsync({ party: partyId, role, valid_from: validFrom }).then(resolve, reject),
            })
        })
    }

    /** Ending a landowner takes effect at once and changes who later documents name: say so before applying it. */
    function confirmEnd(row: ZevPartyRole, lastDay: string): Promise<unknown> {
        return new Promise((resolve, reject) => {
            confirm({
                title: t('pages.zevSettings.parties.endLandownerTitle'),
                message: t('pages.zevSettings.parties.endLandownerMessage', {
                    name: row.party_display_name,
                    date: formatShortDate(lastDay, settings),
                }),
                confirmText: t('pages.zevSettings.parties.end'),
                onConfirm: () => end.mutateAsync({ row, lastDay }).then(resolve, reject),
            })
        })
    }

    function openNewContact(onCreated?: (id: string) => void) {
        setEditingParty(null)
        setPickAfterCreate(() => onCreated ?? null)
        setPartyModalOpen(true)
    }

    function confirmDelete(party: Party) {
        confirm({
            title: t('pages.zevSettings.parties.deleteTitle'),
            message: t('pages.zevSettings.parties.deleteMessage', { name: party.display_name }),
            confirmText: t('common.delete'),
            isDangerous: true,
            onConfirm: () => consumeReportedError(removeParty.mutateAsync(party)),
        })
    }

    const parties = partiesQuery.data ?? []
    const roles = rolesQuery.data ?? []
    const busy = assign.isPending || end.isPending || setBuilding.isPending
    const contacts = parties.filter((party) => party.participations.length === 0)
    const entries = accessQuery.data ?? []
    const today = todayBusinessIso()
    const entriesOf = (party: Party | undefined) => {
        const ids = new Set((party?.accounts ?? []).map((account) => account.id))
        return entries.filter((entry) => ids.has(entry.user.id))
    }
    const partyById = new Map(parties.map((party) => [party.id, party]))
    /** Access, split for the row of the party it belongs to (#761: one place for a person and its login). */
    const accessFor: AccessFor = (partyId, context, managingRole = false) => describeAccess({
        t,
        settings,
        entries: entriesOf(partyById.get(partyId)),
        party: partyById.get(partyId),
        canManage,
        actions: accessActions,
        managingRole,
        onGive: (id) => setGivingAccessTo(`${context}:${id}`),
    })
    const renderGiveForm = (where: string) => givingAccessTo === where && (
        <GiveAccessForm
            key={where}
            parties={parties}
            actions={accessActions}
            initialPartyId={where === FREE_ACCESS_FORM ? undefined : where.slice(where.indexOf(':') + 1)}
            onDone={() => setGivingAccessTo(null)}
        />
    )
    // Everyone with access who is not on the page yet: participants given
    // access, and logins given access by email (a bookkeeper, staff).
    const shownPartyIds = new Set([
        ...roles.filter((row) => activeOn(row, today) || (row.role === 'landowner' && row.valid_from > today)).map((row) => row.party),
        ...contacts.map((party) => party.id),
    ])
    const shownAccountIds = new Set(
        parties.filter((party) => shownPartyIds.has(party.id)).flatMap((party) => party.accounts.map((account) => account.id)),
    )
    const otherParties = parties.filter((party) => !shownPartyIds.has(party.id) && entriesOf(party).length > 0)
    otherParties.forEach((party) => party.accounts.forEach((account) => shownAccountIds.add(account.id)))
    const bareLogins = [...new Map(
        entries.filter((entry) => !shownAccountIds.has(entry.user.id)).map((entry) => [entry.user.id, entry]),
    ).values()]
    const listedParties = [...contacts, ...otherParties]
    const nobodyElse = listedParties.length + bareLogins.length === 0

    return (
        <PageState
            isLoading={partiesQuery.isLoading || rolesQuery.isLoading}
            isError={partiesQuery.isError || rolesQuery.isError}
            onRetry={() => { void partiesQuery.refetch(); void rolesQuery.refetch() }}
        >
        <section className="card page-stack">
            <div>
                <h3 className="mt-0">{t('pages.zevSettings.parties.title')}</h3>
                <p className="muted m-0">{t('pages.zevSettings.parties.description')}</p>
            </div>

            {(['issuer', 'representative'] as const).map((role) => (
                <SingleHolderRole
                    key={role}
                    role={role}
                    rows={roles.filter((row) => row.role === role)}
                    parties={parties}
                    canManage={canManage}
                    busy={busy}
                    onAssign={(party, validFrom) => assignManagingRole(role, party, validFrom)}
                    onNewContact={openNewContact}
                    accessFor={accessFor}
                    renderGiveForm={renderGiveForm}
                />
            ))}

            <Landowners
                rows={roles.filter((row) => row.role === 'landowner')}
                parties={parties}
                canManage={canManage}
                busy={busy}
                buildings={buildingsQuery.data ?? []}
                onAssign={(party, validFrom, building) => assign.mutateAsync({ party, role: 'landowner', valid_from: validFrom, building })}
                onSetBuilding={(row, building) => setBuilding.mutateAsync({ row, building })}
                onEnd={confirmEnd}
                onNewContact={openNewContact}
                accessFor={accessFor}
                renderGiveForm={renderGiveForm}
            />
        </section>

        {nobodyElse ? (
            <>
                {renderGiveForm(FREE_ACCESS_FORM) && <section className="card">{renderGiveForm(FREE_ACCESS_FORM)}</section>}
                <EmptyState
                    titleKey="pages.zevSettings.parties.noContacts"
                    descriptionKey="pages.zevSettings.parties.contactsHint"
                    actions={canManage ? [
                        { labelKey: 'pages.zevSettings.parties.addContact', variant: 'primary', icon: faPlus, onClick: () => openNewContact() },
                        { labelKey: 'pages.zevSettings.access.add', variant: 'secondary', onClick: () => setGivingAccessTo(FREE_ACCESS_FORM) },
                    ] : undefined}
                />
            </>
        ) : (
            <section className="table-card people-rows">
                <div className="people-rows-header">
                    <div>
                        <h3>{t('pages.zevSettings.parties.contacts')}</h3>
                        <p className="muted">{t('pages.zevSettings.parties.contactsHint')}</p>
                    </div>
                    {canManage && (
                        <div className="actions-row actions-row-wrap">
                            <button type="button" className="button button-secondary" onClick={() => setGivingAccessTo(FREE_ACCESS_FORM)}>
                                {t('pages.zevSettings.access.add')}
                            </button>
                            <button type="button" className="button button-primary" onClick={() => openNewContact()}>
                                <FontAwesomeIcon icon={faPlus} fixedWidth />
                                {t('pages.zevSettings.parties.addContact')}
                            </button>
                        </div>
                    )}
                </div>
                {renderGiveForm(FREE_ACCESS_FORM)}
                <table role="table">
                    <thead role="rowgroup">
                        <tr role="row">
                            <th role="columnheader" scope="col">{t('pages.zevSettings.parties.col.person')}</th>
                            <th role="columnheader" scope="col">{t('pages.zevSettings.parties.col.access')}</th>
                            <th role="columnheader" scope="col" className="people-actions-cell">
                                <span className="visually-hidden">{t('pages.zevSettings.parties.col.actions')}</span>
                            </th>
                        </tr>
                    </thead>
                    <tbody role="rowgroup">
                        {listedParties.map((party) => {
                            const editable = canManage && party.participations.length === 0
                            const described = describeAccess({
                                t, settings, entries: entriesOf(party), party, canManage, actions: accessActions,
                                shownEmail: party.email, onGive: (id) => setGivingAccessTo(`contact:${id}`),
                            })
                            const menuItems = [...described.menuItems]
                            if (editable && party.roles.length === 0 && entriesOf(party).length === 0) {
                                menuItems.push({
                                    key: 'delete',
                                    label: t('common.delete'),
                                    icon: <FontAwesomeIcon icon={faTrash} fixedWidth />,
                                    danger: true,
                                    disabled: removeParty.isPending,
                                    onClick: () => confirmDelete(party),
                                })
                            }
                            return (
                                <PersonRows
                                    key={party.id}
                                    cells={{
                                        who: (
                                            <>
                                                <span className="people-row-name">
                                                    <strong>{party.display_name}</strong>
                                                    {party.name_addition && <span className="muted">{party.name_addition}</span>}
                                                    <span className="people-row-tags">
                                                        {party.participations.length > 0 && (
                                                            <span className="badge badge-tag">{t('pages.zevSettings.parties.participant')}</span>
                                                        )}
                                                        {[...new Set(party.roles.map((row) => row.role))].map((role) => (
                                                            <span key={role} className="badge badge-tag">{t(`pages.participants.roles.${role}`)}</span>
                                                        ))}
                                                    </span>
                                                </span>
                                                <span className="people-row-meta muted">
                                                    {party.email && <span>{party.email}</span>}
                                                    {(party.address_line1 || party.city) && (
                                                        <span>{[party.address_line1, [party.postal_code, party.city].filter(Boolean).join(' ')].filter(Boolean).join(', ')}</span>
                                                    )}
                                                </span>
                                            </>
                                        ),
                                        access: described.status,
                                        actions: (
                                            <>
                                                {editable && (
                                                    <button
                                                        type="button"
                                                        className="button button-secondary button-compact"
                                                        aria-label={t('common.edit')}
                                                        title={t('common.edit')}
                                                        onClick={() => { setEditingParty(party); setPartyModalOpen(true) }}
                                                    >
                                                        <FontAwesomeIcon icon={faPen} fixedWidth />
                                                    </button>
                                                )}
                                                {described.primary}
                                                <RowMenu items={menuItems} />
                                            </>
                                        ),
                                    }}
                                    form={renderGiveForm(`contact:${party.id}`)}
                                />
                            )
                        })}
                        {bareLogins.map((entry) => {
                            const loginName = `${entry.user.first_name} ${entry.user.last_name}`.trim()
                            const described = describeAccess({
                                t, settings, entries: entries.filter((item) => item.user.id === entry.user.id), canManage,
                                actions: accessActions, shownEmail: loginName ? undefined : entry.user.email, onGive: () => undefined,
                            })
                            return (
                                <PersonRows
                                    key={`login-${entry.user.id}`}
                                    cells={{
                                        who: <span className="people-row-name"><strong>{loginName || entry.user.email}</strong></span>,
                                        access: described.status,
                                        actions: <RowMenu items={described.menuItems} />,
                                    }}
                                />
                            )
                        })}
                    </tbody>
                </table>
            </section>
        )}

        <PartyFormModal
            isOpen={partyModalOpen}
            party={editingParty}
            isPending={saveParty.isPending}
            onClose={() => { setPartyModalOpen(false); setEditingParty(null); setPickAfterCreate(null) }}
            onSubmit={(input) => saveParty.mutate(input)}
        />
        {dialog && (
            <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />
        )}
        {accessActions.dialog}
        </PageState>
    )
}

/** The row's "…" menu; nothing when no item applies (a viewer, or nothing left to do). */
function RowMenu({ items }: { items: ActionMenuItem[] }) {
    const { t } = useTranslation()
    if (items.length === 0) return null
    return (
        <ActionMenu
            label={t('pages.zevSettings.parties.moreActions')}
            iconOnly
            icon={<FontAwesomeIcon icon={faEllipsis} fixedWidth />}
            items={items}
        />
    )
}

/** One person of the contacts table (and the form that opened under it). */
function PersonRows({ cells, form }: { cells: { who: ReactNode; access: ReactNode; actions: ReactNode }; form?: ReactNode }) {
    return (
        <>
            <tr role="row" className="people-row">
                <td role="cell" className="people-row-who">{cells.who}</td>
                <td role="cell" className="people-row-access">{cells.access}</td>
                <td role="cell" className="people-actions-cell">
                    <div className="people-row-actions">{cells.actions}</div>
                </td>
            </tr>
            {form ? (
                <tr role="row" className="people-form-row">
                    <td role="cell" colSpan={3}>{form}</td>
                </tr>
            ) : null}
        </>
    )
}

interface PickerProps {
    parties: Party[]
    value: string
    onChange: (id: string) => void
    onNewContact: (onCreated: (id: string) => void) => void
    error?: string | null
    pickerRef?: RefObject<HTMLSelectElement | null>
}

/** Every person of the ZEV, plus "New contact…" which opens the contact form. */
function PartyPicker({ parties, value, onChange, onNewContact, error, pickerRef }: PickerProps) {
    const { t } = useTranslation()
    const errorId = useId()
    return (
        <label>
            <span>{t('pages.zevSettings.parties.party')}</span>
            <select
                ref={pickerRef}
                value={value}
                onChange={(event) => (event.target.value === NEW_CONTACT ? onNewContact(onChange) : onChange(event.target.value))}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? errorId : undefined}
            >
                <option value="">{t('pages.zevSettings.parties.selectParty')}</option>
                {parties.map((party) => (
                    <option key={party.id} value={party.id}>{party.display_name}</option>
                ))}
                <option value={NEW_CONTACT}>{t('pages.zevSettings.parties.newContactOption')}</option>
            </select>
            {error && <small className="field-error" id={errorId} role="alert">{error}</small>}
        </label>
    )
}

interface AssignFormProps {
    parties: Party[]
    busy: boolean
    title: string
    submitLabel: string
    onAssign: (party: string, validFrom: string, building?: string | null) => Promise<unknown>
    onNewContact: (onCreated: (id: string) => void) => void
    onDone: () => void
    /** Offer "which building does it own?" (landowners only, #890). */
    buildings?: Building[]
}

function AssignForm({ parties, busy, title, submitLabel, onAssign, onNewContact, onDone, buildings }: AssignFormProps) {
    const { t } = useTranslation()
    const [party, setParty] = useState('')
    const [validFrom, setValidFrom] = useState(todayBusinessIso())
    const [building, setBuilding] = useState('')
    const [error, setError] = useState<string | null>(null)
    const pickerRef = useRef<HTMLSelectElement>(null)

    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!party) {
            setError(t('pages.zevSettings.access.partyRequired'))
            pickerRef.current?.focus()
            return
        }
        if (!validFrom) return
        void onAssign(party, validFrom, buildings ? building || null : undefined).then(onDone, () => undefined)
    }

    return (
        <form className="form-grid zev-access-form" noValidate onSubmit={submit}>
            <h4 className="zev-access-form-title grid-span-full">{title}</h4>
            <PartyPicker
                parties={parties}
                value={party}
                onChange={(id) => { setParty(id); setError(null) }}
                onNewContact={onNewContact}
                error={error}
                pickerRef={pickerRef}
            />
            <label>
                <span>{t('pages.zevSettings.parties.validFrom')}</span>
                <CivilDateInput value={validFrom || null} onChange={(iso) => setValidFrom(iso ?? '')} clearable={false} />
            </label>
            {buildings && buildings.length > 0 && (
                <label>
                    <span>{t('pages.zevSettings.parties.landownerBuilding')}</span>
                    <select value={building} onChange={(event) => setBuilding(event.target.value)}>
                        <option value="">{t('pages.zevSettings.parties.buildingNotSpecified')}</option>
                        {buildings.map((candidate) => (
                            <option key={candidate.id} value={candidate.id}>{candidate.name}</option>
                        ))}
                    </select>
                </label>
            )}
            <div className="actions-row actions-row-wrap">
                <button type="submit" className="button button-primary" disabled={busy}>{submitLabel}</button>
                <button type="button" className="button button-secondary" onClick={onDone}>{t('common.cancel')}</button>
            </div>
        </form>
    )
}

interface SingleHolderRoleProps {
    role: 'issuer' | 'representative'
    rows: ZevPartyRole[]
    parties: Party[]
    canManage: boolean
    busy: boolean
    onAssign: (party: string, validFrom: string) => Promise<unknown>
    onNewContact: (onCreated: (id: string) => void) => void
    /** The holder's access in OpenZEV, shown on its row. */
    accessFor: AccessFor
    renderGiveForm: (where: string) => ReactNode
}

/** The issuer or the representative: today's holder, what is scheduled, the history, and the change action. */
function SingleHolderRole({ role, rows, parties, canManage, busy, onAssign, onNewContact, accessFor, renderGiveForm }: SingleHolderRoleProps) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const [changing, setChanging] = useState(false)
    const today = todayBusinessIso()
    const current = rows.find((row) => activeOn(row, today))
    const upcoming = rows.filter((row) => row.valid_from > today).sort((a, b) => a.valid_from.localeCompare(b.valid_from))
    const past = rows.filter((row) => row.valid_to !== null && row.valid_to < today).sort((a, b) => b.valid_from.localeCompare(a.valid_from))
    const windowText = (row: ZevPartyRole) => [
        t('pages.zevSettings.access.since', { date: formatShortDate(row.valid_from, settings) }),
        row.valid_to ? t('pages.zevSettings.access.until', { date: formatShortDate(row.valid_to, settings) }) : null,
    ].filter(Boolean).join(' · ')
    const changeKey = `pages.zevSettings.parties.${current || upcoming.length ? 'change' : 'set'}.${role}`
    const access = current ? accessFor(current.party, role, true) : null

    return (
        <div className="zev-parties-block">
            <div className="zev-parties-block-header">
                <div>
                    <h4>{t(`pages.zevSettings.parties.${role}Title`)}</h4>
                    <p className="muted">{t(`pages.zevSettings.parties.${role}Hint`)}</p>
                </div>
                {canManage && !changing && (
                    <button type="button" className="button button-secondary button-compact" onClick={() => setChanging(true)}>
                        {t(changeKey)}
                    </button>
                )}
            </div>
            {current && access ? (
                <>
                    <RoleRow
                        name={current.party_display_name}
                        windowText={windowText(current)}
                        status={access.status}
                        actions={<>{access.primary}<RowMenu items={access.menuItems} /></>}
                    />
                    {renderGiveForm(`${role}:${current.party}`)}
                </>
            ) : role === 'issuer' ? (
                // Documents carry only the community's name until someone issues them: a problem with its fix beside it.
                <IssueText tone="warning" onClick={canManage ? () => setChanging(true) : undefined}>
                    {t('pages.zevSettings.parties.issuerNone')}
                </IssueText>
            ) : (
                <p className="muted">{t('pages.zevSettings.parties.representativeNone')}</p>
            )}
            {upcoming.map((row) => (
                <p key={row.id} className="zev-parties-holder">
                    <span className="badge badge-info">{t('pages.zevSettings.parties.upcoming')}</span>
                    <strong>{row.party_display_name}</strong>
                    <span className="muted">{windowText(row)}</span>
                </p>
            ))}
            {changing && (
                <AssignForm
                    parties={parties}
                    busy={busy}
                    title={t(changeKey)}
                    submitLabel={t('pages.zevSettings.parties.apply')}
                    onAssign={onAssign}
                    onNewContact={onNewContact}
                    onDone={() => setChanging(false)}
                />
            )}
            {changing && <p className="muted zev-access-form-hint">{t('pages.zevSettings.parties.changeHint')}</p>}
            {past.length > 0 && (
                <Disclosure summary={t('pages.zevSettings.parties.showHistory')}>
                    <ul className="zev-parties-history">
                        {past.map((row) => (
                            <li key={row.id}>
                                <span>{row.party_display_name}</span>
                                <span className="muted">{windowText(row)}</span>
                            </li>
                        ))}
                    </ul>
                </Disclosure>
            )}
        </div>
    )
}

/** A holder of a role: name and dates, the login's status, and the row's actions. No box of its own: the sheet is the container. */
function RoleRow({ name, windowText, tags, status, actions }: {
    name: string
    windowText: string
    tags?: ReactNode
    status: ReactNode
    actions: ReactNode
}) {
    return (
        <div className="zev-role-row">
            <div className="zev-role-who">
                <strong>{name}</strong>
                {tags}
                <span className="muted">{windowText}</span>
            </div>
            <div className="zev-role-actions">{actions}</div>
            <div className="zev-role-access">{status}</div>
        </div>
    )
}

interface LandownersProps {
    rows: ZevPartyRole[]
    parties: Party[]
    canManage: boolean
    busy: boolean
    buildings: Building[]
    onAssign: (party: string, validFrom: string, building?: string | null) => Promise<unknown>
    onSetBuilding: (row: ZevPartyRole, building: string | null) => Promise<unknown>
    onEnd: (row: ZevPartyRole, lastDay: string) => Promise<unknown>
    onNewContact: (onCreated: (id: string) => void) => void
    /** The landowner's access in OpenZEV, shown on its row (a landowner gets none by its role). */
    accessFor: AccessFor
    renderGiveForm: (where: string) => ReactNode
}

function Landowners({ rows, parties, canManage, busy, buildings, onAssign, onSetBuilding, onEnd, onNewContact, accessFor, renderGiveForm }: LandownersProps) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const [adding, setAdding] = useState(false)
    const [ending, setEnding] = useState<string | null>(null)
    const [settingBuilding, setSettingBuilding] = useState<string | null>(null)
    const [pickedBuilding, setPickedBuilding] = useState('')
    const [lastDay, setLastDay] = useState(todayBusinessIso())
    const today = todayBusinessIso()
    const listed = rows
        .filter((row) => row.valid_to === null || row.valid_to >= today)
        .sort((a, b) => a.party_display_name.localeCompare(b.party_display_name))

    return (
        <div className="zev-parties-block">
            <div className="zev-parties-block-header">
                <div>
                    <h4>{t('pages.zevSettings.parties.landownersTitle')}</h4>
                    <p className="muted">{t('pages.zevSettings.parties.landownersHint')}</p>
                </div>
                {canManage && !adding && (
                    <button type="button" className="button button-secondary button-compact" onClick={() => setAdding(true)}>
                        <FontAwesomeIcon icon={faPlus} fixedWidth />
                        {t('pages.zevSettings.parties.addLandowner')}
                    </button>
                )}
            </div>
            {adding && (
                <AssignForm
                    parties={parties}
                    busy={busy}
                    title={t('pages.zevSettings.parties.addLandowner')}
                    submitLabel={t('pages.zevSettings.parties.add')}
                    buildings={buildings}
                    onAssign={onAssign}
                    onNewContact={onNewContact}
                    onDone={() => setAdding(false)}
                />
            )}
            {listed.length === 0 && <p className="muted">{t('pages.zevSettings.parties.noLandowners')}</p>}
            {listed.length > 0 && (
                <ul className="zev-role-list">
                    {listed.map((row) => {
                        const access = accessFor(row.party, 'landowner')
                        const open = canManage && row.valid_to === null
                        const menuItems: ActionMenuItem[] = [...access.menuItems]
                        if (open) {
                            // Rare, and it changes who later documents name: in the menu, confirmed.
                            menuItems.unshift({
                                key: 'end',
                                label: t('pages.zevSettings.parties.end'),
                                onClick: () => { setLastDay(today); setEnding(row.id) },
                            })
                        }
                        return (
                            <li key={row.id}>
                                <RoleRow
                                    name={row.party_display_name}
                                    tags={row.building_name ? <span className="badge badge-tag">{row.building_name}</span> : undefined}
                                    windowText={[
                                        t('pages.zevSettings.access.since', { date: formatShortDate(row.valid_from, settings) }),
                                        row.valid_to ? t('pages.zevSettings.access.until', { date: formatShortDate(row.valid_to, settings) }) : null,
                                    ].filter(Boolean).join(' · ')}
                                    status={access.status}
                                    actions={
                                        <>
                                            {open && buildings.length > 0 && settingBuilding !== row.id && (
                                                <button
                                                    type="button"
                                                    className="button button-secondary button-compact"
                                                    onClick={() => { setPickedBuilding(row.building ?? ''); setSettingBuilding(row.id) }}
                                                >
                                                    {t(row.building ? 'pages.zevSettings.parties.changeBuilding' : 'pages.zevSettings.parties.setBuilding')}
                                                </button>
                                            )}
                                            {access.primary}
                                            <RowMenu items={menuItems} />
                                        </>
                                    }
                                />
                                {open && settingBuilding === row.id && (
                                    <form
                                        className="zev-role-inline-form"
                                        onSubmit={(event) => {
                                            event.preventDefault()
                                            void onSetBuilding(row, pickedBuilding || null).then(
                                                () => setSettingBuilding(null),
                                                () => undefined,
                                            )
                                        }}
                                    >
                                        <label className="zev-parties-inline-date">
                                            <span>{t('pages.zevSettings.parties.landownerBuilding')}</span>
                                            <select className="select-compact" value={pickedBuilding} disabled={busy} onChange={(event) => setPickedBuilding(event.target.value)}>
                                                <option value="">{t('pages.zevSettings.parties.buildingNotSpecified')}</option>
                                                {buildings.map((candidate) => (
                                                    <option key={candidate.id} value={candidate.id}>{candidate.name}</option>
                                                ))}
                                            </select>
                                        </label>
                                        <button type="submit" className="button button-primary button-compact" disabled={busy}>
                                            {t('common.save')}
                                        </button>
                                        <button type="button" className="button button-secondary button-compact" onClick={() => setSettingBuilding(null)}>
                                            {t('common.cancel')}
                                        </button>
                                    </form>
                                )}
                                {open && ending === row.id && (
                                    <form
                                        className="zev-role-inline-form"
                                        onSubmit={(event) => {
                                            event.preventDefault()
                                            void onEnd(row, lastDay).then(() => setEnding(null), () => undefined)
                                        }}
                                    >
                                        <label className="zev-parties-inline-date">
                                            <span>{t('pages.zevSettings.parties.lastDay')}</span>
                                            <CivilDateInput value={lastDay || null} onChange={(iso) => setLastDay(iso ?? '')} clearable={false} />
                                        </label>
                                        <button type="submit" className="button button-secondary button-compact" disabled={busy || !lastDay}>
                                            {t('pages.zevSettings.parties.end')}
                                        </button>
                                        <button type="button" className="button button-secondary button-compact" onClick={() => setEnding(null)}>
                                            {t('common.cancel')}
                                        </button>
                                    </form>
                                )}
                                {renderGiveForm(`landowner:${row.party}`)}
                            </li>
                        )
                    })}
                </ul>
            )}
        </div>
    )
}
