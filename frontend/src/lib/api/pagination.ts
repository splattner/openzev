import type { PaginatedResponse } from '../../types/api'
import { api, API_BASE_URL } from './client'

/** Hard cap on page requests; a buggy `next` chain must not loop forever. */
const MAX_PAGES = 200

// DRF builds `next` from the request Host, which behind the dev proxy is an
// address the browser cannot reach — rewrite each hop to a base-relative URL.
const BASE_PATH = toPathPrefix(API_BASE_URL)

function toPathPrefix(baseUrl: string): string {
  try {
    return new URL(baseUrl).pathname.replace(/\/+$/, '')
  } catch {
    // Relative base (the common case): the prefix is the value itself.
    return baseUrl.replace(/\/+$/, '')
  }
}

/** Rewrite DRF's absolute `next` link into the base-relative form used here. */
function nextToRelative(next: string): string {
  let url: URL | null = null
  try {
    url = new URL(next)
  } catch {
    // Already-relative link: take it apart without an origin.
  }
  let pathname: string
  let search: string
  if (url) {
    pathname = url.pathname
    search = url.search
  } else {
    const queryIndex = next.indexOf('?')
    pathname = queryIndex === -1 ? next : next.slice(0, queryIndex)
    search = queryIndex === -1 ? '' : next.slice(queryIndex)
  }
  if (BASE_PATH && pathname.startsWith(`${BASE_PATH}/`)) {
    pathname = pathname.slice(BASE_PATH.length)
  }
  return pathname + search
}

/** Walk every page of a DRF PageNumberPagination endpoint and return all rows. */
export async function fetchAllPages<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
): Promise<T[]> {
  const all: T[] = []
  let next: string | null = null
  let requestCount = 0

  do {
    if (requestCount >= MAX_PAGES) {
      throw new Error(`fetchAllPages: exceeded ${MAX_PAGES} page requests while fetching ${path}`)
    }
    const target: string = next ? nextToRelative(next) : path
    const data: PaginatedResponse<T> | T[] = (
      await api.get<PaginatedResponse<T> | T[]>(target, next ? undefined : { params })
    ).data
    // Guard against an endpoint that is not DRF-paginated at all.
    if (Array.isArray(data)) {
      return data
    }
    all.push(...data.results)
    next = data.next
    requestCount += 1
  } while (next)

  return all
}

