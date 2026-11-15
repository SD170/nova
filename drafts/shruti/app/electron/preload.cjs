// Safe bridge for the Nova Desk: save what Nova makes into ~/Nova, and open/reveal it.
// Everything runs in the main process (see main.cjs); the page never touches the disk.
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('novaFiles', {
  save: (opts) => ipcRenderer.invoke('nova:save-file', opts),
  reveal: (p) => ipcRenderer.invoke('nova:reveal', p),
  open: (p) => ipcRenderer.invoke('nova:open', p),
})
