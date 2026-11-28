import type { QueryClient } from '@tanstack/react-query'
import { queryKeys } from '../../lib/api/queryKeys'

// Broad prefixes on purpose: a change can touch any community's period overview and cockpit cards.
export function refreshInvoiceViews(queryClient: QueryClient) {
    void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.lists() })
    void queryClient.invalidateQueries({ queryKey: ['invoices', 'period-overview'] })
    void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.mine() })
    void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.credits() })
    for (const key of ['readiness', 'readiness-list', 'attention']) {
        void queryClient.invalidateQueries({ queryKey: ['invoices', key] })
    }
}
