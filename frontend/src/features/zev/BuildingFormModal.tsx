import { useEffect, useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { fetchParties, locateBuilding } from '../../lib/api/zev'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { coordinateInput } from '../../lib/pvPlanes'
import type { Building, BuildingInput, Party } from '../../types/api'

interface Props {
    isOpen: boolean
    zevId: string
    /** The building to edit; absent to add a new one. */
    building?: Building | null
    isPending: boolean
    onClose: () => void
    onSubmit: (input: BuildingInput) => void
}

function emptyBuilding(zevId: string): BuildingInput {
    return { zev: zevId, name: '', address_line1: '', address_line2: '', postal_code: '', city: '', egid: null, notes: '', latitude: null, longitude: null }
}

/**
 * Add or edit a building of the ZEV (#890): where its metering points are,
 * as opposed to a participant's billing address. A new building can take its
 * address from one of the ZEV's parties.
 */
export function BuildingFormModal({ isOpen, zevId, building, isPending, onClose, onSubmit }: Props) {
    const { t } = useTranslation()
    const [values, setValues] = useState<BuildingInput>(emptyBuilding(zevId))
    const [egidText, setEgidText] = useState('')
    const [latitudeText, setLatitudeText] = useState('')
    const [longitudeText, setLongitudeText] = useState('')
    const [locating, setLocating] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const partiesQuery = useQuery({
        queryKey: queryKeys.zev.parties(zevId),
        queryFn: () => fetchParties(zevId),
        enabled: isOpen && !building && Boolean(zevId),
    })
    const withAddress = (partiesQuery.data ?? []).filter((party) => party.address_line1.trim())

    useEffect(() => {
        if (!isOpen) return
        const next: BuildingInput = building
            ? {
                zev: building.zev,
                name: building.name,
                address_line1: building.address_line1,
                address_line2: building.address_line2,
                postal_code: building.postal_code,
                city: building.city,
                egid: building.egid,
                notes: building.notes,
                latitude: building.latitude,
                longitude: building.longitude,
            }
            : emptyBuilding(zevId)
        setValues(next)
        setEgidText(next.egid === null ? '' : String(next.egid))
        setLatitudeText(next.latitude ?? '')
        setLongitudeText(next.longitude ?? '')
        setError(null)
    }, [isOpen, building, zevId])

    function set<K extends keyof BuildingInput>(field: K, value: BuildingInput[K]) {
        setValues((previous) => ({ ...previous, [field]: value }))
    }

    function copyFromParty(party: Party) {
        setValues((previous) => ({
            ...previous,
            name: previous.name.trim() ? previous.name : party.address_line1,
            address_line1: party.address_line1,
            address_line2: party.address_line2,
            postal_code: party.postal_code,
            city: party.city,
        }))
    }

    async function locate() {
        setLocating(true)
        setError(null)
        try {
            const found = await locateBuilding({ address_line1: values.address_line1, postal_code: values.postal_code, city: values.city })
            setLatitudeText(found.latitude.toFixed(5))
            setLongitudeText(found.longitude.toFixed(5))
        } catch (failure) {
            setError(formatApiError(failure, t('pages.meteringPoints.buildings.locateFailed')))
        } finally {
            setLocating(false)
        }
    }

    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!values.name.trim()) {
            setError(t('pages.meteringPoints.buildings.nameRequired'))
            return
        }
        const egid = egidText.trim() === '' ? null : Number(egidText)
        if (egid !== null && (!Number.isInteger(egid) || egid < 0 || egid > 999_999_999)) {
            setError(t('pages.meteringPoints.buildings.egidInvalid'))
            return
        }
        const latitude = coordinateInput(latitudeText, 90)
        const longitude = coordinateInput(longitudeText, 180)
        if (latitude === undefined || longitude === undefined || (latitude === null) !== (longitude === null)) {
            setError(t('pages.meteringPoints.buildings.locationInvalid'))
            return
        }
        onSubmit({ ...values, name: values.name.trim(), egid, latitude, longitude })
    }

    return (
        <FormModal
            isOpen={isOpen}
            title={t(building ? 'pages.meteringPoints.buildings.edit' : 'pages.meteringPoints.buildings.add')}
            onClose={onClose}
        >
            <form className="form-grid" onSubmit={submit}>
                {!building && withAddress.length > 0 && (
                    <label className="grid-span-full">
                        <span>{t('pages.meteringPoints.buildings.copyFromParticipant')}</span>
                        <select
                            value=""
                            onChange={(event) => {
                                const party = withAddress.find((candidate) => candidate.id === event.target.value)
                                if (party) copyFromParty(party)
                            }}
                        >
                            <option value="">{t('pages.meteringPoints.buildings.copyFromParticipantPlaceholder')}</option>
                            {withAddress.map((party) => (
                                <option key={party.id} value={party.id}>
                                    {`${party.display_name} – ${party.address_line1}`}
                                </option>
                            ))}
                        </select>
                    </label>
                )}
                <p className="muted grid-span-full m-0">{t('pages.meteringPoints.buildings.hint')}</p>
                <label className="grid-span-full">
                    <span>{t('pages.meteringPoints.buildings.name')}</span>
                    <input value={values.name} onChange={(event) => set('name', event.target.value)} maxLength={200} required />
                    <small className="muted">{t('pages.meteringPoints.buildings.nameHint')}</small>
                </label>
                <label className="grid-span-full">
                    <span>{t('pages.participants.form.addressLine1')}</span>
                    <input value={values.address_line1} onChange={(event) => set('address_line1', event.target.value)} />
                </label>
                <label className="grid-span-full">
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
                <label>
                    <span>{t('pages.meteringPoints.buildings.egid')}</span>
                    <input
                        type="number"
                        inputMode="numeric"
                        min={0}
                        max={999999999}
                        value={egidText}
                        onChange={(event) => setEgidText(event.target.value)}
                    />
                    <small className="muted">{t('pages.meteringPoints.buildings.egidHint')}</small>
                </label>
                <fieldset className="grid-span-full form-grid" style={{ border: 0, padding: 0, margin: 0 }}>
                    <legend className="muted" style={{ padding: 0, marginBottom: '0.25rem' }}>{t('pages.meteringPoints.buildings.location')}</legend>
                    <label>
                        <span>{t('pages.meteringPoints.buildings.latitude')}</span>
                        <input inputMode="decimal" value={latitudeText} onChange={(event) => setLatitudeText(event.target.value)} placeholder="47.37691" />
                    </label>
                    <label>
                        <span>{t('pages.meteringPoints.buildings.longitude')}</span>
                        <input inputMode="decimal" value={longitudeText} onChange={(event) => setLongitudeText(event.target.value)} placeholder="8.54169" />
                    </label>
                    <div className="grid-span-full actions-row actions-row-wrap">
                        <button
                            type="button"
                            className="button button-secondary button-compact"
                            disabled={locating || !values.address_line1.trim() || !values.city.trim()}
                            onClick={() => void locate()}
                        >
                            {locating ? t('pages.meteringPoints.buildings.locating') : t('pages.meteringPoints.buildings.locate')}
                        </button>
                        <small className="muted">{t('pages.meteringPoints.buildings.locationHint')}</small>
                    </div>
                </fieldset>
                <label className="grid-span-full">
                    <span>{t('pages.participants.form.notes')}</span>
                    <textarea rows={3} value={values.notes} onChange={(event) => set('notes', event.target.value)} />
                </label>
                {error && <div className="error-banner grid-span-full">{error}</div>}
                <FormModalFooter onCancel={onClose} isPending={isPending} submitLabel={t(building ? 'common.save' : 'common.create')} />
            </form>
        </FormModal>
    )
}
