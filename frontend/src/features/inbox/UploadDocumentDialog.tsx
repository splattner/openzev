import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faPaperPlane } from '@fortawesome/free-solid-svg-icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { FormModalFooter } from '../../components/FormModalFooter'
import { formatApiError } from '../../lib/api/errors'
import { uploadInboxDocument } from '../../lib/api/inbox'
import { queryKeys } from '../../lib/api/queryKeys'
import type { DeliveryResult, Participant } from '../../types/api'
import { AudienceFields, type Audience } from './AudienceFields'
import { DeliveryResultNotice } from './DeliveryResultNotice'
import { formatFileSize, MAX_UPLOAD_BYTES, uploadFileProblem } from './documentPresentation'
import './inbox.css'

type UploadDocumentDialogProps = {
  isOpen: boolean
  onClose: () => void
  zevId: string
  participants: readonly Participant[]
}

/** Deliver one PDF to the whole community or to chosen participants (spec §7.2). */
export function UploadDocumentDialog({ isOpen, onClose, zevId, participants }: UploadDocumentDialogProps) {
  const { t } = useTranslation()
  return (
    <FormModal isOpen={isOpen} title={t('inbox.upload.title')} onClose={onClose} size="md">
      {isOpen ? <UploadForm onClose={onClose} zevId={zevId} participants={participants} /> : null}
    </FormModal>
  )
}

function UploadForm({ onClose, zevId, participants }: Omit<UploadDocumentDialogProps, 'isOpen'>) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [title, setTitle] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [audience, setAudience] = useState<Audience>('all')
  const [selected, setSelected] = useState<string[]>([])
  const [result, setResult] = useState<DeliveryResult | null>(null)

  const mutation = useMutation({
    mutationFn: () => uploadInboxDocument({ zev: zevId, title: title.trim(), file: file as File, audience, participantIds: selected }),
    onSuccess: (data) => {
      setResult(data)
      void queryClient.invalidateQueries({ queryKey: queryKeys.inbox.all })
    },
  })

  const problem = file ? uploadFileProblem(file) : null
  const invalid = !title.trim() || !file || problem !== null || (audience === 'selected' && selected.length === 0)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (invalid || mutation.isPending) return
    mutation.mutate()
  }

  if (result) {
    return (
      <div className="grid">
        <DeliveryResultNotice result={result} />
        <div className="dialog-actions">
          <button type="button" className="button button-primary" onClick={onClose}>{t('common.close')}</button>
        </div>
      </div>
    )
  }

  return (
    <form className="inline-form grid" onSubmit={submit} noValidate>
      <label className="grid-span-full">
        <span>{t('inbox.upload.titleField')}</span>
        <input type="text" maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} required />
      </label>
      <label className="grid-span-full">
        <span>{t('inbox.upload.file')}</span>
        <input
          type="file"
          accept="application/pdf,.pdf"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          aria-invalid={problem ? true : undefined}
          required
        />
        <small className={problem ? 'text-error' : 'muted'}>
          {problem
            ? t(`inbox.upload.problem.${problem}`, { limit: formatFileSize(MAX_UPLOAD_BYTES) })
            : t('inbox.upload.fileHint', { limit: formatFileSize(MAX_UPLOAD_BYTES) })}
        </small>
      </label>
      <AudienceFields
        name="inbox-upload-audience"
        audience={audience}
        onAudienceChange={setAudience}
        participants={participants}
        selected={selected}
        onSelectedChange={setSelected}
        allLabel={t('inbox.upload.audienceAll')}
        disabled={mutation.isPending}
      />
      {mutation.isError && (
        <p role="alert" className="text-error grid-span-full m-0">{formatApiError(mutation.error, t('common.error'))}</p>
      )}
      <FormModalFooter
        onCancel={onClose}
        isPending={mutation.isPending}
        disabled={invalid}
        submitIcon={<FontAwesomeIcon icon={faPaperPlane} fixedWidth />}
        submitLabel={t('inbox.upload.submit')}
      />
    </form>
  )
}
