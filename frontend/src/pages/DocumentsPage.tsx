import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FilterTabs } from '../components/FilterTabs'
import { Notice } from '../components/Notice'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '../components/PageSkeleton'
import {
  countByKind,
  DOCUMENT_KINDS,
  groupByYear,
} from '../features/inbox/documentPresentation'
import { DocumentsList } from '../features/inbox/DocumentsList'
import { listInboxDocuments } from '../lib/api/inbox'
import { queryKeys } from '../lib/api/queryKeys'
import { useAuth } from '../lib/auth'
import { ownParticipantIds, soleCommunityName } from '../lib/membership'
import type { DocumentKind } from '../types/api'

type KindFilter = 'all' | DocumentKind

/**
 * What was delivered to the account (`/me/documents`, SPEC-2026-11-participant-document-inbox §7.1):
 * a read-only list over the inbox, grouped by year. Rows are addressed to the participant row, so
 * documents delivered before the account existed appear as soon as it is linked, and a former
 * participant still reads what it was sent. A manager who is also a participant sees only their own.
 */
export function DocumentsPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [kind, setKind] = useState<KindFilter>('all')
  const [zevId, setZevId] = useState('')

  const query = useQuery({ queryKey: queryKeys.inbox.list('mine'), queryFn: () => listInboxDocuments() })
  const own = useMemo(() => ownParticipantIds(user), [user])
  const documents = useMemo(
    () => (query.data ?? []).filter((document) => document.participant != null && own.has(document.participant)),
    [query.data, own],
  )

  const memberships = user?.memberships ?? []
  const showCommunity = memberships.length > 1
  const inCommunity = zevId ? documents.filter((document) => document.zev === zevId) : documents
  const visible = kind === 'all' ? inCommunity : inCommunity.filter((document) => document.kind === kind)
  const counts = countByKind(inCommunity)

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow={showCommunity ? t('inbox.allCommunities') : soleCommunityName(user)}
        title={t('inbox.title')}
        description={t('inbox.description')}
      />

      {query.isError && query.data && (
        <Notice tone="warning" onRetry={() => void query.refetch()} isRetrying={query.isFetching}>{t('inbox.failed')}</Notice>
      )}
      {query.isLoading ? (
        <PageSkeleton variant="tableRows" />
      ) : query.isError && !query.data ? (
        <Notice tone="error" onRetry={() => void query.refetch()} isRetrying={query.isFetching}>{t('inbox.failed')}</Notice>
      ) : documents.length === 0 ? (
        <div className="card">
          <h3 className="mt-0">{t('inbox.empty.title')}</h3>
          <p className="muted">{t('inbox.empty.description')}</p>
        </div>
      ) : (
        <>
          <div className="actions-row">
            <FilterTabs<KindFilter>
              label={t('inbox.filter.kind')}
              value={kind}
              onChange={setKind}
              tabs={[
                { value: 'all', label: t('inbox.filter.all'), count: inCommunity.length },
                ...DOCUMENT_KINDS.map((value) => ({ value, label: t(`inbox.kind.${value}`), count: counts[value] })),
              ]}
            />
            {showCommunity && (
              <label>
                <span className="visually-hidden">{t('inbox.filter.community')}</span>
                <select value={zevId} onChange={(event) => setZevId(event.target.value)} aria-label={t('inbox.filter.community')}>
                  <option value="">{t('inbox.allCommunities')}</option>
                  {memberships.filter((membership) => membership.participants.length > 0).map((membership) => (
                    <option key={membership.zev} value={membership.zev}>{membership.zev_name}</option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {visible.length === 0 ? (
            <p className="muted">{t('inbox.filter.none')}</p>
          ) : (
            <DocumentsList groups={groupByYear(visible)} showCommunity={showCommunity && !zevId} />
          )}
        </>
      )}
    </div>
  )
}
