/*
 * App.jsx — Root React Component
 * --------------------------------
 * This is the entry point for the React frontend.
 * Every page and component in the app starts here.
 
 */

import Dashboard from './Dashboard.jsx'
import ConnectionTest from './ConnectionTest.jsx'
import RackScreen from './RackScreen.jsx'

function App() {
  const path = window.location.pathname

  if (path === '/connection-test') {
    return <ConnectionTest />
  }

  if (path === '/coach') {
    return <Dashboard mode="coach" />
  }

  if (path === '/rack') {
    return <RackScreen />
  }

  if (path === '/dashboard') {
    return <Dashboard mode="wall" />
  }

  return <Dashboard mode="wall" />
}

export default App
