const ASSETS_BASE = 'http://127.0.0.1:8000'

let currentAudio: HTMLAudioElement | null = null
let uiAudio: HTMLAudioElement | null = null

export function playSound(snd_src: string): void {
  if (currentAudio) {
    currentAudio.pause()
    currentAudio = null
  }

  const url = `${ASSETS_BASE}/assets/sounds/${snd_src}`
  currentAudio = new Audio(url)
  currentAudio.play().catch((err) => {
    console.warn('Failed to play sound:', err)
  })
}

export function playUISound(filename: string): void {
  if (uiAudio) {
    uiAudio.pause()
    uiAudio = null
  }

  const url = `${ASSETS_BASE}/assets/ui-sounds/${filename}`
  uiAudio = new Audio(url)
  uiAudio.play().catch((err) => {
    console.warn('Failed to play UI sound:', err)
  })
}
