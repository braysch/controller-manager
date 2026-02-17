import { ChildProcess, spawn } from 'child_process'
import { join } from 'path'
import { is } from '@electron-toolkit/utils'

export class PythonManager {
  private process: ChildProcess | null = null

  start(): void {
    const backendDir = is.dev
      ? join(__dirname, '../../backend')
      : join(process.resourcesPath, 'backend')

    const projectRoot = is.dev
      ? join(__dirname, '../..')
      : join(process.resourcesPath)

    // Use venv python if available, otherwise fall back to system python3
    const venvPython = join(projectRoot, '.venv', 'bin', 'python3')
    const pythonBin = require('fs').existsSync(venvPython) ? venvPython : 'python3'

    console.log(`[PythonManager] Starting backend from: ${backendDir} using: ${pythonBin}`)

    this.process = spawn(
      pythonBin,
      ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'],
      {
        cwd: backendDir,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PYTHONUNBUFFERED: '1' }
      }
    )

    this.process.stdout?.on('data', (data: Buffer) => {
      console.log(`[Python] ${data.toString().trim()}`)
    })

    this.process.stderr?.on('data', (data: Buffer) => {
      console.log(`[Python] ${data.toString().trim()}`)
    })

    this.process.on('exit', (code) => {
      console.log(`[PythonManager] Python process exited with code ${code}`)
    })

    this.process.on('error', (err) => {
      console.error(`[PythonManager] Failed to start Python:`, err)
    })
  }

  stop(): void {
    if (this.process) {
      console.log('[PythonManager] Stopping Python backend')
      this.process.kill('SIGTERM')
      this.process = null
    }
  }
}
