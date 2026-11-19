import { execFile } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { promisify } from 'node:util'
import type { Sentence, Transcript, WordTiming } from './types.js'

const execFileAsync = promisify(execFile)

export interface FfmpegInfo {
  ffmpeg: string | null
  ffprobe: string | null
  libass: boolean
}

let cachedFfmpeg: FfmpegInfo | null = null

async function findExecutable(name: string): Promise<string | null> {
  try {
    const { stdout } = await execFileAsync('which', [name])
    const p = stdout.trim().split('\n')[0]?.trim()
    return p || null
  } catch {
    return null
  }
}

export async function findFfmpeg(): Promise<FfmpegInfo> {
  if (cachedFfmpeg) return cachedFfmpeg
  const [ffmpeg, ffprobe] = await Promise.all([findExecutable('ffmpeg'), findExecutable('ffprobe')])
  let libass = false
  if (ffmpeg) {
    try {
      const { stdout } = await execFileAsync(ffmpeg, ['-filters'], { maxBuffer: 4 * 1024 * 1024 })
      libass = /\bass\b/.test(stdout)
    } catch {
      libass = false
    }
  }
  cachedFfmpeg = { ffmpeg, ffprobe, libass }
  return cachedFfmpeg
}

export async function findYtdlp(): Promise<string | null> {
  return findExecutable('yt-dlp')
}

export async function runFfmpeg(args: string[]): Promise<void> {
  const { ffmpeg } = await findFfmpeg()
  if (!ffmpeg) throw new Error('ffmpeg not found in runtime')
  try {
    await execFileAsync(ffmpeg, ['-y', '-hide_banner', '-loglevel', 'error', ...args], {
      maxBuffer: 10 * 1024 * 1024,
    })
  } catch (err) {
    const msg = err instanceof Error && 'stderr' in err ? String((err as { stderr?: unknown }).stderr || err.message) : String(err)
    throw new Error(`ffmpeg failed: ${msg.slice(-400)}`)
  }
}

export async function probe(filePath: string): Promise<{ width: number; height: number; duration: number }> {
  const { ffprobe } = await findFfmpeg()
  if (!ffprobe) throw new Error('ffprobe not found in runtime')
  const { stdout } = await execFileAsync(ffprobe, [
    '-v',
    'error',
    '-select_streams',
    'v:0',
    '-show_entries',
    'stream=width,height',
    '-show_entries',
    'format=duration',
    '-of',
    'json',
    filePath,
  ])
  const data = JSON.parse(stdout) as {
    streams?: { width?: number; height?: number }[]
    format?: { duration?: string | number }
  }
  const stream = data.streams?.[0]
  return {
    width: Number(stream?.width ?? 0),
    height: Number(stream?.height ?? 0),
    duration: Number(data.format?.duration ?? 0),
  }
}

export async function hasAudio(filePath: string): Promise<boolean> {
  const { ffprobe } = await findFfmpeg()
  if (!ffprobe) return false
  try {
    const { stdout } = await execFileAsync(ffprobe, [
      '-v',
      'error',
      '-select_streams',
      'a',
      '-show_entries',
      'stream=index',
      '-of',
      'json',
      filePath,
    ])
    const data = JSON.parse(stdout) as { streams?: unknown[] }
    return (data.streams?.length ?? 0) > 0
  } catch {
    return false
  }
}

export function posterPath(videoPath: string): string {
  const parsed = path.parse(videoPath)
  return path.join(parsed.dir, `${parsed.name}.jpg`)
}

export async function makePoster(videoPath: string, atSeconds: number): Promise<void> {
  await runFfmpeg([
    '-ss',
    String(Math.max(0, atSeconds)),
    '-i',
    videoPath,
    '-frames:v',
    '1',
    '-vf',
    'scale=540:-2',
    '-q:v',
    '4',
    posterPath(videoPath),
  ])
}

export async function extractAudioMp3(videoPath: string, outPath: string): Promise<boolean> {
  if (!(await hasAudio(videoPath))) return false
  await runFfmpeg(['-i', videoPath, '-vn', '-ac', '1', '-ar', '16000', '-b:a', '32k', outPath])
  return fs.existsSync(outPath) && fs.statSync(outPath).size > 0
}

export async function sampleFrames(
  videoPath: string,
  duration: number,
  workDir: string,
  limit = 12,
): Promise<{ timestamp: number; path: string }[]> {
  if (duration <= 0) return []
  const count = Math.min(limit, Math.max(3, Math.floor(duration / 8) + 1))
  const folder = path.join(workDir, 'campaign-frames')
  fs.mkdirSync(folder, { recursive: true })
  const samples: { timestamp: number; path: string }[] = []
  for (let i = 0; i < count; i++) {
    const timestamp = Math.min(Math.max(0.5, (duration * (i + 0.5)) / count), Math.max(0.5, duration - 0.2))
    const output = path.join(folder, `frame-${String(i).padStart(2, '0')}.jpg`)
    await runFfmpeg([
      '-ss',
      timestamp.toFixed(3),
      '-i',
      videoPath,
      '-frames:v',
      '1',
      '-vf',
      'scale=512:-2',
      '-q:v',
      '7',
      output,
    ])
    if (fs.existsSync(output) && fs.statSync(output).size > 0) {
      samples.push({ timestamp, path: output })
    }
  }
  return samples
}

/**
 * Fallback acoustic segmentation when local Whisper is unavailable and Gemini audio STT is not configured.
 * Uses ffmpeg silencedetect to locate continuous spoken regions.
 */
export async function detectSpeechSegments(videoPath: string, duration: number): Promise<Transcript> {
  const { ffmpeg } = await findFfmpeg()
  const silences: { start: number; end: number }[] = []
  if (ffmpeg && (await hasAudio(videoPath))) {
    try {
      const { stderr } = await execFileAsync(
        ffmpeg,
        ['-i', videoPath, '-af', 'silencedetect=noise=-32dB:d=0.5', '-f', 'null', '-'],
        { maxBuffer: 10 * 1024 * 1024 },
      )
      let currentStart: number | null = null
      for (const line of stderr.split('\n')) {
        const startMatch = line.match(/silence_start:\s*([0-9.]+)/)
        if (startMatch) currentStart = Number(startMatch[1])
        const endMatch = line.match(/silence_end:\s*([0-9.]+)/)
        if (endMatch) {
          const endVal = Number(endMatch[1])
          silences.push({ start: currentStart ?? Math.max(0, endVal - 0.5), end: endVal })
          currentStart = null
        }
      }
      if (currentStart !== null && currentStart < duration) {
        silences.push({ start: currentStart, end: duration })
      }
    } catch {
      // Ignore silencedetect failure and fall back to uniform segments
    }
  }

  const segments: Sentence[] = []
  let cursor = 0
  for (const s of silences) {
    if (s.start - cursor >= 1.2) {
      segments.push({ start: round3(cursor), end: round3(s.start), text: `Spoken segment (${cursor.toFixed(1)}s–${s.start.toFixed(1)}s)` })
    }
    cursor = Math.max(cursor, s.end)
  }
  if (duration - cursor >= 1.2) {
    segments.push({ start: round3(cursor), end: round3(duration), text: `Spoken segment (${cursor.toFixed(1)}s–${duration.toFixed(1)}s)` })
  }

  // Split overly long segments into ~10s chunks so snapping/selection works smoothly
  const sentences: Sentence[] = []
  for (const seg of segments) {
    let t = seg.start
    while (seg.end - t > 14) {
      const next = round3(t + 10)
      sentences.push({ start: round3(t), end: next, text: `Audio segment ${t.toFixed(1)}s to ${next.toFixed(1)}s.` })
      t = next
    }
    if (seg.end - t >= 1.0) {
      sentences.push({ start: round3(t), end: round3(seg.end), text: `Audio segment ${t.toFixed(1)}s to ${seg.end.toFixed(1)}s.` })
    }
  }

  if (sentences.length === 0 && duration > 1) {
    let t = 0
    while (t < duration) {
      const next = round3(Math.min(duration, t + 10))
      if (next - t >= 1.0) {
        sentences.push({ start: round3(t), end: next, text: `Video segment ${t.toFixed(1)}s to ${next.toFixed(1)}s.` })
      }
      t = next
    }
  }

  return {
    language: 'auto',
    sentences,
    words: interpolateWords(sentences),
    note: 'Acoustic segment fallback (configure Gemini API key for full speech-to-text transcription).',
  }
}

export function interpolateWords(sentences: Sentence[]): WordTiming[] {
  const words: WordTiming[] = []
  for (const s of sentences) {
    const tokens = s.text.trim().split(/\s+/).filter(Boolean)
    if (!tokens.length) continue
    const span = Math.max(0.1, s.end - s.start)
    const step = span / tokens.length
    for (let i = 0; i < tokens.length; i++) {
      words.push({
        word: tokens[i],
        start: round3(s.start + i * step),
        end: round3(s.start + (i + 1) * step),
      })
    }
  }
  return words
}

function round3(n: number): number {
  return Math.round(n * 1000) / 1000
}
