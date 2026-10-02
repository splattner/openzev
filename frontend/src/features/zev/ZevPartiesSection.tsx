import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faPen, faPlus, faTrash } from '@fortawesome/free-solid-svg-icons'
import { CivilDateInput } from '../../components/CivilDateInput'
import { ConfirmDialog, useConfirmDialog } from '../../components/ConfirmDialog'
import {
    assignPartyRole,
    createParty,
    deleteParty,
    endPartyRole,
    fetchParties,
    fetchPartyRoles,
    updateParty,
} from '../../lib/api/zev'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { todayBusinessIso } from '../../lib/dates'
import { useToast } from '../../lib/toast'
import type { Party, PartyInput, PartyRoleName, ZevPartyRole } from '../../types/api'
import { PartyFormModal } from './PartyFormModal'

interface Props {
    zevId: string
    /** Change roles and contacts. A viewer (or a disabled ZEV) only reads. */
    canManage: boolean
}

const NEW_CONTACT = '__new__'

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
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const [editingParty, setEditingParty] = useState<Party | null>(null)
    const [partyModalOpen, setPartyModalOpen] = useState(false)
    // Where a contact created from a role picker should be selected afterwards.
    const [pickAfterCreate, setPickAfterCreate] = useState<((id: string) => void) | null>(null)

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

    function afterChange() {
        void queryClient.invalidateQueries({ queryKey: ['zev', 'parties', zevId] })
        void queryClient.invalidateQueries({ queryKey: ['zev', 'partyRoles', zevId] })
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
        mutationFn: (input: { party: string; role: PartyRoleName; valid_from: string }) => assignPartyRole({ ...input, zev: zevId }),
        onSuccess: () => {
            afterChange()
            pushToast(t('pages.zevSettings.parties.roleAssigned'), 'success')
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
            onConfirm: () => removeParty.mutateAsync(party).then(() => undefined),
        })
    }

    const parties = partiesQuery.data ?? []
    const roles = rolesQuery.data ?? []
    const busy = assign.isPending || end.isPending
    const contacts = parties.filter((party) => party.participations.length === 0)

    return (
        <section className="card page-stack">
            <div>
                <h3 style={{ marginTop: 0 }}>{t('pages.zevSettings.parties.title')}</h3>
                <p className="muted" style={{ margin: 0 }}>{t('pages.zevSettings.parties.description')}</p>
            </div>

            {(partiesQuery.isLoading || rolesQuery.isLoading) && <p className="muted">{t('common.loading')}</p>}
            {(partiesQuery.isError || rolesQuery.isError) && <p className="error-banner">{t('common.error')}</p>}

            {partiesQuery.isSuccess && rolesQuery.isSuccess && (
                <>
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
                        />
                    ))}

                    <Landowners
                        rows={roles.filter((row) => row.role === 'landowner')}
                        parties={parties}
                        canManage={canManage}
                        busy={busy}
                        onAssign={(party, validFrom) => assign.mutateAsync({ party, role: 'landowner', valid_from: validFrom })}
                        onEnd={(row, lastDay) => end.mutateAsync({ row, lastDay })}
                        onNewContact={openNewContact}
                    />

                    <div className="zev-parties-block">
                        <div className="zev-parties-block-header">
                            <div>
                                <h4>{t('pages.zevSettings.parties.contacts')}</h4>
                                <p className="muted">{t('pages.zevSettings.parties.contactsHint')}</p>
                            </div>
                            {canManage && (
                                <button type="button" className="button button-secondary button-compact" onClick={() => openNewContact()}>
                                    <FontAwesomeIcon icon={faPlus} fixedWidth />
                                    {t('pages.zevSettings.parties.addContact')}
                                </button>
                            )}
                        </div>
                        {contacts.length === 0 && <p className="muted">{t('pages.zevSettings.parties.noContacts')}</p>}
                        {contacts.length > 0 && (
                            <ul className="zev-access-list">
                                {contacts.map((party) => (
                                    <li key={party.id} className="zev-access-row">
                                        <div className="zev-access-who">
                                            <strong>{party.display_name}</strong>
                                            {party.name_addition && <span className="muted">{party.name_addition}</span>}
                                            <span className="zev-access-badges">
                                                {[...new Set(party.roles.map((row) => row.role))].map((role) => (
                                                    <span key={role} className="badge badge-info">{t(`pages.participants.roles.${role}`)}</span>
                                                ))}
                                            </span>
                                        </div>
                                        <div className="zev-access-meta muted">
                                            {party.email && <span>{party.email}</span>}
                                            {party.accounts.length > 0 && (
                                                <span>{t('pages.zevSettings.parties.login', { email: party.accounts[0].email })}</span>
                                            )}
                                            {(party.address_line1 || party.city) && (
                                                <span>{[party.address_line1, [party.postal_code, party.city].filter(Boolean).join(' ')].filter(Boolean).join(', ')}</span>
                                            )}
                                        </div>
                                        {canManage && (
                                            <div className="zev-access-actions actions-row actions-row-wrap">
                                                <button
                                                    type="button"
                                                    className="button button-secondary button-compact"
                                                    onClick={() => { setEditingParty(party); setPartyModalOpen(true) }}
                                                >
                                                    <FontAwesomeIcon icon={faPen} fixedWidth />
                                                    {t('common.edit')}
                                                </button>
                                                {party.roles.length === 0 && (
                                                    <button
                                                        type="button"
                                                        className="button button-danger button-compact"
                                                        disabled={removeParty.isPending}
                                                        onClick={() => confirmDelete(party)}
                                                    >
                                                        <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                        {t('common.delete')}
                                                    </button>
                                                )}
                                            </div>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                </>
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
        </section>
    )
}

interface PickerProps {
    parties: Party[]
    value: string
    onChange: (id: string) => void
    onNewContact: (onCreated: (id: string) => void) => void
}

/** Every party of the ZEV, plus "New contact…" which opens the contact form. */
function PartyPicker({ parties, value, onChange, onNewContact }: PickerProps) {
    const { t } = useTranslation()
    return (
        <label>
            <span>{t('pages.zevSettings.parties.party')}</span>
            <select
                value={value}
                onChange={(event) => (event.target.value === NEW_CONTACT ? onNewContact(onChange) : onChange(event.target.value))}
                required
            >
                <option value="">{t('pages.zevSettings.parties.selectParty')}</option>
                {parties.map((party) => (
                    <option key={party.id} value={party.id}>{party.display_name}</option>
                ))}
                <option value={NEW_CONTACT}>{t('pages.zevSettings.parties.newContactOption')}</option>
            </select>
        </label>
    )
}

interface AssignFormProps {
    parties: Party[]
    busy: boolean
    submitLabel: string
    onAssign: (party: string, validFrom: string) => Promise<unknown>
    onNewContact: (onCreated: (id: string) => void) => void
    onDone: () => void
}

function AssignForm({ parties, busy, submitLabel, onAssign, onNewContact, onDone }: AssignFormProps) {
    const { t } = useTranslation()
    const [party, setParty] = useState('')
    const [validFrom, setValidFrom] = useState(todayBusinessIso())

    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!party || !validFrom) return
        void onAssign(party, validFrom).then(onDone, () => undefined)
    }

    return (
        <form className="form-grid zev-access-form" onSubmit={submit}>
            <PartyPicker parties={parties} value={party} onChange={setParty} onNewContact={onNewContact} />
            <label>
                <span>{t('pages.zevSettings.parties.validFrom')}</span>
                <CivilDateInput value={validFrom || null} onChange={(iso) => setValidFrom(iso ?? '')} clearable={false} />
            </label>
            <div className="actions-row actions-row-wrap">
                <button type="submit" className="button button-primary" disabled={busy || !party || !validFrom}>{submitLabel}</button>
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
}

/** The issuer or the representative: today's holder, what is scheduled, the history, and "Change from…". */
function SingleHolderRole({ role, rows, parties, canManage, busy, onAssign, onNewContact }: SingleHolderRoleProps) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const [changing, setChanging] = useState(false)
    const [showHistory, setShowHistory] = useState(false)
    const today = todayBusinessIso()
    const current = rows.find((row) => activeOn(row, today))
    const upcoming = rows.filter((row) => row.valid_from > today).sort((a, b) => a.valid_from.localeCompare(b.valid_from))
    const past = rows.filter((row) => row.valid_to !== null && row.valid_to < today).sort((a, b) => b.valid_from.localeCompare(a.valid_from))
    const windowText = (row: ZevPartyRole) => [
        t('pages.zevSettings.access.since', { date: formatShortDate(row.valid_from, settings) }),
        row.valid_to ? t('pages.zevSettings.access.until', { date: formatShortDate(row.valid_to, settings) }) : null,
    ].filter(Boolean).join(' · ')

    return (
        <div className="zev-parties-block">
            <div className="zev-parties-block-header">
                <div>
                    <h4>{t(`pages.zevSettings.parties.${role}Title`)}</h4>
                    <p className="muted">{t(`pages.zevSettings.parties.${role}Hint`)}</p>
                </div>
                {canManage && !changing && (
                    <button type="button" className="button button-secondary button-compact" onClick={() => setChanging(true)}>
                        {t(current || upcoming.length ? 'pages.zevSettings.parties.changeFrom' : 'pages.zevSettings.parties.set')}
                    </button>
                )}
            </div>
            {current ? (
                <p className="zev-parties-holder">
                    <strong>{current.party_display_name}</strong>
                    <span className="muted">{windowText(current)}</span>
                </p>
            ) : (
                <p className={role === 'issuer' ? 'warning-banner' : 'muted'}>
                    {t(`pages.zevSettings.parties.${role}None`)}
                </p>
            )}
            {upcoming.map((row) => (
                <p key={row.id} className="zev-parties-holder">
                    <span className="badge badge-neutral">{t('pages.zevSettings.parties.upcoming')}</span>
                    <strong>{row.party_display_name}</strong>
                    <span className="muted">{windowText(row)}</span>
                </p>
            ))}
            {changing && (
                <AssignForm
                    parties={parties}
                    busy={busy}
                    submitLabel={t('pages.zevSettings.parties.apply')}
                    onAssign={onAssign}
                    onNewContact={onNewContact}
                    onDone={() => setChanging(false)}
                />
            )}
            {changing && <p className="muted zev-access-form-hint">{t('pages.zevSettings.parties.changeHint')}</p>}
            {past.length > 0 && (
                <>
                    <label className="zev-access-toggle">
                        <input type="checkbox" checked={showHistory} onChange={(event) => setShowHistory(event.target.checked)} />
                        <span>{t('pages.zevSettings.parties.showHistory')}</span>
                    </label>
                    {showHistory && (
                        <ul className="zev-parties-history">
                            {past.map((row) => (
                                <li key={row.id}>
                                    <span>{row.party_display_name}</span>
                                    <span className="muted">{windowText(row)}</span>
                                </li>
                            ))}
                        </ul>
                    )}
                </>
            )}
        </div>
    )
}

interface LandownersProps {
    rows: ZevPartyRole[]
    parties: Party[]
    canManage: boolean
    busy: boolean
    onAssign: (party: string, validFrom: string) => Promise<unknown>
    onEnd: (row: ZevPartyRole, lastDay: string) => Promise<unknown>
    onNewContact: (onCreated: (id: string) => void) => void
}

function Landowners({ rows, parties, canManage, busy, onAssign, onEnd, onNewContact }: LandownersProps) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const [adding, setAdding] = useState(false)
    const [ending, setEnding] = useState<string | null>(null)
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
                    submitLabel={t('pages.zevSettings.parties.addLandowner')}
                    onAssign={onAssign}
                    onNewContact={onNewContact}
                    onDone={() => setAdding(false)}
                />
            )}
            {listed.length === 0 && <p className="muted">{t('pages.zevSettings.parties.noLandowners')}</p>}
            {listed.length > 0 && (
                <ul className="zev-access-list">
                    {listed.map((row) => (
                        <li key={row.id} className="zev-access-row">
                            <div className="zev-access-who">
                                <strong>{row.party_display_name}</strong>
                            </div>
                            <div className="zev-access-meta muted">
                                <span>
                                    {t('pages.zevSettings.access.since', { date: formatShortDate(row.valid_from, settings) })}
                                    {row.valid_to && ` · ${t('pages.zevSettings.access.until', { date: formatShortDate(row.valid_to, settings) })}`}
                                </span>
                            </div>
                            {canManage && row.valid_to === null && (
                                <div className="zev-access-actions actions-row actions-row-wrap">
                                    {ending === row.id ? (
                                        <form
                                            className="actions-row actions-row-wrap"
                                            onSubmit={(event) => {
                                                event.preventDefault()
                                                void onEnd(row, lastDay).then(() => setEnding(null), () => undefined)
                                            }}
                                        >
                                            <label className="zev-parties-inline-date">
                                                <span>{t('pages.zevSettings.parties.lastDay')}</span>
                                                <CivilDateInput value={lastDay || null} onChange={(iso) => setLastDay(iso ?? '')} clearable={false} />
                                            </label>
                                            <button type="submit" className="button button-danger button-compact" disabled={busy}>
                                                {t('pages.zevSettings.parties.end')}
                                            </button>
                                            <button type="button" className="button button-secondary button-compact" onClick={() => setEnding(null)}>
                                                {t('common.cancel')}
                                            </button>
                                        </form>
                                    ) : (
                                        <button type="button" className="button button-secondary button-compact" onClick={() => { setLastDay(today); setEnding(row.id) }}>
                                            {t('pages.zevSettings.parties.end')}
                                        </button>
                                    )}
                                </div>
                            )}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}
