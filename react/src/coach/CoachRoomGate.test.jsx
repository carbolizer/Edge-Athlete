// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import CoachRoomGate from './CoachRoomGate.jsx'
import { fetchCurrentCoach, getCoachToken, setCoachToken } from './api.js'
import { navigate } from '../router.js'

vi.mock('./api.js', () => ({ fetchCurrentCoach: vi.fn(), getCoachToken: vi.fn(), setCoachToken: vi.fn() }))
vi.mock('../router.js', () => ({ navigate: vi.fn() }))
vi.mock('./CoachAccess.jsx', () => ({ default: () => <p>Login form</p> }))
vi.mock('./ChangePassword.jsx', () => ({ default: () => <p>Change password first</p> }))
let root, container
const room = { id: 7, name: 'Varsity room', school: { id: 2, name: 'Central High' }, dashboard_path: '/coach/rooms/7' }
const me = { username: 'coach', weight_room: room, is_staff: false, must_change_password: false }
beforeEach(() => {
  vi.resetAllMocks()
  getCoachToken.mockReturnValue('token')
  fetchCurrentCoach.mockResolvedValue(me)
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(async () => { await act(async () => root.unmount()); container.remove() })
async function render(props = {}, child = () => <p>Private dashboard</p>) {
  await act(async () => root.render(<CoachRoomGate {...props}>{child}</CoachRoomGate>))
}

it('does not mount private children before the server confirms the session', async () => {
  let resolve
  fetchCurrentCoach.mockReturnValue(new Promise(r => { resolve = r }))
  const child = vi.fn(() => <p>Private dashboard</p>)
  await render({}, child)
  expect(container.textContent).toContain('Checking your account')
  expect(child).not.toHaveBeenCalled()
  await act(async () => resolve(me))
  expect(child).toHaveBeenCalled()
})
it('loads only the assigned direct dashboard and displays school and room', async () => {
  await render({ canonical: true, roomId: '7' })
  expect(container.textContent).toContain('Central High · Varsity room')
  expect(container.textContent).toContain('Private dashboard')
})
it('redirects the generic coach route to the server-provided dashboard', async () => {
  const child = vi.fn()
  await render({ canonical: true }, child)
  expect(navigate).toHaveBeenCalledWith('/coach/rooms/7', { replace: true })
  expect(child).not.toHaveBeenCalled()
})
it('refuses another room URL and offers the assigned dashboard', async () => {
  const child = vi.fn()
  await render({ canonical: true, roomId: '8' }, child)
  expect(container.textContent).toContain('Dashboard access denied')
  expect(child).not.toHaveBeenCalled()
  await act(async () => container.querySelector('button').click())
  expect(navigate).toHaveBeenCalledWith('/coach/rooms/7')
})
it('blocks unassigned accounts including staff and allows checking a new assignment', async () => {
  fetchCurrentCoach.mockResolvedValueOnce({ ...me, is_staff: true, weight_room: null })
  const child = vi.fn(() => <p>Private dashboard</p>)
  await render({}, child)
  expect(container.textContent).toContain('No weight room assigned')
  expect(child).not.toHaveBeenCalled()
  await act(async () => container.querySelector('button').click())
  expect(child).toHaveBeenCalled()
})
it('preserves the forced password change before opening the dashboard', async () => {
  fetchCurrentCoach.mockResolvedValue({ ...me, must_change_password: true })
  const child = vi.fn()
  await render({ canonical: true }, child)
  expect(container.textContent).toContain('Change password first')
  expect(child).not.toHaveBeenCalled()
  expect(navigate).not.toHaveBeenCalled()
})
it('clears an expired session without mounting private data', async () => {
  fetchCurrentCoach.mockRejectedValue({ status: 401 })
  const child = vi.fn()
  await render({}, child)
  expect(container.textContent).toContain('Login form')
  expect(setCoachToken).toHaveBeenCalledWith(null)
  expect(child).not.toHaveBeenCalled()
})
it('keeps private children hidden if session verification fails', async () => {
  fetchCurrentCoach.mockRejectedValue(new Error('Offline'))
  const child = vi.fn()
  await render({}, child)
  expect(container.textContent).toContain('Offline')
  expect(child).not.toHaveBeenCalled()
})
