import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiRequestError, ENDPOINTS, WRITE_TOKEN_HEADER, api, buildPath, setWriteToken } from './client'
import { apiError, mockApi } from '../test/mockApi'

afterEach(() => {
  setWriteToken('')
  vi.unstubAllGlobals()
})

describe('api client', () => {
  it('fills and encodes path parameters, and refuses a missing one', () => {
    expect(buildPath('editProfile', { profile_key: 'team a/b' })).toBe('/human-inputs/capability-profiles/team%20a%2Fb')
    expect(() => buildPath('editProfile')).toThrow(/profile_key/)
  })

  it('lists every route under /human-inputs', () => {
    for (const [, path] of Object.values(ENDPOINTS)) expect(path.startsWith('/human-inputs/')).toBe(true)
  })

  it('turns the API error envelope into an ApiRequestError with its code', async () => {
    mockApi({ 'GET /human-inputs/seasons/2099/kappa': apiError(409, 'prerequisite_missing', 'establish the codebook first') })
    const failure = api.kappa(2099)
    await expect(failure).rejects.toBeInstanceOf(ApiRequestError)
    await expect(failure).rejects.toMatchObject({ code: 'prerequisite_missing', status: 409, requestId: 'req-test' })
  })

  it('sends the write token on writes only', async () => {
    const mock = mockApi({
      'GET /human-inputs/capability-profiles': [],
      'POST /human-inputs/capability-profiles/p1/archive': { profile_key: 'p1' },
    })
    setWriteToken('secret-token')
    await api.listProfiles(false)
    await api.archiveProfile('p1', { archived_by: 'Test Person' })
    expect(mock.calls[0].headers[WRITE_TOKEN_HEADER]).toBeUndefined()
    expect(mock.calls[1].headers[WRITE_TOKEN_HEADER]).toBe('secret-token')
  })

  it('uploads a manual as the raw PDF body with its metadata in the query', async () => {
    const mock = mockApi({ 'POST /human-inputs/game-manuals': { status: 201, body: { manual: { id: 1 }, created: true } } })
    const file = new Blob(['%PDF-1.7 synthetic'], { type: 'application/pdf' })
    await api.uploadManual({ season: 2099, game_name: 'Synthetic', filename: 'm.pdf', uploaded_by: 'Test Person' }, file)
    const call = mock.calls[0]
    expect(call.headers['Content-Type']).toBe('application/pdf')
    expect(call.rawBody).toBe(file)
    expect(Object.fromEntries(call.query)).toEqual({ season: '2099', game_name: 'Synthetic', filename: 'm.pdf', uploaded_by: 'Test Person' })
  })
})
