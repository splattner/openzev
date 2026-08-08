export function getLatestEmailLog(invoice: {
  email_logs?: Array<{ created_at: string; recipient: string; status: string; id: string }>
} | null) {
  if (!invoice?.email_logs?.length) return null
  return [...invoice.email_logs].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0]
}
