import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter'
import './BleLab.css'
import BleLab from './BleLab.jsx'

createRoot(document.getElementById('ble-lab-root')).render(
  <StrictMode><BleLab /></StrictMode>,
)
