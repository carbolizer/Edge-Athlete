// React development safeguards
import { StrictMode } from 'react'

// ReactDOM renderer for mounting the app into index.html
import { createRoot } from 'react-dom/client'

// Global frontend styles
import './index.css'

// Root React component
import App from './App.jsx'

// Find the <div id="root"></div> in index.html
// and mount the React application into it.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)