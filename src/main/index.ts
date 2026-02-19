import { app, shell, BrowserWindow, protocol, ipcMain } from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { PythonManager } from './python-manager'
import fs from 'fs'

function getLaunchPaths(): { gameFolder: string | null; emulatorFolder: string | null } {
  // Filter out the executable itself, Electron/Chromium flags, and dev-mode script paths
  const positional = process.argv
    .slice(1)
    .filter((arg) => !arg.startsWith('-') && !arg.endsWith('.js') && !arg.includes('app.asar'))
  return {
    gameFolder: positional[0] ?? null,
    emulatorFolder: positional[1] ?? null,
  }
}

let pythonManager: PythonManager

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 960,
    height: 720,
    show: false,
    //fullscreen: true,
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow.show()
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

app.whenReady().then(() => {
  protocol.registerFileProtocol('local', (request, callback) => {
    const url = request.url.replace('local://', '')
    try {
      return callback(decodeURIComponent(url))
    } catch (error) {
      console.error(error)
    }
  })

  electronApp.setAppUserModelId('com.controller-manager')

  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  ipcMain.handle('get-launch-paths', () => getLaunchPaths())

  ipcMain.on('quit-and-launch', () => {
    fs.writeFileSync('/tmp/controller-manager-launch', '')
    app.quit()
  })

  pythonManager = new PythonManager()
  pythonManager.start()

  createWindow()

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  pythonManager.stop()
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
