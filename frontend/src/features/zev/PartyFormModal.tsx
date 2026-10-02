import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { TITLE_KEYS } from '../../lib/participantTitle'
import type { Party, PartyInput } from '../../types/api'

const EMPTY: PartyInput = {
    kind: 'person',
    title: '',
    first_name: '',
    last_name: '',
    organisation_name: '',
    name_addition: '',
    email: '',
    phone: '',
    address_line1: '',
    address_line2: '',
    postal_code: '',
    city: '',
    notes: '',
}

interface Props {
    isOpen: boolean
    /** The party to edit; absent to add a new contact. */
    party?: Party | null
    isPending: boolean
    onClose: () => void
    onSubmit: (input: PartyInput) => void
}

/**
 * Add or edit a person or organisation of the ZEV (#761). A party's name and
 * address are shared by every participation of it, so an edit here shows on
 * each of its participant cards too.
 */
export function PartyFormModal({ isOpen, party, isPending, onClose, onSubmit }: Props) {
    const { t } = useTranslation()
    const [values, setValues] = useState<PartyInput>(EMPTY)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!isOpen) return
        setValues(party ? { ...EMPTY, ...pick(party) } : EMPTY)
        setError(null)
    }, [isOpen, party])

    function set<K extends keyof PartyInput>(field: K, value: PartyInput[K]) {
        setValues((previous) => ({ ...previous, [field]: value }))
    }

    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (values.kind === 'organisation' && !values.organisation_name.trim()) {
            setError(t('pages.participants.validation.organisationNameRequired'))
            return
        }
        if (values.kind === 'person' && !values.last_name.trim()) {
            setError(t('pages.zevSettings.parties.lastNameRequired'))
            return
        }
        onSubmit({ ...values, organisation_name: values.kind === 'organisation' ? values.organisation_name.trim() : '' })
    }

    const organisation = values.kind === 'organisation'

    return (
        <FormModal
            isOpen={isOpen}
            title={t(party ? 'pages.zevSettings.parties.editContact' : 'pages.zevSettings.parties.newContact')}
            onClose={onClose}
            maxWidth="760px"
        >
            <form className="form-grid" onSubmit={submit}>
                <label>
                    <span>{t('pages.participants.form.kind')}</span>
                    <select value={values.kind} onChange={(event) => set('kind', event.target.value as PartyInput['kind'])}>
                        <option value="person">{t('pages.participants.kind.person')}</option>
                        <option value="organisation">{t('pages.participants.kind.organisation')}</option>
                    </select>
                </label>
                {organisation && (
                    <label>
                        <span>{t('pages.participants.form.organisationName')}</span>
                        <input value={values.organisation_name} onChange={(event) => set('organisation_name', event.target.value)} required />
                    </label>
                )}
                <label>
                    <span>{t('pages.participants.form.title')}</span>
                    <select value={values.title} onChange={(event) => set('title', event.target.value as PartyInput['title'])}>
                        <option value="">{t('pages.zevs.titles.none')}</option>
                        {TITLE_KEYS.map((key) => (
                            <option key={key} value={key}>{t(`pages.zevs.titles.${key}` as Parameters<typeof t>[0])}</option>
                        ))}
                    </select>
                </label>
                <label>
                    <span>{t(organisation ? 'pages.participants.form.contactFirstName' : 'pages.participants.form.firstName')}</span>
                    <input value={values.first_name} onChange={(event) => set('first_name', event.target.value)} />
                </label>
                <label>
                    <span>{t(organisation ? 'pages.participants.form.contactLastName' : 'pages.participants.form.lastName')}</span>
                    <input value={values.last_name} onChange={(event) => set('last_name', event.target.value)} required={!organisation} />
                </label>
                <label style={{ gridColumn: '1 / -1' }}>
                    <span>{t('pages.participants.form.nameAddition')}</span>
                    <input value={values.name_addition} onChange={(event) => set('name_addition', event.target.value)} />
                </label>
                <label>
                    <span>{t('pages.participants.form.email')}</span>
                    <input type="email" value={values.email} onChange={(event) => set('email', event.target.value)} />
                </label>
                <label>
                    <span>{t('pages.participants.form.phone')}</span>
                    <input value={values.phone} onChange={(event) => set('phone', event.target.value)} />
                </label>
                <label style={{ gridColumn: '1 / -1' }}>
                    <span>{t('pages.participants.form.addressLine1')}</span>
                    <input value={values.address_line1} onChange={(event) => set('address_line1', event.target.value)} />
                </label>
                <label style={{ gridColumn: '1 / -1' }}>
                    <span>{t('pages.participants.form.addressLine2')}</span>
                    <input value={values.address_line2} onChange={(event) => set('address_line2', event.target.value)} />
                </label>
                <label>
                    <span>{t('pages.participants.form.postalCode')}</span>
                    <input value={values.postal_code} onChange={(event) => set('postal_code', event.target.value)} />
                </label>
                <label>
                    <span>{t('pages.participants.form.city')}</span>
                    <input value={values.city} onChange={(event) => set('city', event.target.value)} />
                </label>
                <label style={{ gridColumn: '1 / -1' }}>
                    <span>{t('pages.participants.form.notes')}</span>
                    <textarea rows={3} value={values.notes} onChange={(event) => set('notes', event.target.value)} />
                </label>
                {party && party.participations.length > 0 && (
                    <p className="muted" style={{ gridColumn: '1 / -1', margin: 0 }}>{t('pages.participants.form.sharedPartyHint')}</p>
                )}
                {error && <div className="error-banner" style={{ gridColumn: '1 / -1' }}>{error}</div>}
                <FormModalFooter onCancel={onClose} isPending={isPending} submitLabel={t(party ? 'common.save' : 'common.create')} />
            </form>
        </FormModal>
    )
}

function pick(party: Party): PartyInput {
    return {
        kind: party.kind,
        title: party.title,
        first_name: party.first_name,
        last_name: party.last_name,
        organisation_name: party.organisation_name,
        name_addition: party.name_addition,
        email: party.email,
        phone: party.phone,
        address_line1: party.address_line1,
        address_line2: party.address_line2,
        postal_code: party.postal_code,
        city: party.city,
        notes: party.notes,
    }
}
