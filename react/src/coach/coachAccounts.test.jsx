// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import CoachAccess from './CoachAccess.jsx'
import RosterWorkspace from './RosterWorkspace.jsx'
import FirstRunSetup from './FirstRunSetup.jsx'
import ChangePassword from './ChangePassword.jsx'
import CoachManagement from './CoachManagement.jsx'
import {
  changePassword, coachFetch, coachLogin, createCoach, listCoaches,
  resetCoachPassword, setCoachToken, updateCoach,
} from './api.js'

vi.mock('./api.js', () => ({
  coachFetch: vi.fn(),
  coachLogin: vi.fn(),
  setCoachToken: vi.fn(),
  changePassword: vi.fn(),
  listCoaches: vi.fn(),
  createCoach: vi.fn(),
  updateCoach: vi.fn(),
  resetCoachPassword: vi.fn(),
}))
vi.mock('../router.js', () => ({ navigate: vi.fn() }))

let container, root
beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.restoreAllMocks()
})
async function render(element) { await act(async () => root.render(element)) }
async function fill(input, value) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function submit() {
  await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
}
async function click(text) {
  const button = [...container.querySelectorAll('button')].find(b => b.textContent === text)
  expect(button, `button "${text}"`).toBeTruthy()
  await act(async () => button.click())
}

it('requires the one-time setup code and matching passwords before creating the first admin', async () => {
  coachFetch.mockResolvedValueOnce({ setup_required: true, setup_code_pending: true }).mockResolvedValueOnce({ access: 'setup-token' })
  const loggedIn = vi.fn()
  await render(<CoachAccess onLoggedIn={loggedIn} />)
  const inputs = container.querySelectorAll('input')
  await fill(inputs[0], 'firstcoach')
  await fill(inputs[1], 'unique-password')
  await fill(inputs[2], 'different')
  await fill(inputs[3], 'ABC234')
  await submit()
  expect(container.querySelector('[role=alert]').textContent).toContain('do not match')
  expect(coachFetch).toHaveBeenCalledTimes(1)
  await fill(inputs[2], 'unique-password')
  await submit()
  expect(coachFetch).toHaveBeenLastCalledWith('/api/auth/setup/', {
    method: 'POST',
    body: { username: 'firstcoach', password: 'unique-password', setup_code: 'ABC234' },
  })
  expect(setCoachToken).toHaveBeenCalledWith('setup-token')
  expect(loggedIn).toHaveBeenCalledWith('setup-token')
})

it('tells the operator to issue a setup code when none is pending yet', async () => {
  coachFetch.mockResolvedValueOnce({ setup_required: true, setup_code_pending: false }).mockResolvedValueOnce({ setup_required: true, setup_code_pending: true })
  await render(<CoachAccess onLoggedIn={vi.fn()} />)
  expect(container.textContent).toContain('manage.py setup_code')
  await click('I\u2019ve run it — check again')
  expect(container.querySelector('[role=note]')).toBeNull()
})

it('shows login errors and accepts valid credentials', async () => {
  coachFetch.mockResolvedValue({ setup_required: false })
  coachLogin.mockRejectedValueOnce(new Error('The username or password was not accepted.')).mockResolvedValueOnce('login-token')
  const loggedIn = vi.fn()
  await render(<CoachAccess onLoggedIn={loggedIn} />)
  const inputs = container.querySelectorAll('input')
  await fill(inputs[0], 'coach')
  await fill(inputs[1], 'password')
  await submit()
  expect(container.querySelector('[role=alert]').textContent).toContain('not accepted')
  expect(loggedIn).not.toHaveBeenCalled()
  await submit()
  expect(loggedIn).toHaveBeenCalledWith('login-token')
})

it('recovers when another browser completes setup first', async () => {
  coachFetch.mockResolvedValueOnce({ setup_required: true, setup_code_pending: true })
    .mockRejectedValueOnce(Object.assign(new Error('Setup is complete.'), { status: 409 }))
  await render(<CoachAccess onLoggedIn={vi.fn()} />)
  await submit()
  expect(container.textContent).toContain('Coach login')
  expect(container.querySelectorAll('input')).toHaveLength(2)
})

it('changes a temporary password and reports success', async () => {
  changePassword.mockResolvedValue(null)
  const changed = vi.fn()
  await render(<ChangePassword accessToken="token" forced onChanged={changed} onLogout={vi.fn()} />)
  const inputs = container.querySelectorAll('input')
  await fill(inputs[0], 'temp-pass')
  await fill(inputs[1], 'new-pass')
  await fill(inputs[2], 'mismatch')
  await submit()
  expect(container.querySelector('[role=alert]').textContent).toContain('do not match')
  expect(changePassword).not.toHaveBeenCalled()
  await fill(inputs[2], 'new-pass')
  await submit()
  expect(changePassword).toHaveBeenCalledWith('token', 'temp-pass', 'new-pass')
  expect(changed).toHaveBeenCalled()
})

it('creates a coach and shows the temporary password exactly once', async () => {
  listCoaches.mockResolvedValue([])
  createCoach.mockResolvedValue({ id: 2, username: 'assistant', is_staff: false, is_active: true, must_change_password: true, temporary_password: 'TEMP-abc123' })
  await render(<CoachManagement accessToken="token" currentUsername="head" onLogout={vi.fn()} onChangePassword={vi.fn()} />)
  const inputs = container.querySelectorAll('input')
  await fill(inputs[0], 'assistant')
  await submit()
  expect(createCoach).toHaveBeenCalledWith('token', 'assistant', '')
  expect(container.textContent).toContain('TEMP-abc123')
  await click('Dismiss')
  expect(container.textContent).not.toContain('TEMP-abc123')
})

it('does not let an administrator change their own access or reset their own password from the list', async () => {
  listCoaches.mockResolvedValue([{ id: 1, username: 'head', is_staff: true, is_active: true, must_change_password: false }])
  await render(<CoachManagement accessToken="token" currentUsername="head" onLogout={vi.fn()} onChangePassword={vi.fn()} />)
  expect(container.textContent).toContain('This is you')
  expect([...container.querySelectorAll('button')].some(b => b.textContent === 'Deactivate')).toBe(false)
  expect([...container.querySelectorAll('button')].some(b => b.textContent === 'Make coach')).toBe(false)
})

const assistant = (overrides = {}) => (
  { id: 2, username: 'assistant', is_staff: false, is_active: true, must_change_password: false, ...overrides })

it('deactivates and reactivates another coach', async () => {
  listCoaches
    .mockResolvedValueOnce([assistant()])
    .mockResolvedValueOnce([assistant({ is_active: false })])
    .mockResolvedValueOnce([assistant()])
  updateCoach.mockResolvedValue({})
  await render(<CoachManagement accessToken="token" currentUsername="head" onLogout={vi.fn()} onChangePassword={vi.fn()} />)
  await click('Deactivate')
  expect(updateCoach).toHaveBeenCalledWith('token', 2, { is_active: false })
  await click('Reactivate')
  expect(updateCoach).toHaveBeenLastCalledWith('token', 2, { is_active: true })
})

it('promotes a coach to administrator and shows the admin badge', async () => {
  listCoaches
    .mockResolvedValueOnce([assistant()])
    .mockResolvedValueOnce([assistant({ is_staff: true })])
  updateCoach.mockResolvedValue({})
  await render(<CoachManagement accessToken="token" currentUsername="head" onLogout={vi.fn()} onChangePassword={vi.fn()} />)
  await click('Make administrator')
  expect(updateCoach).toHaveBeenCalledWith('token', 2, { is_staff: true })
  expect(container.textContent).toContain('administrator')
  expect([...container.querySelectorAll('button')].some(b => b.textContent === 'Make coach')).toBe(true)
})

it('resets another coach password after confirmation', async () => {
  listCoaches.mockResolvedValue([{ id: 2, username: 'assistant', is_staff: false, is_active: true, must_change_password: false }])
  resetCoachPassword.mockResolvedValue({ id: 2, username: 'assistant', temporary_password: 'RESET-xyz' })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  await render(<CoachManagement accessToken="token" currentUsername="head" onLogout={vi.fn()} onChangePassword={vi.fn()} />)
  await click('Reset password')
  expect(resetCoachPassword).toHaveBeenCalledWith('token', 2)
  expect(container.textContent).toContain('RESET-xyz')
})

it('creates, edits without clearing a tag, and removes a member with history-retention confirmation', async () => {
  let roster = []
  coachFetch.mockImplementation(async (path, options) => {
    if (!options.method) return roster
    if (options.method === 'POST') roster = [{ id: 1, name: options.body.name, is_active: true }]
    if (options.method === 'PATCH') roster = [{ ...roster[0], name: options.body.name }]
    if (options.method === 'DELETE') roster = [{ ...roster[0], is_active: false }]
    return options.method === 'DELETE' ? null : roster[0]
  })
  const onChanged = vi.fn()
  await render(<RosterWorkspace accessToken="token" onLogout={vi.fn()} onChanged={onChanged} />)
  await fill(container.querySelector('input'), 'Jordan')
  await submit()
  expect(container.querySelector('li').textContent).toContain('Jordan')
  await click('Edit')
  await fill(container.querySelector('input'), 'Jordan Smith')
  await submit()
  expect(coachFetch).toHaveBeenCalledWith('/api/athletes/1/', { token: 'token', method: 'PATCH', body: { name: 'Jordan Smith' } })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  await click('Remove')
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Saved workouts and reports will be retained'))
  expect(container.querySelector('li').textContent).toContain('No team members yet')
  expect(onChanged).toHaveBeenCalledTimes(3)
})

it('keeps a member visible when the server refuses removal during a session', async () => {
  coachFetch.mockResolvedValueOnce([{ id: 1, name: 'Jordan', is_active: true }]).mockRejectedValueOnce(new Error('End the active training session before removing this athlete.'))
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  await render(<RosterWorkspace accessToken="token" onLogout={vi.fn()} onChanged={vi.fn()} />)
  await click('Remove')
  expect(container.querySelector('[role=alert]').textContent).toContain('End the active training session')
  expect(container.querySelector('li').textContent).toContain('Jordan')
})

it('does not expose the app before first-run status is known and offers a retry on failure', async () => {
  coachFetch.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ setup_required: false })
  await render(<FirstRunSetup><p>Application ready</p></FirstRunSetup>)
  expect(container.textContent).not.toContain('Application ready')
  await click('Retry connection')
  expect(container.textContent).toContain('Application ready')
})

it('allows a previously configured rack to reopen its offline shell', async () => {
  localStorage.setItem('edge_setup_complete', 'true')
  coachFetch.mockRejectedValue(new Error('offline'))
  await render(<FirstRunSetup><p>Offline shell</p></FirstRunSetup>)
  expect(container.textContent).toContain('Offline shell')
})

it('lets an administrator revoke and restore room access', async () => {
  const weightRoom = { id: 7, name: 'Varsity', school: { name: 'Central' } }
  listCoaches.mockResolvedValue([{ id: 2, username: 'assistant', is_active: true, weight_room: weightRoom }])
  updateCoach.mockResolvedValue({})
  await render(<CoachManagement accessToken="token" currentUsername="admin" weightRoom={weightRoom} />)
  expect(container.textContent).toContain('Central · Varsity')
  listCoaches.mockResolvedValue([{ id: 2, username: 'assistant', is_active: true, weight_room: null }])
  await click('Remove room access')
  expect(updateCoach).toHaveBeenLastCalledWith('token', 2, { weight_room_id: null })
  expect(container.textContent).toContain('No weight room assigned')
  await click('Assign to this room')
  expect(updateCoach).toHaveBeenLastCalledWith('token', 2, { weight_room_id: 7 })
})
