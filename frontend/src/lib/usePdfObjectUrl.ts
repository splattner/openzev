import { useEffect, useState } from 'react'

type PdfFetcher = (signal: AbortSignal) => Promise<Blob>

type PdfObjectUrlState = {
  request: PdfFetcher | null
  url: string | null
  blob: Blob | null
  loading: boolean
  error: boolean
}

const IDLE_STATE: PdfObjectUrlState = {
  request: null,
  url: null,
  blob: null,
  loading: false,
  error: false,
}

/** Fetch an authenticated PDF and revoke its object URL when replaced or unmounted. */
export function usePdfObjectUrl(
  fetcher: PdfFetcher | null,
  enabled: boolean,
): {
  url: string | null
  blob: Blob | null
  loading: boolean
  error: boolean
} {
  const request = enabled ? fetcher : null
  const [state, setState] = useState<PdfObjectUrlState>(IDLE_STATE)

  useEffect(() => {
    if (!request) {
      setState(IDLE_STATE)
      return
    }

    const controller = new AbortController()
    let objectUrl: string | null = null
    let cancelled = false
    setState({ request, url: null, blob: null, loading: true, error: false })

    void request(controller.signal)
      .then((blob) => {
        if (cancelled) return
        // Some responses omit Content-Type; reject only declared non-PDF types.
        if (blob.type && !blob.type.startsWith('application/pdf')) throw new Error('Not a PDF')
        objectUrl = URL.createObjectURL(blob)
        setState({ request, url: objectUrl, blob, loading: false, error: false })
      })
      .catch(() => {
        if (!cancelled && !controller.signal.aborted) setState({ request, url: null, blob: null, loading: false, error: true })
      })

    return () => {
      cancelled = true
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [request])

  if (state.request === request) {
    return { url: state.url, blob: state.blob, loading: state.loading, error: state.error }
  }

  return request
    ? { url: null, blob: null, loading: true, error: false }
    : { url: IDLE_STATE.url, blob: IDLE_STATE.blob, loading: IDLE_STATE.loading, error: IDLE_STATE.error }
}
