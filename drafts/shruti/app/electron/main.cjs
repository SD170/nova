// Electron main process — opens the Nova window.
const { app, BrowserWindow, ipcMain, session, shell, systemPreferences } = require('electron')
const path = require('path')
const fs = require('fs')
const os = require('os')

const DEV_URL = process.env.ELECTRON_START_URL // set by `npm run dev`
// Dev aids (env vars, nothing on the page):
//   JARVIS_PAGE_JS='…'        run a snippet in the page after load, e.g. feed audio to
//                             window.jarvisAvatar.connectAudio(...) to see the lips move
//   JARVIS_SCREENSHOT=out.png capture the window after load, then quit
const SCREENSHOT = process.env.JARVIS_SCREENSHOT
const PAGE_JS = process.env.JARVIS_PAGE_JS

// ── Nova Desk: files Nova makes (the exam-prep PDF) are saved on THIS laptop under ~/Nova.
// Only ~/Nova is ever written or opened, and only http(s) downloads are allowed.
const NOVA_DIR = path.join(os.homedir(), 'Nova')
const insideNova = (p) => typeof p === 'string' && path.resolve(p).startsWith(NOVA_DIR + path.sep)

ipcMain.handle('nova:save-file', async (_e, { url, filename, headers, folder }) => {
  if (!/^https?:\/\//.test(String(url))) throw new Error('Only http(s) downloads are allowed')
  const dir = path.join(NOVA_DIR, folder === 'exam' ? 'Exam Prep' : 'Saved')
  fs.mkdirSync(dir, { recursive: true })
  const res = await fetch(url, { headers: headers || {} })
  if (!res.ok) throw new Error(`Download failed (HTTP ${res.status})`)
  const data = Buffer.from(await res.arrayBuffer())
  const safe = path.basename(String(filename || 'nova-file')).replace(/[^\w.\- ()]/g, '_')
  const target = path.join(dir, safe)
  fs.writeFileSync(target, data)
  return { path: target, bytes: data.length }
})
ipcMain.handle('nova:reveal', (_e, p) => {
  if (insideNova(p)) shell.showItemInFolder(p)
})
ipcMain.handle('nova:open', async (_e, p) => {
  if (insideNova(p)) await shell.openPath(p)
})

function createWindow() {
  const win = new BrowserWindow({
    // dev aid: JARVIS_SIZE=900x1100 to check framing at other window sizes
    width: Number((process.env.JARVIS_SIZE || '1280x820').split('x')[0]),
    height: Number((process.env.JARVIS_SIZE || '1280x820').split('x')[1]),
    minWidth: 360,
    minHeight: 480,
    backgroundColor: '#05030A',
    title: 'NOVA',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, 'preload.cjs'), // window.novaFiles (save / open / reveal under ~/Nova)
      backgroundThrottling: false, // keep voice + animation running when the window isn't focused
    },
  })

  win.once('ready-to-show', () => win.show())

  // Source links on cards open in the real browser, never inside the app.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) shell.openExternal(url)
    return { action: 'deny' }
  })

  if (DEV_URL) win.loadURL(DEV_URL)
  else
    win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'), {
      // dev aid: JARVIS_QUERY="debug" → ?debug (face rig colors)
      query: process.env.JARVIS_QUERY ? Object.fromEntries(new URLSearchParams(process.env.JARVIS_QUERY)) : undefined,
    })

  if (PAGE_JS) win.webContents.once('did-finish-load', () => win.webContents.executeJavaScript(PAGE_JS).catch(console.error))

  if (SCREENSHOT) {
    win.webContents.on('console-message', (_e, level, message) => {
      console.log(`[renderer:${level}] ${message}`)
    })
    win.webContents.once('did-finish-load', () => {
      setTimeout(async () => {
        const trace = await win.webContents.executeJavaScript('(window.__trace || []).join("\\n")')
        if (trace) console.log(trace)
        // JARVIS_SCREENSHOT_FRAMES=n → n shots 120ms apart (out-1.png, out-2.png, …)
        const frames = Number(process.env.JARVIS_SCREENSHOT_FRAMES || 1)
        for (let i = 1; i <= frames; i++) {
          const img = await win.webContents.capturePage()
          const out = path.resolve(frames > 1 ? SCREENSHOT.replace(/\.png$/, `-${i}.png`) : SCREENSHOT)
          fs.writeFileSync(out, img.toPNG())
          console.log(`screenshot saved: ${out}`)
          if (i < frames) await new Promise((r) => setTimeout(r, Number(process.env.JARVIS_SCREENSHOT_INTERVAL || 120)))
        }
        app.quit()
      }, Number(process.env.JARVIS_SCREENSHOT_DELAY || 3500))
    })
  }
}

async function ensureMicAccess() {
  // macOS asks once (push-to-talk needs the mic); afterwards it's remembered.
  if (process.platform !== 'darwin') return
  if (systemPreferences.getMediaAccessStatus('microphone') === 'granted') return
  try {
    await systemPreferences.askForMediaAccess('microphone')
  } catch {
    /* denied → the page shows the mic but recording fails gracefully */
  }
}

app.whenReady().then(async () => {
  // Only the microphone is allowed (for teammates' voice code); everything else is denied.
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback, details) => {
    const wantsAudio = permission === 'media' && (details.mediaTypes || []).every((t) => t === 'audio')
    callback(wantsAudio)
  })
  session.defaultSession.setPermissionCheckHandler((_wc, permission) => permission === 'media')

  if (!SCREENSHOT) await ensureMicAccess()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
