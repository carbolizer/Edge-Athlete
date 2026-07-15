/*
 * App.jsx — Root React Component
 * --------------------------------
 * This is the entry point for the React frontend.
 * Every page and component in the app starts here.
 
 */

import Dashboard from './Dashboard.jsx'
import ConnectionTest from './ConnectionTest.jsx'
import RackScreenDemo from './RackScreenDemo.jsx'
import { AdminSetupPage, AthleteDetailPage, RackDetailPage } from './CoachPages.jsx'

function App() {
  const path = window.location.pathname

  if (path === '/connection-test') {
    return <ConnectionTest />
  }

  if (path === '/rack-demo') {
    return <RackScreenDemo />
  }

  if (path === '/coach') {
    return <Dashboard mode="coach" />
  }

  if (path === '/dashboard') {
    return <Dashboard mode="wall" />
  }

  if (path === '/rack-detail') {
    return <RackDetailPage />
  }

  if (path === '/athlete') {
    return <AthleteDetailPage />
  }

  if (path === '/admin-setup') {
    return <AdminSetupPage />
  }

  return <Dashboard mode="wall" />
}

export default App
