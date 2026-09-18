// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import useLiveRoomState from './useLiveRoomState.js'

vi.mock('mqtt', () => ({ default: { connect: () => ({ on: vi.fn(), end: vi.fn() }) } }))
let root, container, monitor
function Probe({ onAuthRequired }) {
  monitor = useLiveRoomState({ mode: 'coach', accessToken: 'existing-token', onAuthRequired })
  return <p>{monitor.roomState?.privateName || monitor.requestState}</p>
}
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  root = createRoot(container)
  vi.stubGlobal('fetch', vi.fn())
})
afterEach(async () => {
  await act(async () => root.unmount())
  vi.unstubAllGlobals()
})
it('clears private data when a previously authorized session is revoked', async () => {
  fetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ revision: 1, privateName: 'Private athlete' }) })
  const lost = vi.fn()
  await act(async () => root.render(<Probe onAuthRequired={lost} />))
  expect(container.textContent).toBe('Private athlete')
  fetch.mockResolvedValueOnce({ ok: false, status: 403 })
  await act(async () => monitor.refresh({ preserveSnapshot: true }))
  expect(lost).toHaveBeenCalledOnce()
  expect(container.textContent).toBe('auth-required')
  expect(monitor.roomState).toBeNull()
})
