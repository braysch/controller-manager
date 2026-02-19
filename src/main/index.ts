import { app, shell, BrowserWindow, protocol, ipcMain } from 'electron'
import { join } from 'path'
import { writeFileSync, unlinkSync } from 'fs'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { PythonManager } from './python-manager'
import { readFile } from 'fs/promises'

const LAUNCH_MARKER = '/tmp/controller-manager-launch'

let pythonManager: PythonManager

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 960,
    height: 900,
    show: false,
    fullscreen: true,
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
  electronApp.setAppUserModelId('com.controller-manager')

  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  // Register custom protocol to serve local files
  protocol.handle('local', async (request) => {
    const filePath = request.url.slice('local://'.length)
    try {
      const data = await readFile(filePath)
      // Determine MIME type based on file extension
      const ext = filePath.split('.').pop()?.toLowerCase()
      const mimeTypes: Record<string, string> = {
        png: 'image/png',
        jpg: 'image/jpeg',
        jpeg: 'image/jpeg',
        gif: 'image/gif',
        svg: 'image/svg+xml',
        webp: 'image/webp'
      }
      const mimeType = mimeTypes[ext || ''] || 'application/octet-stream'
      
      return new Response(data, {
        headers: { 'Content-Type': mimeType }
      })
    } catch (error) {
      console.error('Failed to load file:', filePath, error)
      return new Response('File not found', { status: 404 })
    }
  })

  // Clean up any stale marker from a previous run
  try { unlinkSync(LAUNCH_MARKER) } catch { /* didn't exist */ }

  ipcMain.on('quit-and-launch', () => {
    writeFileSync(LAUNCH_MARKER, '')
    pythonManager.stop()
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
