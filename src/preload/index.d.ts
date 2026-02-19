import { ElectronAPI } from '@electron-toolkit/preload'

declare global {
  interface Window {
    electron: ElectronAPI
    api: {
      quitAndLaunch: () => void
      getLaunchPaths: () => Promise<{ gameFolder: string | null; emulatorFolder: string | null }>
    }
  }
}
