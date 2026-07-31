/*
 * StateNavbar.jsx — the three-position switch at the bottom of the coach app.
 *
 * PLANNING · SESSION · ANALYTICS. One of them is always lit, and a lime pill
 * slides between them when the coach changes state.
 *
 * WHY THE PILL IS MEASURED IN JS. The three labels are different lengths, so
 * the pill has to be a different width in each position, and CSS cannot know
 * how wide "Analytics" renders in the tablet's font. So after every layout we
 * read the selected button's real position and width off the DOM and write them
 * onto the pill; CSS animates the change from there. It re-measures on window
 * resize too, because a tablet gets rotated.
 *
 * WHY SESSION CAN BE OFF. SESSION is the live room, and there is no live room
 * until a training day is running. Rather than send a coach to an empty screen,
 * the button dims and stops responding until a day exists. This is the only
 * state that can be unavailable.
 *
 * This component never unmounts when the state changes — that is the point. It
 * is rendered outside the part of the screen that swaps, so the bar is one
 * continuous object and not three copies of a bar.
 */

import { useLayoutEffect, useRef, useState } from 'react'
import { COACH_STATES } from './coachState.js'
import './StateNavbar.css'

export default function StateNavbar({ current, onSelect, dayRunning }) {
  const buttonRefs = useRef({})
  // Null until the buttons have been measured, so the pill is never rendered in
  // the wrong place. That also means its FIRST appearance carries no animation
  // for free: CSS transitions do not run on an element's initial style, only on
  // a later change. There is no "skip the first one" flag here for that reason.
  const [pill, setPill] = useState(null)

  // useLayoutEffect, not useEffect: this reads the DOM's geometry and writes a
  // style back. Doing it after paint would show one frame of the pill in its
  // old place.
  useLayoutEffect(() => {
    function measure() {
      const button = buttonRefs.current[current]
      if (!button) return
      setPill({ left: button.offsetLeft, width: button.offsetWidth })
    }
    measure()
    // Fonts load asynchronously — Inter arriving after first paint changes every
    // label's width, and the pill would be left sized for the fallback font.
    document.fonts?.ready?.then(measure).catch(() => {})
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [current])

  return (
    <nav className="coach-states" aria-label="Coach workspace state">
      <div className="coach-states-inner">
        {pill && (
          <span
            aria-hidden="true"
            className="coach-states-glider"
            style={{ transform: `translateX(${pill.left}px)`, width: pill.width }}
          />
        )}
        {COACH_STATES.map((state) => {
          // Only SESSION has a precondition; the other two are always reachable.
          //
          // ...unless the coach is STANDING on it. A day can end while SESSION
          // is open, and dimming the button underneath them would put the lime
          // pill and the "you cannot go here" grey on the same button — two
          // opposite messages at once. Where they are is not somewhere they need
          // permission to go, and the body already explains that the room is
          // closed, so the bar just keeps showing where they are.
          const unavailable = state.key === 'session' && !dayRunning && current !== 'session'
          return (
            <button
              key={state.key}
              type="button"
              ref={(node) => { buttonRefs.current[state.key] = node }}
              className={state.key === current ? 'on' : ''}
              aria-current={state.key === current ? 'page' : undefined}
              disabled={unavailable}
              title={unavailable ? 'No training day is running' : undefined}
              onClick={() => onSelect(state.key)}
            >
              {state.label}
            </button>
          )
        })}
      </div>
    </nav>
  )
}
