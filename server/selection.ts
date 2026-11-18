import fs from 'node:fs'
import path from 'node:path'
import { LLMError, type OpenAICompatibleLLM } from './llm.js'
import { sampleFrames } from './media.js'
import type { ClipOptions, Sentence, SourceItem, SourceResult, Transcript } from './types.js'

const MAX_ATTEMPTS = 3
const WINDOW_SECONDS = 18 * 60
const WINDOW_OVERLAP_SECONDS = 45
const MAX_SENTENCE_OVERRUN_SECONDS = 8.0

const SELECTION_SCHEMA: Record<string, unknown> = {
  type: 'object',
  properties: {
    clips: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          rank: { type: 'integer' },
          start_seconds: { type: 'number' },
          end_seconds: { type: 'number' },
          title: { type: 'string' },
          post_title: { type: 'string' },
          caption: { type: 'string' },
          hashtags: { type: 'array', items: { type: 'string' } },
          broll_queries: { type: 'array', items: { type: 'string' } },
          rationale: { type: 'string' },
          hook_score: { type: 'number' },
          value_score: { type: 'number' },
          clarity_score: { type: 'number' },
          overall_score: { type: 'number' },
        },
        required: [
          'rank',
          'start_seconds',
          'end_seconds',
          'title',
          'post_title',
          'caption',
          'hashtags',
          'broll_queries',
          'rationale',
          'hook_score',
          'value_score',
          'clarity_score',
          'overall_score',
        ],
        additionalProperties: false,
      },
    },
  },
  required: ['clips'],
  additionalProperties: false,
}

export interface SelectedClip {
  rank: number
  start_seconds: number
  end_seconds: number
  title: string
  post_title: string
  caption: string
  hashtags: string[]
  broll_queries: string[]
  rationale: string
  score: number
  overall_score?: number
  transcript: string
  campaign_shots?: MontageShot[]
}

export interface MontageShot {
  source_index: number
  start_seconds: number
  end_seconds: number
  reason: string
}

export interface CampaignPlan {
  campaign_name: string | null
  platform: string[]
  content_type: string | null
  subject_or_theme: string | null
  source_requirements: string[]
  reference_urls: string[]
  mood: string[]
  language: string | null
  output_count: number | null
  target_duration_seconds: number | null
  aspect_ratio: string | null
  audio_mode: string | null
  track_or_sound: string | null
  official_platform_sound_required: boolean | null
  on_screen_text_requirements: string[]
  mandatory_content: string[]
  prohibited_content: string[]
  visual_style_and_pacing: string[]
  post_upload_actions: string[]
  performance_eligibility: string[]
  payout_or_submission_caps: string[]
  rights_or_permissions_to_confirm: string[]
  unresolved_questions: string[]
}

function emptyCampaignPlan(): CampaignPlan {
  return {
    campaign_name: null,
    platform: [],
    content_type: null,
    subject_or_theme: null,
    source_requirements: [],
    reference_urls: [],
    mood: [],
    language: null,
    output_count: null,
    target_duration_seconds: null,
    aspect_ratio: null,
    audio_mode: null,
    track_or_sound: null,
    official_platform_sound_required: null,
    on_screen_text_requirements: [],
    mandatory_content: [],
    prohibited_content: [],
    visual_style_and_pacing: [],
    post_upload_actions: [],
    performance_eligibility: [],
    payout_or_submission_caps: [],
    rights_or_permissions_to_confirm: [],
    unresolved_questions: [],
  }
}

function formatCampaignPlan(plan: Partial<CampaignPlan>): string {
  return Object.entries(plan)
    .filter(([, v]) => v !== null && v !== undefined && v !== '' && (!Array.isArray(v) || v.length > 0))
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : String(v)}`)
    .join('\n')
}

function buildPrompt(source: SourceResult, transcript: Transcript, options: ClipOptions & { campaign_plan?: Partial<CampaignPlan> }): [string, string] {
  let instructions = (options.instructions || '').trim()
  const campaignBrief = (options.campaign_brief || '').trim()
  if (options.campaign_mode && campaignBrief) {
    const planText = options.campaign_plan ? formatCampaignPlan(options.campaign_plan) : 'No structured plan available.'
    instructions = [
      instructions,
      `CAMPAIGN REQUIREMENTS (highest priority):\n${campaignBrief}`,
      `STRUCTURED CAMPAIGN PLAN:\n${planText}`,
    ]
      .filter(Boolean)
      .join('\n\n')
  }

  const template = fs.readFileSync(path.resolve('server/prompts/clip_selection.md'), 'utf-8')
  const maxAllowed = Number(options.max_seconds) + MAX_SENTENCE_OVERRUN_SECONDS
  const system = template
    .replace(/\$clip_count/g, String(options.clip_count))
    .replace(/\$min_seconds/g, String(Number(options.min_seconds)))
    .replace(/\$max_seconds/g, String(maxAllowed))
    .replace(/\$instructions/g, instructions ? `\nInstructions from the user:\n${instructions}\n` : '')

  const lines = transcript.sentences.map((s) => `[${s.start.toFixed(1)}-${s.end.toFixed(1)}] ${s.text}`).join('\n')
  const user =
    `Video: ${source.title || 'Untitled'}` +
    (source.uploader ? ` by ${source.uploader}` : '') +
    ` (${Math.round(source.duration_seconds || 0)}s, language: ${transcript.language})\n\n` +
    `Transcript (one sentence per line, [start-end] in seconds):\n${lines}\n\n` +
    `Return exactly ${options.clip_count} strong, non-overlapping clips if the transcript contains enough; return fewer only if it genuinely does not.`

  return [system, user]
}

function splitWindows(sentences: Sentence[]): { sentences: Sentence[] }[] {
  if (!sentences.length) return []
  const first = Math.min(...sentences.map((s) => s.start))
  const last = Math.max(...sentences.map((s) => s.end))
  if (last - first <= WINDOW_SECONDS) return [{ sentences }]
  const windows: { sentences: Sentence[] }[] = []
  let cursor = first
  const step = WINDOW_SECONDS - WINDOW_OVERLAP_SECONDS
  while (cursor < last) {
    const limit = cursor + WINDOW_SECONDS
    const chunk = sentences.filter((s) => s.end > cursor && s.start < limit)
    if (chunk.length) windows.push({ sentences: chunk })
    cursor += step
  }
  return windows
}

export async function selectClips(
  llm: OpenAICompatibleLLM,
  source: SourceResult,
  transcript: Transcript,
  options: ClipOptions,
): Promise<{ model: string; clips: SelectedClip[] }> {
  const sentences = transcript.sentences ?? []
  if (!sentences.length) {
    throw new Error('No speech found in the video, so there is nothing to clip')
  }

  const windows = splitWindows(sentences)
  const candidates: SelectedClip[] = []
  let lastError = 'no clips returned'
  const maxAttempts = llm.provider.local ? 1 : MAX_ATTEMPTS

  for (const window of windows) {
    const windowTranscript: Transcript = { ...transcript, sentences: window.sentences }
    const windowCount = Math.max(2, Math.min(3, Math.floor((options.clip_count + windows.length - 1) / windows.length) + 1))
    const windowOptions: ClipOptions = windows.length > 1 ? { ...options, clip_count: windowCount } : options
    const [system, user] = buildPrompt(source, windowTranscript, windowOptions)

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      let raw: Record<string, unknown>[] = []
      try {
        const res = await llm.completeJson(system, user, SELECTION_SCHEMA, 'clip_selection')
        raw = Array.isArray(res.clips) ? (res.clips as Record<string, unknown>[]) : []
      } catch (err) {
        lastError = err instanceof Error ? err.message : String(err)
        if (err instanceof LLMError && !err.retryable) {
          throw new Error(`Clip selection stopped: ${lastError}`)
        }
        if (attempt === maxAttempts) break
        continue
      }

      const valid = validateClips(raw, windowTranscript, windowOptions)
      if (valid.length > 0) {
        for (const c of valid) {
          c.overall_score = c.score
          candidates.push(c)
        }
        break
      }
      lastError = 'the model did not suggest a clip within the requested length'
    }
  }

  if (!candidates.length) {
    throw new Error(`Clip selection failed: ${lastError}`)
  }

  candidates.sort((a, b) => (b.overall_score ?? b.score ?? 0) - (a.overall_score ?? a.score ?? 0))
  candidates.forEach((c, idx) => {
    c.rank = idx + 1
  })
  const clips = validateClips(candidates as unknown as Record<string, unknown>[], transcript, options)

  return { model: llm.model, clips }
}

export function validateClips(
  rawClips: Record<string, unknown>[],
  transcript: Transcript,
  options: ClipOptions,
): SelectedClip[] {
  const minS = Number(options.min_seconds)
  const maxS = Number(options.max_seconds)
  const sentences = [...transcript.sentences].sort((a, b) => a.start - b.start || a.end - b.end)
  const accepted: SelectedClip[] = []
  const sorted = [...rawClips].sort((a, b) => num(a.rank, 999) - num(b.rank, 999))

  for (const item of sorted) {
    const rawStart = Number(item.start_seconds)
    const rawEnd = Number(item.end_seconds)
    if (!Number.isFinite(rawStart) || !Number.isFinite(rawEnd)) continue
    if (rawStart < sentences[0].start || rawEnd > sentences[sentences.length - 1].end) continue

    const [start, end] = snap(rawStart, rawEnd, sentences, minS, maxS)
    if (end - start < minS - 0.5 || end - start > maxS + MAX_SENTENCE_OVERRUN_SECONDS + 0.5) continue
    if (accepted.some((c) => start < c.end_seconds && c.start_seconds < end)) continue

    const [hashtags, cleanedCaption] = cleanHashtags(item.hashtags, String(item.caption ?? ''))
    accepted.push({
      rank: accepted.length + 1,
      start_seconds: round3(start),
      end_seconds: round3(end),
      title: String(item.title ?? '').trim() || `Clip ${accepted.length + 1}`,
      post_title: String(item.post_title ?? '').trim().slice(0, 100),
      caption: cleanCaptionText(cleanedCaption),
      hashtags,
      broll_queries: Array.isArray(item.broll_queries)
        ? item.broll_queries.map((q) => String(q).trim()).filter(Boolean).slice(0, 8)
        : [],
      rationale: String(item.rationale ?? '').trim(),
      score: num(item.overall_score ?? item.score, 0),
      transcript: excerpt(start, end, sentences),
    })

    if (accepted.length >= options.clip_count) break
  }

  accepted.forEach((c, idx) => {
    c.rank = idx + 1
  })
  return accepted
}

function snap(start: number, end: number, sentences: Sentence[], minS: number, maxS: number): [number, number] {
  if (!sentences.length) return [start, Math.min(Math.max(end, start + minS), start + maxS)]
  let s = sentences.reduce((best, cur) => (Math.abs(cur.start - start) < Math.abs(best.start - start) ? cur : best)).start
  const requestedEnd = end
  let e = sentences.reduce((best, cur) => (Math.abs(cur.end - end) < Math.abs(best.end - end) ? cur : best)).end

  if (e <= s) {
    const later = sentences.filter((item) => item.end > s).map((item) => item.end)
    e = later.length ? later[0] : s + minS
  }
  if (e - s < minS) {
    const longer = sentences.filter((item) => item.end >= s + minS).map((item) => item.end)
    if (longer.length) {
      e = Math.min(...longer)
    } else {
      const earlier = sentences.filter((item) => item.start <= e - minS).map((item) => item.start)
      if (earlier.length) s = Math.max(...earlier)
    }
  }
  if (requestedEnd - s >= maxS - 3) {
    const completion = sentences
      .filter((item) => item.end > s + maxS && item.end <= s + maxS + MAX_SENTENCE_OVERRUN_SECONDS)
      .map((item) => item.end)
    if (completion.length) return [s, Math.min(...completion)]
  }
  if (e - s > maxS) {
    const fitting = sentences.filter((item) => item.end > s && item.end <= s + maxS).map((item) => item.end)
    if (fitting.length && Math.max(...fitting) - s >= minS) {
      e = Math.max(...fitting)
    } else {
      const completion = sentences
        .filter((item) => item.end > s + maxS && item.end <= s + maxS + MAX_SENTENCE_OVERRUN_SECONDS)
        .map((item) => item.end)
      if (completion.length) e = Math.min(...completion)
    }
  }
  return [s, e]
}

function excerpt(start: number, end: number, sentences: Sentence[]): string {
  return sentences
    .filter((s) => s.start >= start - 0.01 && s.end <= end + 0.01)
    .map((s) => s.text)
    .join(' ')
}

function cleanCaptionText(caption: string): string {
  let value = caption.trim()
  const marker = /\s*\(\d+\s*(?:chars?|characters?|s|secs?|seconds?)\)\s*$/i
  while (marker.test(value)) {
    value = value.replace(marker, '').trim()
  }
  return value.replace(/\s{2,}/g, ' ')
}

function cleanHashtags(tags: unknown, caption: string): [string[], string] {
  const trailing = /(?:\s*#[\w\u00C0-\uFFFF]+)+\s*$/
  const match = caption.match(trailing)
  const extra = match ? match[0].trim().split(/\s+/) : []
  const cleanedCaption = match ? caption.slice(0, match.index).trim() : caption

  const rawList = [...(Array.isArray(tags) ? tags : []), ...extra]
  const result: string[] = []
  const seen = new Set<string>()
  for (const tag of rawList) {
    const cleaned = '#' + String(tag).replace(/[^\w\u00C0-\uFFFF]/g, '')
    if (cleaned.length > 1 && !seen.has(cleaned.toLowerCase())) {
      seen.add(cleaned.toLowerCase())
      result.push(cleaned)
    }
  }
  return [result.slice(0, 10), cleanedCaption]
}

function num(v: unknown, fallback: number): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

function round3(n: number): number {
  return Math.round(n * 1000) / 1000
}

// ── Campaign parsing, vision sampling, and montage planning ──────────────────

const PLAN_SCHEMA: Record<string, unknown> = {
  type: 'object',
  properties: {
    campaign_name: { type: ['string', 'null'] },
    platform: { type: 'array', items: { type: 'string' } },
    content_type: { type: ['string', 'null'] },
    subject_or_theme: { type: ['string', 'null'] },
    source_requirements: { type: 'array', items: { type: 'string' } },
    reference_urls: { type: 'array', items: { type: 'string' } },
    mood: { type: 'array', items: { type: 'string' } },
    language: { type: ['string', 'null'] },
    output_count: { type: ['integer', 'null'] },
    target_duration_seconds: { type: ['number', 'null'] },
    aspect_ratio: { type: ['string', 'null'] },
    audio_mode: { type: ['string', 'null'] },
    track_or_sound: { type: ['string', 'null'] },
    official_platform_sound_required: { type: ['boolean', 'null'] },
    on_screen_text_requirements: { type: 'array', items: { type: 'string' } },
    mandatory_content: { type: 'array', items: { type: 'string' } },
    prohibited_content: { type: 'array', items: { type: 'string' } },
    visual_style_and_pacing: { type: 'array', items: { type: 'string' } },
    post_upload_actions: { type: 'array', items: { type: 'string' } },
    performance_eligibility: { type: 'array', items: { type: 'string' } },
    payout_or_submission_caps: { type: 'array', items: { type: 'string' } },
    rights_or_permissions_to_confirm: { type: 'array', items: { type: 'string' } },
    unresolved_questions: { type: 'array', items: { type: 'string' } },
  },
  required: Object.keys(emptyCampaignPlan()),
  additionalProperties: false,
}

export async function parseCampaignBrief(llm: OpenAICompatibleLLM, brief: string): Promise<CampaignPlan> {
  const text = brief.trim()
  if (!text) return emptyCampaignPlan()
  const system =
    'You are a universal short-form campaign strategist. Read the supplied campaign brief and extract its actual requirements into the schema. Do not invent missing values: use null for unknown scalar values and empty arrays when no items are specified. Return JSON only.'
  const res = await llm.completeJson(
    system,
    `Extract the requirements from this campaign brief. Do not add assumptions.\n\n${text}`,
    PLAN_SCHEMA,
    'campaign_requirements',
  )
  return { ...emptyCampaignPlan(), ...(res as Partial<CampaignPlan>) }
}

const FRAME_SCHEMA: Record<string, unknown> = {
  type: 'object',
  properties: {
    frames: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          timestamp: { type: 'number' },
          description: { type: 'string' },
          mood: { type: 'string' },
          subjects: { type: 'string' },
        },
        required: ['timestamp', 'description', 'mood', 'subjects'],
        additionalProperties: false,
      },
    },
  },
  required: ['frames'],
  additionalProperties: false,
}

export async function analyzeCampaignVideo(
  source: SourceItem,
  workDir: string,
  llm: OpenAICompatibleLLM,
  campaignBrief: string,
): Promise<{ frames: { timestamp: number; description: string; mood: string; subjects: string }[] }> {
  const frames = await sampleFrames(source.video_path, source.duration_seconds, workDir)
  if (!frames.length) return { frames: [] }
  const system =
    'You are a professional short-form video editor analysing source footage for a campaign. Describe only what is visibly present. Return JSON only.'
  const user = `Campaign brief:\n${campaignBrief}\n\nAnalyse these timestamped frames. Return one observation per frame, preserving each timestamp.`
  const res = await llm.completeJsonWithImages(system, user, FRAME_SCHEMA, 'campaign_visual_analysis', frames)
  const list = Array.isArray(res.frames) ? (res.frames as Record<string, unknown>[]) : []
  return {
    frames: list
      .filter((f) => Number.isFinite(Number(f.timestamp)))
      .map((f) => ({
        timestamp: Number(f.timestamp),
        description: String(f.description ?? '').slice(0, 500),
        mood: String(f.mood ?? '').slice(0, 100),
        subjects: String(f.subjects ?? '').slice(0, 200),
      })),
  }
}

const MONTAGE_SCHEMA: Record<string, unknown> = {
  type: 'object',
  properties: {
    edits: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          shots: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                source_index: { type: 'integer' },
                start_seconds: { type: 'number' },
                end_seconds: { type: 'number' },
                reason: { type: 'string' },
              },
              required: ['source_index', 'start_seconds', 'end_seconds', 'reason'],
              additionalProperties: false,
            },
          },
        },
        required: ['title', 'shots'],
        additionalProperties: false,
      },
    },
  },
  required: ['edits'],
  additionalProperties: false,
}

export async function buildMontagePlan(
  llm: OpenAICompatibleLLM,
  brief: string,
  campaignPlan: CampaignPlan,
  sources: SourceItem[],
  analyses: { frames: { timestamp: number; description: string; mood: string; subjects: string }[] }[],
  outputCount: number,
  targetSeconds: number,
  additionalInstructions = '',
): Promise<{ rank: number; title: string; shots: MontageShot[] }[]> {
  const candidates: Record<string, unknown>[] = []
  sources.forEach((src, sourceIndex) => {
    for (const frame of analyses[sourceIndex]?.frames ?? []) {
      candidates.push({
        source_index: sourceIndex,
        source_title: src.title,
        source_duration: src.duration_seconds,
        ...frame,
      })
    }
  })
  if (candidates.length < 3) {
    throw new Error('Not enough visual scenes could be analysed. Use a vision-capable model and clear source videos.')
  }
  const system =
    'You are an expert campaign film editor. Build coherent, emotionally paced short-form video montages from the supplied timestamped visual observations. Each shot should be 2 to 5 seconds. Return JSON only.'
  const user =
    `Campaign brief:\n${brief}\n\nExtracted requirements:\n${formatCampaignPlan(campaignPlan)}\n\n` +
    `Additional creator instructions:\n${additionalInstructions || 'None'}\n\n` +
    `Create ${outputCount} distinct edits, each approximately ${targetSeconds.toFixed(1)} seconds.\n\n` +
    `Visual observations:\n${JSON.stringify(candidates)}`

  const res = await llm.completeJson(system, user, MONTAGE_SCHEMA, 'campaign_montage_plan')
  const edits = Array.isArray(res.edits) ? (res.edits as { title?: string; shots?: Record<string, unknown>[] }[]) : []
  const validEdits: { rank: number; title: string; shots: MontageShot[] }[] = []

  edits.slice(0, outputCount).forEach((edit, idx) => {
    const shots: MontageShot[] = []
    for (const s of edit.shots ?? []) {
      const sourceIndex = Math.trunc(Number(s.source_index))
      if (sourceIndex < 0 || sourceIndex >= sources.length) continue
      const dur = sources[sourceIndex].duration_seconds
      const start = Math.max(0, Math.min(Number(s.start_seconds), dur))
      let end = Math.max(start, Math.min(Number(s.end_seconds), dur))
      if (end - start > 5.0) end = start + 5.0
      if (end - start < 1.5) continue
      shots.push({
        source_index: sourceIndex,
        start_seconds: round3(start),
        end_seconds: round3(end),
        reason: String(s.reason ?? '').slice(0, 300),
      })
    }
    if (shots.length >= 2) {
      validEdits.push({
        rank: idx + 1,
        title: String(edit.title ?? '').trim() || `Campaign edit ${idx + 1}`,
        shots,
      })
    }
  })

  if (!validEdits.length) {
    throw new Error('Could not build a valid montage plan from the visual observations.')
  }
  return validEdits
}
