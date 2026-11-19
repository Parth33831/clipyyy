import fs from 'node:fs'
import path from 'node:path'
import type { Transcript, WordTiming } from './types.js'

export const FONTS_DIR = path.resolve('server/assets/fonts')

export interface CaptionStyleSpec {
  font: string
  size: number
  case: 'lower' | 'upper' | 'none'
  color: string
  dimAlpha: number
  emphasisColor: string | null
  emphasisScale: number
  outline: number
  shadow: number
  position: number
  maxWords: number
  maxChars: number
}

export const STYLES: Record<string, CaptionStyleSpec> = {
  bold: {
    font: 'Archivo Black',
    size: 0.055,
    case: 'lower',
    color: 'FFFFFF',
    dimAlpha: 0x73,
    emphasisColor: 'FFD400',
    emphasisScale: 1.2,
    outline: 0.0025,
    shadow: 0.0012,
    position: 0.22,
    maxWords: 3,
    maxChars: 18,
  },
  highlight: {
    font: 'Archivo Black',
    size: 0.05,
    case: 'upper',
    color: '2BE36F',
    dimAlpha: 0x00,
    emphasisColor: null,
    emphasisScale: 1.2,
    outline: 0.0025,
    shadow: 0.0012,
    position: 0.22,
    maxWords: 3,
    maxChars: 18,
  },
  minimal: {
    font: 'Archivo Black',
    size: 0.042,
    case: 'none',
    color: 'FFFFFF',
    dimAlpha: 0x00,
    emphasisColor: null,
    emphasisScale: 1.2,
    outline: 0.0025,
    shadow: 0.0012,
    position: 0.12,
    maxWords: 5,
    maxChars: 28,
  },
}

const EMPHASIS_STOP_WORDS = new Set(
  `a an the is are was were be and or but not no in on at to of for by with from as it its this
   that he she we they his her my your our their i you me us him them do does did has have had
   will would could should can so if then just very too also more all about when who how what
   which`.split(/\s+/),
)

export function clipWords(transcript: Transcript, start: number, end: number): WordTiming[] {
  return (transcript.words ?? [])
    .filter((w) => w.end > start && w.start < end)
    .map((w) => ({
      word: w.word,
      start: Math.max(0, Math.round((w.start - start) * 1000) / 1000),
      end: Math.max(0, Math.round((Math.min(w.end, end) - start) * 1000) / 1000),
    }))
}

function chunkWords(words: WordTiming[], style: CaptionStyleSpec): WordTiming[][] {
  const chunks: WordTiming[][] = []
  let current: WordTiming[] = []
  for (const word of words) {
    const text = [...current, word].map((w) => w.word).join(' ')
    if (current.length > 0 && (current.length >= style.maxWords || text.length > style.maxChars)) {
      chunks.push(current)
      current = []
    }
    current.push(word)
    if (/[.!?]$/.test(word.word)) {
      chunks.push(current)
      current = []
    }
  }
  if (current.length > 0) chunks.push(current)
  return chunks
}

function displayWord(word: string, caseMode: CaptionStyleSpec['case']): string {
  const trimmed = word.trim()
  const text = trimmed.endsWith('...') ? trimmed : trimmed.replace(/[,.;:]+$/, '')
  if (caseMode === 'lower') return text.toLowerCase()
  if (caseMode === 'upper') return text.toUpperCase()
  return text
}

function emphasisIndex(chunk: WordTiming[]): number | null {
  const candidates = chunk
    .map((w, i) => ({ i, word: displayWord(w.word, 'lower') }))
    .filter((c) => !EMPHASIS_STOP_WORDS.has(c.word))
  if (!candidates.length) return null
  const best = candidates.reduce((a, b) => (b.word.length > a.word.length ? b : a))
  return best.word.length >= 5 ? best.i : null
}

function assColor(rgb: string): string {
  const clean = rgb.replace(/^#/, '')
  return `&H00${clean.slice(4, 6)}${clean.slice(2, 4)}${clean.slice(0, 2)}&`.toUpperCase()
}

function escapeAss(text: string): string {
  return text.replace(/\\/g, '\\\\').replace(/\{/g, '(').replace(/\}/g, ')')
}

function formatTs(seconds: number): string {
  const centis = Math.max(0, Math.round(seconds * 100))
  const h = Math.floor(centis / 360000)
  const rem1 = centis % 360000
  const m = Math.floor(rem1 / 6000)
  const rem2 = rem1 % 6000
  const s = Math.floor(rem2 / 100)
  const cs = rem2 % 100
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(cs).padStart(2, '0')}`
}

export function writeAss(
  words: WordTiming[],
  outPath: string,
  width: number,
  height: number,
  styleName: string,
): string {
  const style = STYLES[styleName] ?? STYLES.bold
  const fontSize = Math.round(height * style.size)
  const lines: string[] = [
    '[Script Info]',
    'ScriptType: v4.00+',
    `PlayResX: ${width}`,
    `PlayResY: ${height}`,
    'WrapStyle: 0',
    'ScaledBorderAndShadow: yes',
    '',
    '[V4+ Styles]',
    'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
    `Style: Default,${style.font},${fontSize},${assColor(style.color)},&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,${(height * style.outline).toFixed(1)},${(height * style.shadow).toFixed(1)},2,${Math.round(width * 0.08)},${Math.round(width * 0.08)},${Math.round(height * style.position)},1`,
    '',
    '[Events]',
    'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
  ]

  const chunks = chunkWords(words, style)
  for (let n = 0; n < chunks.length; n++) {
    const chunk = chunks[n]
    let chunkEnd = chunk[chunk.length - 1].end + 0.25
    if (n + 1 < chunks.length) {
      chunkEnd = Math.min(chunkEnd, chunks[n + 1][0].start)
    }
    const emph = style.emphasisColor ? emphasisIndex(chunk) : null
    for (let i = 0; i < chunk.length; i++) {
      const word = chunk[i]
      const start = word.start
      const end = i + 1 < chunk.length ? chunk[i + 1].start : chunkEnd
      if (end - start < 0.02) continue
      const parts: string[] = []
      for (let j = 0; j < chunk.length; j++) {
        const other = chunk[j]
        const tags: string[] = []
        if (j === emph && style.emphasisColor) {
          tags.push(`\\c${assColor(style.emphasisColor)}`)
          if (style.emphasisScale !== 1.0) {
            tags.push(`\\fs${Math.round(fontSize * style.emphasisScale)}`)
          }
        } else if (j === i) {
          tags.push(`\\c${assColor(style.color)}`)
        } else {
          tags.push('\\c&HFFFFFF&')
        }
        const alpha = j === i ? 0 : style.dimAlpha
        tags.push(`\\alpha&H${alpha.toString(16).toUpperCase().padStart(2, '0')}&`)
        parts.push(`{${tags.join('')}}${escapeAss(displayWord(other.word, style.case))}`)
      }
      const fade = i === 0 ? '{\\fad(120,0)}' : ''
      lines.push(`Dialogue: 0,${formatTs(start)},${formatTs(end)},Default,,0,0,0,,${fade}${parts.join(' ')}`)
    }
  }

  fs.writeFileSync(outPath, `${lines.join('\n')}\n`, 'utf-8')
  return outPath
}

function filterPath(p: string): string {
  return p.replace(/\\/g, '/').replace(/:/g, '\\:').replace(/'/g, "\\'")
}

export function assFilter(assPath: string): string {
  return `ass='${filterPath(assPath)}':fontsdir='${filterPath(FONTS_DIR)}'`
}
