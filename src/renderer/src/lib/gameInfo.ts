// Derives a stable, human game name/console system from the selected ROM
// path, so a custom control mapping can be looked up the same way whether
// it's being configured or applied. Pegasus collection metadata (already
// read via window.electron.readMetadata for player-count in ReadyGrid) gives
// the real title when available; the filename (without extension) is the
// fallback so mappings still work for ROMs with no metadata.pegasus.txt.

interface PegasusEntry {
  title: string
  files: string[]
}

function baseName(p: string): string {
  return p.split(/[\\/]/).pop() ?? p
}

function parsePegasusEntries(content: string): PegasusEntry[] {
  const entries: PegasusEntry[] = []
  let current: PegasusEntry | null = null
  for (const rawLine of content.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    const gameMatch = line.match(/^game:\s*(.+)$/)
    if (gameMatch) {
      if (current) entries.push(current)
      current = { title: gameMatch[1].trim(), files: [] }
      continue
    }
    if (!current) continue
    const fileMatch = line.match(/^file:\s*(.+)$/)
    if (fileMatch) current.files.push(fileMatch[1].trim())
  }
  if (current) entries.push(current)
  return entries
}

export function parseGameTitle(content: string, gamePath: string): string | null {
  const target = baseName(gamePath)
  const entries = parsePegasusEntries(content)
  const match = entries.find((e) => e.files.some((f) => baseName(f) === target))
  return match ? match.title : null
}

export function baseNameNoExt(gamePath: string): string {
  return baseName(gamePath).replace(/\.[^.]+$/, '')
}

// Mesen's four supported systems (see MesenConfigWriter.SYSTEM_CONTROLLERS),
// matched by the ROM extensions already offered in the file-picker dialog.
const SYSTEM_BY_EXT: Record<string, string> = {
  nes: 'Nes',
  sfc: 'Snes',
  smc: 'Snes',
  gb: 'Gameboy',
  gbc: 'Gameboy',
  gba: 'Gba'
}

export function systemForGamePath(gamePath: string): string | null {
  const ext = gamePath.split('.').pop()?.toLowerCase()
  if (!ext) return null
  return SYSTEM_BY_EXT[ext] ?? null
}
