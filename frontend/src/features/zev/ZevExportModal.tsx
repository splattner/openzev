import { faDownload, faXmark } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { exportZevArchive, fetchTransferSections, readBlobError } from '../../lib/api/zevTransfer'
import { downloadBlob } from '../../lib/downloadBlob'
import { useToast } from '../../lib/toast'
import { TransferSectionPicker } from './TransferSectionPicker'
import { DEFAULT_SECTIONS, type TransferSectionName } from './transferSections'

type ZevExportModalProps = {
  isOpen: boolean
  zevId: string
  zevName: string
  onClose: () => void
}

// Structure-only by default: the archive's point is the community's setup.
// Readings and invoices are the bulk of a zip (and readings alone can stream
// for minutes), so opting into the data sections should be deliberate. Derived
// from the section list so a section added to the backend still ends up in the
// default selection unless it is explicitly a data section.
const DATA_SECTIONS: TransferSectionName[] = ['readings', 'invoices']
const INITIAL_SELECTION: TransferSectionName[] = DEFAULT_SECTIONS.map(
  (section) => section.name,
).filter((name) => !DATA_SECTIONS.includes(name))

export function ZevExportModal({ isOpen, zevId, zevName, onClose }: ZevExportModalProps) {
  const { t } = useTranslation()
  const { pushToast } = useToast()
  const [selected, setSelected] = useState<TransferSectionName[]>(INITIAL_SELECTION)

  // Reset to the structure-only default each time the dialog opens.
  useEffect(() => {
    if (isOpen) setSelected(INITIAL_SELECTION)
  }, [isOpen])

  const sectionsQuery = useQuery({
    queryKey: queryKeys.zev.transferSections(),
    queryFn: fetchTransferSections,
    enabled: isOpen,
  })
  const sections = sectionsQuery.data ?? DEFAULT_SECTIONS

  const exportMutation = useMutation({
    mutationFn: () => exportZevArchive(zevId, selected),
    onSuccess: ({ blob, filename }) => {
      downloadBlob(blob, filename)
      pushToast(t('zevTransfer.exportSuccess'), 'success')
      onClose()
    },
    onError: async (error) => {
      // The request asked for a Blob, so a 400's JSON body arrives as one too.
      const response = (error as { response?: { data?: unknown } }).response
      const detail = await readBlobError(response?.data)
      pushToast(detail ?? formatApiError(error, t('zevTransfer.exportFailed')), 'error')
    },
  })

  return (
    <FormModal isOpen={isOpen} title={t('zevTransfer.exportTitle')} onClose={onClose} maxWidth="560px">
      <div style={{ display: 'grid', gap: '1.25rem' }}>
        <p className="muted" style={{ margin: 0 }}>
          {t('zevTransfer.exportDescription', { name: zevName })}
        </p>

        <div className="warning-banner">{t('zevTransfer.personalDataWarning')}</div>

        <TransferSectionPicker
          sections={sections}
          selected={selected}
          onChange={setSelected}
          disabled={exportMutation.isPending}
        />

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
          <button className="button button-secondary" type="button" onClick={onClose}>
            <FontAwesomeIcon icon={faXmark} fixedWidth />
            {t('common.cancel')}
          </button>
          <button
            className="button button-primary"
            type="button"
            disabled={selected.length === 0 || exportMutation.isPending}
            onClick={() => exportMutation.mutate()}
          >
            <FontAwesomeIcon icon={faDownload} fixedWidth />
            {exportMutation.isPending ? t('zevTransfer.exporting') : t('zevTransfer.download')}
          </button>
        </div>
      </div>
    </FormModal>
  )
}
