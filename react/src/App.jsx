/*
 * App.jsx — Root React Component
 * --------------------------------
 * This is the entry point for the React frontend.
 * Every page and component in the app starts here.
 
 */

import Dashboard from './Dashboard.jsx'
import ConnectionTest from './ConnectionTest.jsx'
import WallDisplay from './dashboard/WallDisplay.jsx'

function App() {
  const path = window.location.pathname

  // /dashboard is the read-only team wall display (its own big-screen kiosk app,
  // separate from the tablet Dashboard below).
  if (path === '/dashboard') {
    return <WallDisplay />
  }

  if (path === '/connection-test') {
    return <ConnectionTest />
  }

  return <Dashboard />
}

export default App

