import axios from 'axios'
import MockAdapter from 'axios-mock-adapter'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { api, API_BASE_URL } from '../src/lib/api/client'

const REFRESH_URL = `${API_BASE_URL}/auth/token/refresh/`

describe('api refresh interceptor', () => {
  let apiMock: MockAdapter
  let axiosMock: MockAdapter

  beforeEach(() => {
    apiMock = new MockAdapter(api)
    axiosMock = new MockAdapter(axios)
  })

  afterEach(() => {
    apiMock.restore()
    axiosMock.restore()
  })

  it('refreshes the session on 401 and retries the original request', async () => {
    apiMock
      .onGet('/protected')
      .replyOnce(401)
      .onGet('/protected')
      .reply(200, { ok: true })

    axiosMock.onPost(REFRESH_URL).reply(200)

    const response = await api.get('/protected')

    expect(response.data.ok).toBe(true)
    // The refresh endpoint is called exactly once, with no body (the httpOnly cookie carries the token).
    expect(axiosMock.history.post).toHaveLength(1)
    expect(axiosMock.history.post[0].url).toBe(REFRESH_URL)
  })

  it('propagates the error when the refresh request fails', async () => {
    apiMock.onGet('/protected').replyOnce(401)
    axiosMock.onPost(REFRESH_URL).reply(401)

    await expect(api.get('/protected')).rejects.toBeDefined()
  })

  it('does not attempt to refresh when the failing request targets an auth/token endpoint', async () => {
    apiMock.onPost('/auth/token/refresh/').reply(401)

    await expect(api.post('/auth/token/refresh/', null)).rejects.toBeDefined()
    // No recursive refresh call should be made.
    expect(axiosMock.history.post).toHaveLength(0)
  })

  it('reuses one refresh request for concurrent 401 responses', async () => {
    apiMock.onGet('/protected-a').replyOnce(401).onGet('/protected-a').reply(200, { ok: 'a' })
    apiMock.onGet('/protected-b').replyOnce(401).onGet('/protected-b').reply(200, { ok: 'b' })
    axiosMock.onPost(REFRESH_URL).reply(200)

    const [responseA, responseB] = await Promise.all([api.get('/protected-a'), api.get('/protected-b')])

    expect(responseA.data.ok).toBe('a')
    expect(responseB.data.ok).toBe('b')
    // A single shared refresh request should serve both concurrent failures.
    expect(axiosMock.history.post).toHaveLength(1)
  })
})
