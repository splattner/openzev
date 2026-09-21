import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Switch } from '@mantine/core'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCheck, faPen, faPlug, faPlus, faTrash, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import {
    createBackupDestination,
    deleteBackupDestination,
    fetchBackupDestinations,
    testBackupDestination,
    updateBackupDestination,
} from '../../lib/api/backups'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { useToast } from '../../lib/toast'
import { ConfirmDialog, useConfirmDialog } from '../../components/ConfirmDialog'
import { FormModal } from '../../components/FormModal'
import type { BackupDestination, BackupStatus } from '../../types/api'
import {
    EMPTY_DESTINATION_FORM,
    buildDestinationPayload,
    destinationTarget,
    destinationToForm,
    type DestinationFormState,
} from './backupHelpers'

export function BackupDestinationsSection({ status }: { status: BackupStatus | undefined }) {
    const { t } = useTranslation()
    const queryClient = useQueryClient()
    const { pushToast } = useToast()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const [modalOpen, setModalOpen] = useState(false)
    const [editing, setEditing] = useState<BackupDestination | null>(null)
    const [form, setForm] = useState<DestinationFormState>(EMPTY_DESTINATION_FORM)
    const [formError, setFormError] = useState<string | null>(null)
    const [testingId, setTestingId] = useState<string | null>(null)

    const destinationsQuery = useQuery({
        queryKey: queryKeys.backups.destinations(),
        queryFn: fetchBackupDestinations,
    })
    const destinations = destinationsQuery.data ?? []

    const encryptionAvailable = status?.encrypted ?? false
    const environmentCredentials = status?.environment_credentials ?? false

    function refresh() {
        void queryClient.invalidateQueries({ queryKey: queryKeys.backups.destinations() })
        void queryClient.invalidateQueries({ queryKey: queryKeys.backups.status() })
    }

    function closeModal() {
        setModalOpen(false)
        setEditing(null)
        setFormError(null)
    }

    const saveMutation = useMutation({
        mutationFn: () => {
            const payload = buildDestinationPayload(form, editing ?? undefined)
            return editing ? updateBackupDestination(editing.id, payload) : createBackupDestination(payload)
        },
        onSuccess: () => {
            refresh()
            pushToast(t('pages.backups.destinations.saved'), 'success')
            closeModal()
        },
        onError: (error) => setFormError(formatApiError(error)),
    })

    const deleteMutation = useMutation({
        mutationFn: (id: string) => deleteBackupDestination(id),
        onSuccess: () => {
            refresh()
            pushToast(t('pages.backups.destinations.deleted'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error), 'error'),
    })

    async function runTest(destination: BackupDestination) {
        setTestingId(destination.id)
        try {
            await testBackupDestination(destination.id)
            pushToast(t('pages.backups.destinations.testOk', { name: destination.name }), 'success')
        } catch (error) {
            pushToast(
                t('pages.backups.destinations.testFailed', { name: destination.name, reason: formatApiError(error) }),
                'error',
            )
        } finally {
            setTestingId(null)
        }
    }

    function openCreate() {
        setEditing(null)
        setForm(EMPTY_DESTINATION_FORM)
        setFormError(null)
        setModalOpen(true)
    }

    function openEdit(destination: BackupDestination) {
        setEditing(destination)
        setForm(destinationToForm(destination))
        setFormError(null)
        setModalOpen(true)
    }

    function confirmDelete(destination: BackupDestination) {
        confirm({
            title: t('pages.backups.destinations.deleteTitle'),
            message: t('pages.backups.destinations.deleteMessage', { name: destination.name }),
            confirmText: t('common.delete'),
            isDangerous: true,
            onConfirm: () => deleteMutation.mutateAsync(destination.id),
        })
    }

    function update<K extends keyof DestinationFormState>(key: K, value: DestinationFormState[K]) {
        setForm((previous) => ({ ...previous, [key]: value }))
    }

    function submit(event: FormEvent) {
        event.preventDefault()
        setFormError(null)
        saveMutation.mutate()
    }

    const isS3 = form.kind === 's3'
    // The server refuses to store a secret it cannot encrypt, so say so up front
    // rather than letting the admin find out from a rejected save.
    const secretDisabled = !encryptionAvailable

    return (
        <section className="card page-stack">
            <div className="actions-row actions-row-wrap" style={{ justifyContent: 'space-between' }}>
                <div style={{ flex: '1 1 22rem', minWidth: 0 }}>
                    <h3 style={{ margin: 0 }}>{t('pages.backups.destinations.title')}</h3>
                    <p className="muted" style={{ margin: '0.25rem 0 0' }}>{t('pages.backups.destinations.description')}</p>
                </div>
                <button type="button" className="button button-primary" onClick={openCreate}>
                    <FontAwesomeIcon icon={faPlus} fixedWidth />
                    {t('pages.backups.destinations.add')}
                </button>
            </div>

            {destinationsQuery.isLoading ? (
                <div className="muted">{t('common.loading')}</div>
            ) : destinations.length === 0 ? (
                <div className="muted">{t('pages.backups.destinations.empty')}</div>
            ) : (
                <div className="table-card">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('pages.backups.destinations.columns.name')}</th>
                                <th>{t('pages.backups.destinations.columns.type')}</th>
                                <th>{t('pages.backups.destinations.columns.target')}</th>
                                <th>{t('pages.backups.destinations.columns.credentials')}</th>
                                <th>{t('pages.backups.destinations.columns.keeps')}</th>
                                <th>{t('pages.backups.destinations.columns.status')}</th>
                                <th>{t('common.actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {destinations.map((destination) => (
                                <tr key={destination.id}>
                                    <td><strong>{destination.name}</strong></td>
                                    <td>{t(`pages.backups.destinations.kind.${destination.kind}`)}</td>
                                    <td style={{ minWidth: '12rem', overflowWrap: 'anywhere' }}>{destinationTarget(destination)}</td>
                                    <td>
                                        {destination.kind === 's3'
                                            ? t(`pages.backups.destinations.credentialMode.${destination.credential_mode}`)
                                            : '—'}
                                    </td>
                                    <td>
                                        {destination.retention_count > 0
                                            ? t('pages.backups.destinations.keepsN', { count: destination.retention_count })
                                            : t('pages.backups.destinations.keepsAll')}
                                    </td>
                                    <td>
                                        <span className={`badge ${destination.enabled ? 'badge-success' : 'badge-neutral'}`}>
                                            {destination.enabled
                                                ? t('pages.backups.destinations.enabled')
                                                : t('pages.backups.destinations.disabled')}
                                        </span>
                                    </td>
                                    <td className="actions-cell">
                                        <div className="actions-cell-content">
                                            <button
                                                type="button"
                                                className="button button-secondary button-compact"
                                                disabled={testingId === destination.id}
                                                onClick={() => void runTest(destination)}
                                            >
                                                <FontAwesomeIcon icon={faPlug} fixedWidth />
                                                {t('pages.backups.destinations.test')}
                                            </button>
                                            <button
                                                type="button"
                                                className="button button-secondary button-compact"
                                                onClick={() => openEdit(destination)}
                                            >
                                                <FontAwesomeIcon icon={faPen} fixedWidth />
                                                {t('common.edit')}
                                            </button>
                                            <button
                                                type="button"
                                                className="button button-danger button-compact"
                                                onClick={() => confirmDelete(destination)}
                                            >
                                                <FontAwesomeIcon icon={faTrash} fixedWidth />
                                                {t('common.delete')}
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            <FormModal
                isOpen={modalOpen}
                title={editing ? t('pages.backups.form.editTitle') : t('pages.backups.form.createTitle')}
                onClose={closeModal}
                maxWidth="640px"
            >
                <form onSubmit={submit} className="page-stack">
                    <label>
                        <span>{t('pages.backups.form.name')}</span>
                        <input
                            type="text"
                            value={form.name}
                            onChange={(event) => update('name', event.target.value)}
                            required
                            maxLength={100}
                        />
                    </label>

                    <label>
                        <span>{t('pages.backups.form.kind')}</span>
                        <select
                            value={form.kind}
                            onChange={(event) => update('kind', event.target.value as DestinationFormState['kind'])}
                            disabled={editing !== null}
                        >
                            <option value="local">{t('pages.backups.destinations.kind.local')}</option>
                            <option value="s3">{t('pages.backups.destinations.kind.s3')}</option>
                        </select>
                    </label>

                    {!isS3 && (
                        <label>
                            <span>{t('pages.backups.form.path')}</span>
                            <input
                                type="text"
                                value={form.path}
                                onChange={(event) => update('path', event.target.value)}
                                placeholder="/var/backups/openzev"
                                required
                            />
                            <small className="muted">{t('pages.backups.form.pathHint')}</small>
                        </label>
                    )}

                    {isS3 && (
                        <>
                            <label>
                                <span>{t('pages.backups.form.bucket')}</span>
                                <input
                                    type="text"
                                    value={form.bucket}
                                    onChange={(event) => update('bucket', event.target.value)}
                                    required
                                />
                            </label>
                            <label>
                                <span>{t('pages.backups.form.prefix')}</span>
                                <input
                                    type="text"
                                    value={form.prefix}
                                    onChange={(event) => update('prefix', event.target.value)}
                                    placeholder="openzev/prod"
                                />
                                <small className="muted">{t('pages.backups.form.prefixHint')}</small>
                            </label>
                            <label>
                                <span>{t('pages.backups.form.region')}</span>
                                <input
                                    type="text"
                                    value={form.region}
                                    onChange={(event) => update('region', event.target.value)}
                                    placeholder="eu-central-1"
                                />
                            </label>
                            <label>
                                <span>{t('pages.backups.form.endpointUrl')}</span>
                                <input
                                    type="url"
                                    value={form.endpoint_url}
                                    onChange={(event) => update('endpoint_url', event.target.value)}
                                    placeholder="https://minio.example.com:9000"
                                />
                                <small className="muted">{t('pages.backups.form.endpointHint')}</small>
                            </label>

                            {environmentCredentials && (
                                <div className="info-banner">{t('pages.backups.form.environmentCredentials')}</div>
                            )}

                            <label>
                                <span>{t('pages.backups.form.accessKeyId')}</span>
                                <input
                                    type="text"
                                    value={form.access_key_id}
                                    onChange={(event) => update('access_key_id', event.target.value)}
                                    autoComplete="off"
                                />
                            </label>
                            <label>
                                <span>{t('pages.backups.form.secretAccessKey')}</span>
                                <input
                                    type="password"
                                    value={form.secret_access_key}
                                    onChange={(event) => update('secret_access_key', event.target.value)}
                                    autoComplete="new-password"
                                    disabled={secretDisabled || form.remove_secret}
                                />
                                {secretDisabled ? (
                                    <small className="muted">{t('pages.backups.form.secretNeedsKey')}</small>
                                ) : editing?.has_secret_access_key ? (
                                    <small className="muted">{t('pages.backups.form.secretStoredHint')}</small>
                                ) : (
                                    <small className="muted">{t('pages.backups.form.credentialsHint')}</small>
                                )}
                            </label>
                            {editing?.has_secret_access_key && (
                                <Switch
                                    checked={form.remove_secret}
                                    onChange={(event) => {
                                        const checked = event.currentTarget.checked
                                        setForm((previous) => ({
                                            ...previous,
                                            remove_secret: checked,
                                            secret_access_key: checked ? '' : previous.secret_access_key,
                                        }))
                                    }}
                                    label={t('pages.backups.form.removeSecret')}
                                />
                            )}

                            <label>
                                <span>{t('pages.backups.form.serverSideEncryption')}</span>
                                <select
                                    value={form.server_side_encryption}
                                    onChange={(event) => update('server_side_encryption', event.target.value)}
                                >
                                    <option value="AES256">{t('pages.backups.form.sseAes256')}</option>
                                    <option value="aws:kms">{t('pages.backups.form.sseKms')}</option>
                                    <option value="">{t('pages.backups.form.sseNone')}</option>
                                </select>
                            </label>
                        </>
                    )}

                    <label>
                        <span>{t('pages.backups.form.retention')}</span>
                        <input
                            type="number"
                            min={0}
                            step={1}
                            inputMode="numeric"
                            value={form.retention_count}
                            onChange={(event) => update('retention_count', event.target.value)}
                        />
                        <small className="muted">{t('pages.backups.form.retentionHint')}</small>
                    </label>

                    <Switch
                        checked={form.enabled}
                        onChange={(event) => update('enabled', event.currentTarget.checked)}
                        label={t('pages.backups.form.enabled')}
                    />

                    {formError && <div className="error-banner">{formError}</div>}

                    <div className="actions-row actions-row-end actions-row-wrap">
                        <button
                            type="button"
                            className="button button-secondary"
                            onClick={closeModal}
                            disabled={saveMutation.isPending}
                        >
                            <FontAwesomeIcon icon={faXmark} fixedWidth />
                            {t('common.cancel')}
                        </button>
                        <button type="submit" className="button button-primary" disabled={saveMutation.isPending}>
                            <FontAwesomeIcon icon={faCheck} fixedWidth />
                            {saveMutation.isPending ? t('common.saving') : editing ? t('common.save') : t('common.create')}
                        </button>
                    </div>
                </form>
            </FormModal>

            {dialog && (
                <ConfirmDialog
                    title={dialog.title}
                    message={dialog.message}
                    confirmText={dialog.confirmText}
                    isDangerous={dialog.isDangerous}
                    isLoading={dialogLoading}
                    onConfirm={handleConfirm}
                    onCancel={handleCancel}
                />
            )}
        </section>
    )
}
