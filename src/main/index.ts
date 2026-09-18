import { app, shell, BrowserWindow, protocol, ipcMain, dialog } from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { PythonManager } from './python-manager'
import fs from 'fs'
import * as path from 'path'

function getLaunchPaths(): {
  gameFolder: string | null
  gamePath: string | null
  emulatorFolder: string | null
  emulatorTarget: string | null
} {
  // Filter out the executable itself, Electron/Chromium flags, and dev-mode script paths
  const positional = process.argv
    .slice(1)
    .filter((arg) => !arg.startsWith('-') && !arg.endsWith('.js') && !arg.includes('app.asar'))
  const emulatorFlag = process.argv.find((arg) => arg.startsWith('--emulator='))
  // Every emulate.sh wrapper invokes us with "<the actual ROM/ISO path>/.."
  // as this argument (so read-metadata's path.join can normalize it down to
  // the enclosing folder without needing a real, separately-passed folder
  // arg) - path.normalize collapses that trailing ".." the same way, and
  // stripping it back off recovers the real game path Pegasus launched with.
  const rawGameArg = positional[0] ?? null
  const gamePath = rawGameArg && rawGameArg.endsWith('/..') ? rawGameArg.slice(0, -3) : null
  return {
    gameFolder: rawGameArg ? path.normalize(rawGameArg) : null,
    gamePath,
    emulatorFolder: positional[1] ?? null,
    emulatorTarget: emulatorFlag ? emulatorFlag.split('=')[1] : null,
  }
}

let pythonManager: PythonManager
let mainWindow: BrowserWindow | null = null

function createWindow(): void {
  const window = new BrowserWindow({
    width: 960,
    height: 720,
    show: false,
    fullscreen: true,
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false
    }
  })
  mainWindow = window

  window.on('ready-to-show', () => {
    window.show()
  })

  window.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    window.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    window.loadFile(join(__dirname, '../renderer/index.html'))
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

  // Signal the emulate.sh wrapper that configuration is done and it should launch
  // the emulator now. Controller Manager itself keeps running in the background
  // (e.g. for the Wii Remote bridge) - the wrapper script kills it (SIGTERM, see
  // the process.on('SIGTERM', ...) handler below) once the game session ends.
  ipcMain.on('signal-launch', (_, gamePath?: string | null) => {
    fs.writeFileSync('/tmp/controller-manager-launch', gamePath ?? '')
    mainWindow?.hide()
  })

  ipcMain.handle('select-game', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openFile'],
      title: 'Select Game (ROM)',
      filters: [
        { name: 'ROMs', extensions: ['nes', 'sfc', 'smc', 'gb', 'gbc', 'gba', 'n64', 'z64', 'v64'] },
        { name: 'All Files', extensions: ['*'] }
      ]
    })
    if (result.canceled || result.filePaths.length === 0) {
      return null
    }
    const gamePath = result.filePaths[0]
    return {
      gamePath,
      gameFolder: path.dirname(gamePath)
    }
  })

  ipcMain.handle('read-metadata', async (_, gameFolder: string) => {
    try {
      const filePath = path.join(gameFolder, 'metadata.pegasus.txt')
      const content = fs.readFileSync(filePath, 'utf-8')
      return { success: true, content, path: filePath }
    } catch (error) {
      return { success: false, error: String(error), path: '' }
    }
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

// The emulate.sh wrapper sends this once the game session ends (the emulator
// process it was running has exited), to stop Controller Manager alongside it.
process.on('SIGTERM', () => {
  pythonManager?.stop()
  app.exit(0)
})
