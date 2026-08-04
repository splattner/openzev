import { faUpload, faXmark } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import {
  fetchTransferSections,
  importZevArchive,
  inspectZevArchive,
  type ArchiveManifest,
  type ImportEntryError,
} from '../../lib/api/zevTransfer'
import { useToast } from '../../lib/toast'
import { TransferSectionPicker } from './TransferSectionPicker'
import { DEFAULT_SECTIONS, type TransferSectionName } from './transferSections'

type ZevImportModalProps = {
  isOpen: boolean
  onClose: () => void
  onImported: (zevId: string) => void
}

export function ZevImportModal({ isOpen, onClose, onImported }: ZevImportModalProps) {
  const { t } = useTranslation()
  const { pushToast } = useToast()

  const [file, setFile] = useState<File | null>(null)
  const [manifest, setManifest] = useState<ArchiveManifest | null>(null)
  const [selected, setSelected] = useState<TransferSectionName[]>([])
  const [name, setName] = useState('')
  const [fatalError, setFatalError] = useState<string | null>(null)
  const [entryErrors, setEntryErrors] = useState<ImportEntryError[]>([])
  const [totalErrors, setTotalErrors] = useState(0)

  const sectionsQuery = useQuery({
    queryKey: queryKeys.zev.transferSections(),
    queryFn: fetchTransferSections,
    enabled: isOpen,
  })
  const sections = sectionsQuery.data ?? DEFAULT_SECTIONS
  const available = manifest?.sections ?? []
  const unavailable = sections
    .map((section) => section.name)
    .filter((sectionName) => !available.includes(sectionName))

  function reset() {
    setFile(null)
    setManifest(null)
    setSelected([])
    setName('')
    setFatalError(null)
    setEntryErrors([])
    setTotalErrors(0)
  }

  function close() {
    reset()
    onClose()
  }

  const inspectMutation = useMutation({
    mutationFn: inspectZevArchive,
    onSuccess: (result) => {
      setManifest(result)
      // Everything the archive holds, pre-ticked: the common case is importing
      // all of it, and the picker still lets sections be dropped.
      setSelected(result.sections)
      setName(result.source_zev?.name ?? '')
      setFatalError(null)
    },
    onError: (error) => {
      setManifest(null)
      setSelected([])
      setFatalError(formatApiError(error, t('zevTransfer.unreadableArchive')))
    },
  })

  const importMutation = useMutation({
    mutationFn: () => importZevArchive(file as File, selected, name),
    onSuccess: (result) => {
      pushToast(t('zevTransfer.importSuccess', { name: result.zev_name }), 'success')
      const zevId = result.zev_id
      reset()
      onImported(zevId)
    },
    onError: (error) => {
      const data = (error as { response?: { data?: { detail?: string; errors?: ImportEntryError[]; total_errors?: number } } })
        .response?.data
      const entries = data?.errors ?? []
      setEntryErrors(entries)
      setTotalErrors(data?.total_errors ?? 0)
      // The backend's `detail` is an untranslated summary of the same count the
      // table below already states, so it is only worth showing when there is
      // no table — a malformed archive, a bad version, an unreachable server.
      setFatalError(
        entries.length > 0 ? null : data?.detail ?? formatApiError(error, t('zevTransfer.importFailed')),
      )
    },
  })

  function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const picked = event.target.files?.[0] ?? null
    setEntryErrors([])
    setTotalErrors(0)
    setFile(picked)
    if (picked) {
      inspectMutation.mutate(picked)
    } else {
      setManifest(null)
    }
  }

  const busy = inspectMutation.isPending || importMutation.isPending

  return (
    <FormModal isOpen={isOpen} title={t('zevTransfer.importTitle')} onClose={close} maxWidth="640px">
      <div style={{ display: 'grid', gap: '1.25rem' }}>
        <p className="muted" style={{ margin: 0 }}>
          {t('zevTransfer.importDescription')}
        </p>

        {/* Running the import twice makes two ZEVs. Saying so up front is
            cheaper than the support conversation about the duplicate. */}
        <div className="warning-banner">{t('zevTransfer.notIdempotentWarning')}</div>

        <label>
          <span>{t('zevTransfer.archiveFile')}</span>
          <input type="file" accept=".zip,application/zip" onChange={handleFile} disabled={busy} />
        </label>

        {inspectMutation.isPending && <div className="muted">{t('zevTransfer.reading')}</div>}

        {manifest && (
          <>
            {/* Inline grid: there is no shared definition-list class in the
                stylesheet, and this is the only place that needs one. */}
            <dl
              style={{
                margin: 0,
                display: 'grid',
                gridTemplateColumns: 'auto 1fr',
                gap: '0.35rem 1rem',
                fontSize: '0.9rem',
              }}
            >
              <dt className="muted">{t('zevTransfer.sourceZev')}</dt>
              <dd style={{ margin: 0 }}>{manifest.source_zev?.name || '—'}</dd>
              <dt className="muted">{t('zevTransfer.exportedAt')}</dt>
              <dd style={{ margin: 0 }}>{new Date(manifest.exported_at).toLocaleString()}</dd>
              <dt className="muted">{t('zevTransfer.formatVersion')}</dt>
              <dd style={{ margin: 0 }}>{manifest.format_version}</dd>
            </dl>

            <label>
              <span>{t('zevTransfer.newZevName')}</span>
              <input
                type="text"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={manifest.source_zev?.name}
                disabled={busy}
              />
            </label>

            <TransferSectionPicker
              sections={sections}
              selected={selected}
              onChange={setSelected}
              unavailable={unavailable}
              counts={manifest.counts}
              disabled={busy}
            />
          </>
        )}

        {fatalError && <div className="error-banner">{fatalError}</div>}

        {entryErrors.length > 0 && (
          <div className="page-stack" style={{ gap: '0.5rem' }}>
            <strong>{t('zevTransfer.rejectedEntries', { count: totalErrors })}</strong>
            <div style={{ maxHeight: '14rem', overflowY: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t('zevTransfer.errorSection')}</th>
                    <th>{t('zevTransfer.errorEntry')}</th>
                    <th>{t('zevTransfer.errorDetail')}</th>
                  </tr>
                </thead>
                <tbody>
                  {entryErrors.map((entry, index) => (
                    <tr key={`${entry.section}-${entry.position}-${index}`}>
                      <td>{t(`zevTransfer.sections.${entry.section}`)}</td>
                      <td>
                        {entry.label}
                        {entry.position !== null && (
                          <span className="muted"> ({t('zevTransfer.errorPosition', { position: entry.position })})</span>
                        )}
                      </td>
                      <td>
                        {Object.entries(entry.errors).map(([field, messages]) => (
                          <div key={field}>
                            {field !== '__all__' && <code>{field}: </code>}
                            {messages.join(' ')}
                          </div>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
          <button className="button button-secondary" type="button" onClick={close}>
            <FontAwesomeIcon icon={faXmark} fixedWidth />
            {t('common.cancel')}
          </button>
          <button
            className="button button-primary"
            type="button"
            disabled={!file || !manifest || selected.length === 0 || busy}
            onClick={() => importMutation.mutate()}
          >
            <FontAwesomeIcon icon={faUpload} fixedWidth />
            {importMutation.isPending ? t('zevTransfer.importing') : t('zevTransfer.import')}
          </button>
        </div>
      </div>
    </FormModal>
  )
}
