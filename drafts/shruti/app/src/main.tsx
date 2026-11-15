import React from 'react'
import ReactDOM from 'react-dom/client'
// Inter, bundled (works offline on stage)
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/orbitron/600.css' // NOVA title + HUD
import './index.css'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
