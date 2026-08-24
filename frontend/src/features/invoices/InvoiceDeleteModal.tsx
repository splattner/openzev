import { useTranslation } from 'react-i18next'

type InvoiceDeleteModalProps = {
  isOpen: boolean
  isPending: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function InvoiceDeleteModal({ isOpen, isPending, onCancel, onConfirm }: InvoiceDeleteModalProps) {
  const { t } = useTranslation()

  if (!isOpen) {
    return null
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={onCancel}
    >
      <div
        style={{
          backgroundColor: 'var(--surface-card)',
          borderRadius: '0.5rem',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1)',
          maxWidth: '400px',
          width: '90%',
          padding: '2rem',
        }}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 style={{ margin: '0 0 1rem 0', color: 'var(--danger-600)' }}>{t('pages.invoices.deleteModal.title')}</h2>
        <p style={{ margin: '0 0 1.5rem 0', color: 'var(--ink-soft)' }}>
          {t('pages.invoices.deleteModal.message')}
        </p>
        <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
          <button className="button button-secondary" type="button" disabled={isPending} onClick={onCancel}>
            {t('common.cancel')}
          </button>
          <button className="button button-danger" type="button" disabled={isPending} onClick={onConfirm}>
            {isPending ? t('pages.invoices.deleting') : t('pages.invoices.delete')}
          </button>
        </div>
      </div>
    </div>
  )
}
