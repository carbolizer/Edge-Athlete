/*
 * App.jsx — Root React Component
 * --------------------------------
 * This is the entry point for the React frontend.
 * Every page and component in the app starts here.
 
 */

import Dashboard from './Dashboard.jsx'
import ConnectionTest from './ConnectionTest.jsx'

function App() {
  const path = window.location.pathname

  if (path === '/connection-test') {
    return <ConnectionTest />
  }

  return <Dashboard />
}

export default App

