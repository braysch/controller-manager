import { contextBridge, ipcRenderer } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'

const api = {
  quitAndLaunch: () => ipcRenderer.send('quit-and-launch'),
  getLaunchPaths: () =>
    ipcRenderer.invoke('get-launch-paths') as Promise<{
      gameFolder: string | null
      emulatorFolder: string | null
      emulatorTarget: string | null
    }>
}

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', {
      ...electronAPI,
      readMetadata: (gameFolder: string) => ipcRenderer.invoke('read-metadata', gameFolder)
    })
    contextBridge.exposeInMainWorld('api', api)
  } catch (error) {
    console.error(error)
  }
} else {
  // @ts-ignore
  window.electron = electronAPI
  // @ts-ignore
  window.api = api
}
