import fs from 'node:fs'
import path from 'node:path'
import type { SelectedClip } from './selection.js'
import type { TimelineClip, TimelineWindow, Transcript, WordTiming } from './types.js'

const MIN_WINDOW = 1.5
const MAX_WINDOW = 4.0
const TARGET_WINDOW = 3.0
const MAX_CONSECUTIVE_BROLL = 8.0

const STOP_WORDS = new Set(
  `a an the is are was were be been being have has had do does did will would could should may
   might shall can i you he she it we they me him her us them my your his its our their this that
   these those and or but if then so because as of in on at to for with from by about into over
   after before up down out off not no yes just very really also too more most some any all what
   which who whom whose when where why how there here than like get got go going gonna know think
   mean thing things something anything everything one two well right okay yeah oh um uh actually
   basically literally people want said say says see let lets dont doesnt didnt cant wont im youre
   thats theres`.split(/\s+/),
)

export function planTimeline(clips: SelectedClip[], transcript: Transcript, broll: boolean): { clips: TimelineClip[] } {
  const words = transcript.words ?? []
  return {
    clips: clips.map((clip) => {
      const start = clip.start_seconds
      const end = clip.end_seconds
      const duration = Math.round((end - start) * 1000) / 1000
      const sentenceEnds = Array.from(
        new Set(
          transcript.sentences
            .filter((s) => s.end > start && s.start < end && Math.min(s.end, end) - start > 0)
            .map((s) => Math.round((Math.min(s.end, end) - start) * 1000) / 1000),
        ),
      ).sort((a, b) => a - b)
      const windows = buildWindows(duration, sentenceEnds)
      return {
        rank: clip.rank,
        start_seconds: start,
        end_seconds: end,
        duration_seconds: duration,
        windows: assignWindows(windows, start, words, broll, clip.broll_queries),
      }
    }),
  }
}

function buildWindows(duration: number, sentenceEnds: number[]): [number, number][] {
  if (duration <= MAX_WINDOW) return [[0, round3(duration)]]
  const windows: [number, number][] = []
  let cursor = 0
  while (duration - cursor > MAX_WINDOW) {
    const lower = cursor + MIN_WINDOW
    const upper = cursor + MAX_WINDOW
    const candidates = sentenceEnds.filter((b) => b >= lower && b <= upper)
    const boundary = candidates.length
      ? candidates.reduce((best, b) => (Math.abs(b - (cursor + TARGET_WINDOW)) < Math.abs(best - (cursor + TARGET_WINDOW)) ? b : best))
      : upper
    windows.push([round3(cursor), round3(boundary)])
    cursor = boundary
  }
  const remainder = duration - cursor
  if (remainder < MIN_WINDOW && windows.length) {
    const [prevStart] = windows.pop()!
    const merged = duration - prevStart
    if (merged <= MAX_WINDOW) {
      windows.push([prevStart, round3(duration)])
    } else {
      const split = round3(prevStart + Math.min(MAX_WINDOW, merged - MIN_WINDOW))
      windows.push([prevStart, split], [split, round3(duration)])
    }
  } else {
    windows.push([round3(cursor), round3(duration)])
  }
  return windows
}

function assignWindows(
  windows: [number, number][],
  clipStart: number,
  words: WordTiming[],
  broll: boolean,
  queries: string[],
): TimelineWindow[] {
  const qCopy = [...queries]
  let consecutive = 0
  return windows.map(([localStart, localEnd], index) => {
    const duration = round3(localEnd - localStart)
    const text = words
      .filter((w) => w.end > clipStart + localStart && w.start < clipStart + localEnd)
      .map((w) => w.word)
      .join(' ')
    const keywords = extractKeywords(text)
    const isBroll =
      broll &&
      index > 0 &&
      index < windows.length - 1 &&
      index % 3 !== 0 &&
      (qCopy.length > 0 || keywords.length > 0) &&
      consecutive + duration <= MAX_CONSECUTIVE_BROLL

    consecutive = isBroll ? consecutive + duration : 0
    return {
      index,
      type: isBroll ? 'broll' : 'speaker',
      start: round3(localStart),
      end: round3(localEnd),
      duration,
      text,
      query: isBroll ? nextQuery(qCopy, keywords) : null,
    }
  })
}

function nextQuery(queries: string[], keywords: string[]): string {
  if (queries.length) {
    const q = queries.shift()!
    queries.push(q)
    return q
  }
  return keywords.join(' ')
}

function extractKeywords(text: string, limit = 3): string[] {
  const words = text.toLowerCase().match(/[a-z]+(?:'[a-z]+)?/g) ?? []
  const seen: string[] = []
  for (const w of words) {
    if (w.length > 3 && !STOP_WORDS.has(w.replace(/'/g, '')) && !seen.includes(w)) {
      seen.push(w)
    }
  }
  return seen.sort((a, b) => b.length - a.length).slice(0, limit)
}

const FALLBACK_QUERIES = ['city', 'nature', 'people', 'technology', 'abstract']

export async function fillBroll(
  timeline: { clips: TimelineClip[] },
  workDir: string,
  apiKey: string,
  orientation: string,
): Promise<{ clips: TimelineClip[] }> {
  const brollWindows = timeline.clips.flatMap((c) => c.windows).filter((w) => w.type === 'broll')
  if (!brollWindows.length) return timeline
  if (!apiKey) {
    for (const w of brollWindows) {
      w.type = 'speaker'
      w.note = 'no Pexels API key'
    }
    return timeline
  }

  const used = new Set<number>()
  for (const clip of timeline.clips) {
    for (const window of clip.windows) {
      if (window.type !== 'broll') continue
      const video = await findPexelsVideo(apiKey, window.query ?? 'abstract', window.duration, orientation, used)
      if (!video) {
        window.type = 'speaker'
        window.note = 'no stock match'
        continue
      }
      used.add(video.id)
      const dest = path.join(workDir, `broll-${String(clip.rank).padStart(2, '0')}-${String(window.index).padStart(2, '0')}.mp4`)
      const res = await fetch(video.url, { signal: AbortSignal.timeout(120_000) })
      if (!res.ok) {
        window.type = 'speaker'
        window.note = 'broll download failed'
        continue
      }
      const buf = Buffer.from(await res.arrayBuffer())
      fs.writeFileSync(dest, buf)
      window.broll_path = dest
      window.broll_credit = `Video by ${video.author} on Pexels`
      window.broll_page = video.page
    }
  }
  return timeline
}

async function findPexelsVideo(
  apiKey: string,
  query: string,
  duration: number,
  orientation: string,
  used: Set<number>,
): Promise<{ id: number; duration: number; url: string; author: string; page: string } | null> {
  for (const q of [query, ...FALLBACK_QUERIES]) {
    const results = await searchPexels(apiKey, q, orientation)
    for (const minDur of [duration, 3.0]) {
      const match = results.find((v) => !used.has(v.id) && v.duration >= minDur)
      if (match) return match
    }
  }
  return null
}

async function searchPexels(
  apiKey: string,
  query: string,
  orientation: string,
): Promise<{ id: number; duration: number; url: string; author: string; page: string }[]> {
  try {
    const url = new URL('https://api.pexels.com/videos/search')
    url.searchParams.set('query', query)
    url.searchParams.set('orientation', orientation)
    url.searchParams.set('per_page', '15')
    const res = await fetch(url, {
      headers: { Authorization: apiKey },
      signal: AbortSignal.timeout(30_000),
    })
    if (!res.ok) return []
    const json = (await res.json()) as {
      videos?: {
        id: number
        duration?: number
        url?: string
        user?: { name?: string }
        video_files?: { link?: string; width?: number }[]
      }[]
    }
    const results: { id: number; duration: number; url: string; author: string; page: string }[] = []
    for (const item of json.videos ?? []) {
      const files = (item.video_files ?? [])
        .filter((f) => f.link && f.width)
        .sort((a, b) => Math.abs((a.width ?? 0) - 1080) - Math.abs((b.width ?? 0) - 1080))
      if (files[0]?.link) {
        results.push({
          id: item.id,
          duration: Number(item.duration ?? 0),
          url: files[0].link,
          author: item.user?.name ?? 'Pexels',
          page: item.url ?? '',
        })
      }
    }
    return results
  } catch {
    return []
  }
}

function round3(n: number): number {
  return Math.round(n * 1000) / 1000
}
