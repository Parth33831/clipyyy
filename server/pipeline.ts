import { execFile } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { promisify } from 'node:util'
import { assFilter, clipWords, writeAss } from './captions.js'
import { getLlm, transcribeAudioWithGemini } from './llm.js'
import {
  detectSpeechSegments,
  extractAudioMp3,
  findYtdlp,
  hasAudio,
  makePoster,
  probe,
  runFfmpeg,
} from './media.js'
import {
  analyzeCampaignVideo,
  buildMontagePlan,
  parseCampaignBrief,
  selectClips,
  type CampaignPlan,
  type MontageShot,
  type SelectedClip,
} from './selection.js'
import {
  claimNextRun,
  deleteRun as dbDeleteRun,
  getRun,
  getSetting,
  listClips,
  listPosts,
  listStages,
  replaceClips,
  runDir,
  setStage,
  updateRun,
} from './store.js'
import { fillBroll, planTimeline } from './timeline.js'
import type {
  AspectRatio,
  ClipOptions,
  RunRecord,
  SourceItem,
  SourceResult,
  TimelineClip,
  Transcript,
} from './types.js'

const execFileAsync = promisify(execFile)

const SIZES: Record<AspectRatio, [number, number]> = {
  '9:16': [1080, 1920],
  '4:5': [1080, 1350],
  '1:1': [1080, 1080],
}

export const STAGES: { name: string; label: string; fn: (ctx: PipelineContext) => Promise<Record<string, unknown>> }[] = [
  { name: 'download', label: 'Download', fn: stageDownload },
  { name: 'transcribe', label: 'Transcribe', fn: stageTranscribe },
  { name: 'select', label: 'Find clips', fn: stageSelect },
  { name: 'plan', label: 'Plan edits', fn: stagePlan },
  { name: 'broll', label: 'B-roll', fn: stageBroll },
  { name: 'reframe', label: 'Reframe', fn: stageReframe },
  { name: 'render', label: 'Render', fn: stageRender },
]

export const STAGE_NAMES = STAGES.map((s) => s.name)

interface PipelineContext {
  runId: string
  source: string
  options: ClipOptions
  workDir: string
  outDir: string
  state: Record<string, unknown>
}

function isUrl(src: string): boolean {
  return /^https?:\/\//i.test(src)
}

function slugify(text: string, limit = 40): string {
  const slug = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return slug.slice(0, limit).replace(/-+$/, '') || 'clip'
}

async function fetchSingleSource(source: string, workDir: string): Promise<SourceItem> {
  fs.mkdirSync(workDir, { recursive: true })
  const videoPath = path.join(workDir, 'source.mp4')
  let title = source
  let uploader = ''

  if (isUrl(source)) {
    const ytdlp = await findYtdlp()
    if (ytdlp) {
      const { stdout } = await execFileAsync(ytdlp, ['--no-playlist', '--dump-json', '--skip-download', source])
      const info = JSON.parse(stdout.split('\n')[0]) as { title?: string; uploader?: string; is_live?: boolean }
      if (info.is_live) throw new Error('Live streams are not supported')
      title = info.title || source
      uploader = info.uploader || ''
      if (!fs.existsSync(videoPath)) {
        await execFileAsync(ytdlp, [
          '--no-playlist',
          '--format',
          'bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b',
          '--merge-output-format',
          'mp4',
          '--output',
          videoPath,
          source,
        ])
      }
    } else {
      // Try direct media download when URL points to a video file/stream
      const res = await fetch(source, { signal: AbortSignal.timeout(120_000) })
      if (!res.ok) {
        throw new Error(`Could not download URL (${res.status} ${res.statusText}). Upload a video file or direct .mp4 URL.`)
      }
      const ct = res.headers.get('content-type') || ''
      if (!ct.startsWith('video/') && !ct.includes('octet-stream') && !/\.(mp4|mov|webm|mkv)(\?|$)/i.test(source)) {
        throw new Error(
          'Webpage links (such as YouTube) require yt-dlp, which is not available in this Node.js container. Upload a video file or paste a direct .mp4 URL.',
        )
      }
      const buf = Buffer.from(await res.arrayBuffer())
      fs.writeFileSync(videoPath, buf)
      const urlPath = new URL(source).pathname
      title = path.basename(urlPath, path.extname(urlPath)) || source
    }
  } else {
    if (!fs.existsSync(source)) {
      throw new Error(`Source file not found: ${source}`)
    }
    if (!fs.existsSync(videoPath)) {
      fs.copyFileSync(source, videoPath)
    }
    const base = path.basename(source, path.extname(source))
    title = base.replace(/^[0-9a-f]{12}-/, '')
  }

  const info = await probe(videoPath)
  if (!info.width || !info.duration) {
    throw new Error('Source has no valid video stream')
  }

  return {
    source,
    title,
    uploader,
    duration_seconds: info.duration,
    width: info.width,
    height: info.height,
    video_path: videoPath,
  }
}

async function stageDownload(ctx: PipelineContext): Promise<Record<string, unknown>> {
  if (ctx.options.campaign_mode) {
    const sources: string[] = ctx.source.trim().startsWith('[') ? JSON.parse(ctx.source) : [ctx.source]
    const items: SourceItem[] = []
    for (let i = 0; i < sources.length; i++) {
      const itemDir = path.join(ctx.workDir, `source-${String(i + 1).padStart(2, '0')}`)
      const item = await fetchSingleSource(sources[i], itemDir)
      item.source_index = i
      items.push(item)
    }
    const result: SourceResult = {
      source: ctx.source,
      title: items.length === 1 ? items[0].title : `Campaign montage · ${items.length} sources`,
      sources: items,
      video_path: items[0].video_path,
      duration_seconds: items.reduce((sum, item) => sum + item.duration_seconds, 0),
      width: items[0].width,
      height: items[0].height,
    }
    updateRun(ctx.runId, { title: result.title })
    return result as unknown as Record<string, unknown>
  }

  const result = await fetchSingleSource(ctx.source, ctx.workDir)
  updateRun(ctx.runId, { title: result.title })
  return result as unknown as Record<string, unknown>
}

async function stageTranscribe(ctx: PipelineContext): Promise<Record<string, unknown>> {
  if (ctx.options.campaign_mode) {
    return { language: 'campaign', sentences: [], words: [] }
  }
  const source = ctx.state.download as SourceResult
  const mp3Path = path.join(ctx.workDir, 'audio.mp3')
  const extracted = await extractAudioMp3(source.video_path, mp3Path)
  if (extracted) {
    const geminiTranscript = await transcribeAudioWithGemini(mp3Path, source.duration_seconds, ctx.options.language)
    if (geminiTranscript) {
      return geminiTranscript as unknown as Record<string, unknown>
    }
  }
  const fallback = await detectSpeechSegments(source.video_path, source.duration_seconds)
  return fallback as unknown as Record<string, unknown>
}

async function stageSelect(ctx: PipelineContext): Promise<Record<string, unknown>> {
  const options = { ...ctx.options }
  const defaults = getSetting('default_instructions').trim()
  if (defaults) {
    options.instructions = `${defaults}\n${options.instructions}`.trim()
  }
  const llm = getLlm(options.model)
  const source = ctx.state.download as SourceResult

  if (options.campaign_mode) {
    if (!options.campaign_brief.trim()) {
      throw new Error('Add the campaign rules before starting a campaign edit.')
    }
    if (llm.provider.local) {
      throw new Error('Campaign montage editing needs a vision-capable model. Select Gemini or OpenRouter in Settings.')
    }
    const plan = await parseCampaignBrief(llm, options.campaign_brief)
    const sources = source.sources ?? [source as SourceItem]
    const analyses = []
    for (let i = 0; i < sources.length; i++) {
      analyses.push(
        await analyzeCampaignVideo(
          sources[i],
          path.join(ctx.workDir, `campaign-source-${String(i + 1).padStart(2, '0')}`),
          llm,
          options.campaign_brief,
        ),
      )
    }
    const count = Math.min(10, plan.output_count || options.clip_count)
    const target = plan.target_duration_seconds || options.max_seconds
    const edits = await buildMontagePlan(llm, options.campaign_brief, plan, sources, analyses, count, target, options.instructions)
    updateRun(ctx.runId, { title: plan.campaign_name || source.title || 'Campaign edit' })
    const clips: SelectedClip[] = edits.map((edit) => {
      const duration = edit.shots.reduce((sum, s) => sum + (s.end_seconds - s.start_seconds), 0)
      return {
        rank: edit.rank,
        title: edit.title,
        post_title: edit.title,
        caption: '',
        hashtags: [],
        broll_queries: [],
        rationale: 'AI-selected campaign montage',
        score: 0,
        transcript: '',
        start_seconds: 0,
        end_seconds: Math.round(duration * 1000) / 1000,
        campaign_shots: edit.shots,
      }
    })
    return { campaign_plan: plan, campaign_edits: edits, clips }
  }

  const transcript = ctx.state.transcribe as Transcript
  return (await selectClips(llm, source, transcript, options)) as unknown as Record<string, unknown>
}

async function stagePlan(ctx: PipelineContext): Promise<Record<string, unknown>> {
  const selection = ctx.state.select as { clips: SelectedClip[] }
  if (ctx.options.campaign_mode) {
    return {
      clips: selection.clips.map((c) => ({
        rank: c.rank,
        start_seconds: 0,
        end_seconds: c.end_seconds,
        duration_seconds: c.end_seconds,
        windows: [],
      })),
    }
  }
  const transcript = ctx.state.transcribe as Transcript
  return planTimeline(selection.clips, transcript, ctx.options.broll) as unknown as Record<string, unknown>
}

async function stageBroll(ctx: PipelineContext): Promise<Record<string, unknown>> {
  if (ctx.options.campaign_mode) return { clips: [] }
  const plan = JSON.parse(JSON.stringify(ctx.state.plan)) as { clips: TimelineClip[] }
  const orientation = ctx.options.aspect_ratio === '1:1' ? 'square' : 'portrait'
  return (await fillBroll(plan, ctx.workDir, getSetting('pexels_api_key'), orientation)) as unknown as Record<string, unknown>
}

async function stageReframe(ctx: PipelineContext): Promise<Record<string, unknown>> {
  if (ctx.options.campaign_mode) return { clips: [] }
  const source = ctx.state.download as SourceResult
  const plan = ctx.state.plan as { clips: TimelineClip[] }
  const aspectMap: Record<AspectRatio, number> = { '9:16': 9 / 16, '4:5': 4 / 5, '1:1': 1 }
  const targetAspect = aspectMap[ctx.options.aspect_ratio]
  const srcW = source.width
  const srcH = source.height
  let cropW = srcW
  let cropH = srcH
  if (srcW / srcH > targetAspect) {
    cropH = srcH
    cropW = Math.round(srcH * targetAspect)
  } else {
    cropW = srcW
    cropH = Math.round(srcW / targetAspect)
  }
  cropW = cropW - (cropW % 2)
  cropH = cropH - (cropH % 2)
  const cropX = Math.max(0, Math.floor((srcW - cropW) / 2))
  const cropY = Math.max(0, Math.floor((srcH - cropH) / 2))

  return {
    clips: plan.clips.map((c) => ({
      rank: c.rank,
      crop: { width: cropW, height: cropH, x: cropX, y: cropY },
    })),
  }
}

async function stageRender(ctx: PipelineContext): Promise<Record<string, unknown>> {
  const [width, height] = SIZES[ctx.options.aspect_ratio]
  fs.mkdirSync(ctx.outDir, { recursive: true })
  const source = ctx.state.download as SourceResult
  const selection = ctx.state.select as { clips: SelectedClip[]; campaign_plan?: CampaignPlan }
  const brollTimeline = ctx.state.broll as { clips: TimelineClip[] }
  const reframe = ctx.state.reframe as { clips: { rank: number; crop: { width: number; height: number; x: number; y: number } }[] }
  const transcript = ctx.state.transcribe as Transcript

  const renders: {
    rank: number
    status: 'ready' | 'failed'
    file_path?: string
    width?: number
    height?: number
    duration_seconds?: number
    error?: string
  }[] = []

  if (ctx.options.campaign_mode) {
    const sources = source.sources ?? [source as SourceItem]
    for (const clip of selection.clips) {
      const output = path.join(ctx.outDir, `clip-${String(clip.rank).padStart(2, '0')}-${slugify(clip.title)}.mp4`)
      const clipDir = path.join(ctx.workDir, `clip-${String(clip.rank).padStart(2, '0')}`)
      fs.mkdirSync(clipDir, { recursive: true })
      try {
        await renderCampaignClip(sources, clip.campaign_shots ?? [], clipDir, output, width, height, ctx.options)
        const info = await probe(output)
        await makePoster(output, Math.min(1.0, info.duration / 2))
        renders.push({
          rank: clip.rank,
          status: 'ready',
          file_path: output,
          width: info.width,
          height: info.height,
          duration_seconds: Math.round(info.duration * 100) / 100,
        })
      } catch (err) {
        renders.push({ rank: clip.rank, status: 'failed', error: err instanceof Error ? err.message : String(err) })
      }
    }
  } else {
    const timeline = brollTimeline.clips?.length ? brollTimeline : (ctx.state.plan as { clips: TimelineClip[] })
    const cropByRank = new Map(reframe.clips.map((c) => [c.rank, c.crop]))
    const metaByRank = new Map(selection.clips.map((c) => [c.rank, c]))
    const addCaptions = ctx.options.captions && !ctx.options.source_has_subtitles

    for (const clip of timeline.clips) {
      const meta = metaByRank.get(clip.rank)!
      const crop = cropByRank.get(clip.rank)!
      const output = path.join(ctx.outDir, `clip-${String(clip.rank).padStart(2, '0')}-${slugify(meta.title)}.mp4`)
      const clipDir = path.join(ctx.workDir, `clip-${String(clip.rank).padStart(2, '0')}`)
      fs.mkdirSync(clipDir, { recursive: true })

      try {
        const words = clipWords(transcript, clip.start_seconds, clip.end_seconds)
        let assPath: string | null = null
        if (addCaptions && words.length > 0) {
          assPath = writeAss(words, path.join(clipDir, 'captions.ass'), width, height, ctx.options.caption_style)
        }
        await renderStandardClip(source.video_path, clip, crop, clipDir, output, width, height, assPath)
        const info = await probe(output)
        await makePoster(output, Math.min(1.0, info.duration / 2))
        renders.push({
          rank: clip.rank,
          status: 'ready',
          file_path: output,
          width: info.width,
          height: info.height,
          duration_seconds: Math.round(info.duration * 100) / 100,
        })
      } catch (err) {
        renders.push({ rank: clip.rank, status: 'failed', error: err instanceof Error ? err.message : String(err) })
      }
    }
  }

  if (!renders.some((r) => r.status === 'ready')) {
    throw new Error('Every clip failed to render: ' + renders.map((r) => r.error || '').join('; '))
  }

  const byRank = new Map(renders.map((r) => [r.rank, r]))
  replaceClips(
    ctx.runId,
    selection.clips.map((c) => {
      const r = byRank.get(c.rank)!
      return {
        rank: c.rank,
        start_seconds: c.start_seconds,
        end_seconds: c.end_seconds,
        title: c.title,
        post_title: c.post_title,
        caption: c.caption,
        hashtags: c.hashtags,
        rationale: c.rationale,
        score: c.score ?? null,
        transcript: c.transcript,
        file_path: r.file_path ?? null,
        width: r.width ?? null,
        height: r.height ?? null,
        duration_seconds: r.duration_seconds ?? null,
        status: r.status,
        error: r.error ?? null,
      }
    }),
  )

  return {
    renders,
    quality_checks: ctx.options.campaign_mode
      ? {
          aspect_ratio: ctx.options.aspect_ratio,
          audio_track_included: Boolean(ctx.options.campaign_music_path),
          captions_or_lyrics_burned: Boolean(ctx.options.campaign_lyrics.trim()),
        }
      : undefined,
  }
}

async function renderStandardClip(
  sourceVideo: string,
  clip: TimelineClip,
  crop: { width: number; height: number; x: number; y: number },
  clipDir: string,
  output: string,
  width: number,
  height: number,
  assPath: string | null,
): Promise<void> {
  const audio = await hasAudio(sourceVideo)
  const hasBroll = clip.windows.some((w) => w.type === 'broll' && w.broll_path)

  if (!hasBroll) {
    const filters = [
      `crop=${crop.width}:${crop.height}:${crop.x}:${crop.y}`,
      `scale=${width}:${height}`,
      'setsar=1',
      'fps=30',
      'format=yuv420p',
    ]
    if (assPath) filters.push(assFilter(assPath))

    const args = [
      '-ss',
      String(clip.start_seconds),
      '-to',
      String(clip.end_seconds),
      '-i',
      sourceVideo,
      '-vf',
      filters.join(','),
      '-c:v',
      'libx264',
      '-preset',
      'veryfast',
      '-crf',
      '20',
      ...(audio ? ['-c:a', 'aac', '-b:a', '160k'] : ['-an']),
      '-movflags',
      '+faststart',
      output,
    ]
    await runFfmpeg(args)
    return
  }

  const segDir = path.join(clipDir, 'segments')
  fs.mkdirSync(segDir, { recursive: true })
  const segPaths: string[] = []
  for (const w of clip.windows) {
    const segPath = path.join(segDir, `${String(w.index).padStart(3, '0')}.mp4`)
    if (w.type === 'broll' && w.broll_path) {
      await runFfmpeg([
        '-stream_loop',
        '-1',
        '-i',
        w.broll_path,
        '-t',
        String(w.duration),
        '-vf',
        `scale=${width}:${height}:force_original_aspect_ratio=increase,crop=${width}:${height},setsar=1,fps=30,format=yuv420p`,
        '-an',
        '-c:v',
        'libx264',
        '-preset',
        'veryfast',
        '-crf',
        '18',
        segPath,
      ])
    } else {
      await runFfmpeg([
        '-ss',
        String(clip.start_seconds + w.start),
        '-to',
        String(clip.start_seconds + w.end),
        '-i',
        sourceVideo,
        '-vf',
        `crop=${crop.width}:${crop.height}:${crop.x}:${crop.y},scale=${width}:${height},setsar=1,fps=30,format=yuv420p`,
        '-an',
        '-c:v',
        'libx264',
        '-preset',
        'veryfast',
        '-crf',
        '18',
        segPath,
      ])
    }
    segPaths.push(segPath)
  }

  const concatFile = path.join(segDir, 'list.txt')
  fs.writeFileSync(concatFile, segPaths.map((p) => `file '${path.resolve(p)}'`).join('\n'), 'utf-8')

  const inputs = ['-f', 'concat', '-safe', '0', '-i', concatFile]
  const maps = ['-map', '0:v:0']
  if (audio) {
    inputs.push('-ss', String(clip.start_seconds), '-to', String(clip.end_seconds), '-i', sourceVideo)
    maps.push('-map', '1:a:0', '-c:a', 'aac', '-b:a', '160k')
  }
  const videoArgs = assPath
    ? ['-vf', assFilter(assPath), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20']
    : ['-c:v', 'copy']

  await runFfmpeg([...inputs, ...maps, ...videoArgs, '-shortest', '-movflags', '+faststart', output])
  fs.rmSync(segDir, { recursive: true, force: true })
}

async function renderCampaignClip(
  sources: SourceItem[],
  shots: MontageShot[],
  clipDir: string,
  output: string,
  width: number,
  height: number,
  options: ClipOptions,
): Promise<void> {
  const segDir = path.join(clipDir, 'segments')
  fs.mkdirSync(segDir, { recursive: true })
  const segPaths: string[] = []
  let totalDuration = 0

  for (let i = 0; i < shots.length; i++) {
    const shot = shots[i]
    const src = sources[shot.source_index] ?? sources[0]
    const segPath = path.join(segDir, `shot-${String(i).padStart(3, '0')}.mp4`)
    await runFfmpeg([
      '-ss',
      String(shot.start_seconds),
      '-to',
      String(shot.end_seconds),
      '-i',
      src.video_path,
      '-vf',
      `scale=${width}:${height}:force_original_aspect_ratio=increase,crop=${width}:${height},setsar=1,fps=30,format=yuv420p`,
      '-an',
      '-c:v',
      'libx264',
      '-preset',
      'veryfast',
      '-crf',
      '18',
      segPath,
    ])
    segPaths.push(segPath)
    totalDuration += shot.end_seconds - shot.start_seconds
  }

  const concatFile = path.join(segDir, 'list.txt')
  fs.writeFileSync(concatFile, segPaths.map((p) => `file '${path.resolve(p)}'`).join('\n'), 'utf-8')

  const lyricLines = options.campaign_lyrics
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

  let assPath: string | null = null
  if (lyricLines.length > 0 && totalDuration > 0) {
    const step = totalDuration / lyricLines.length
    const syntheticWords = lyricLines.flatMap((line, idx) => {
      const lineStart = idx * step
      const tokens = line.split(/\s+/)
      const wordStep = step / Math.max(1, tokens.length)
      return tokens.map((word, wIdx) => ({
        word,
        start: lineStart + wIdx * wordStep,
        end: lineStart + (wIdx + 1) * wordStep,
      }))
    })
    assPath = writeAss(syntheticWords, path.join(clipDir, 'lyrics.ass'), width, height, options.caption_style)
  }

  const inputs = ['-f', 'concat', '-safe', '0', '-i', concatFile]
  const maps = ['-map', '0:v:0']
  if (options.campaign_music_path && fs.existsSync(options.campaign_music_path)) {
    inputs.push('-i', options.campaign_music_path)
    maps.push('-map', '1:a:0', '-c:a', 'aac', '-b:a', '160k', '-shortest')
  }
  const videoArgs = assPath
    ? ['-vf', assFilter(assPath), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20']
    : ['-c:v', 'copy']

  await runFfmpeg([...inputs, ...maps, ...videoArgs, '-movflags', '+faststart', output])
  fs.rmSync(segDir, { recursive: true, force: true })
}

// ── Runner & Queue Worker ────────────────────────────────────────────────────

async function executeRun(run: RunRecord): Promise<void> {
  const workDir = path.join(runDir(run.id), 'work')
  const outDir = path.join(runDir(run.id), 'clips')
  fs.mkdirSync(workDir, { recursive: true })
  const ctx: PipelineContext = {
    runId: run.id,
    source: run.source,
    options: run.options,
    workDir,
    outDir,
    state: {},
  }

  for (const stage of STAGES) {
    const artifact = path.join(workDir, `${stage.name}.json`)
    if (fs.existsSync(artifact)) {
      ctx.state[stage.name] = JSON.parse(fs.readFileSync(artifact, 'utf-8'))
      setStage(run.id, stage.name, 'done')
      continue
    }
    updateRun(run.id, { current_stage: stage.name })
    setStage(run.id, stage.name, 'running')
    try {
      const result = await stage.fn(ctx)
      fs.writeFileSync(artifact, JSON.stringify(result, null, 2), 'utf-8')
      ctx.state[stage.name] = result
      setStage(run.id, stage.name, 'done')
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setStage(run.id, stage.name, 'failed', msg)
      updateRun(run.id, { status: 'failed', error: `${stage.name}: ${msg}` })
      return
    }
  }

  updateRun(run.id, { status: 'completed', current_stage: null, error: null })
}

let workerRunning = false
let workerScheduled = false

export function wakeWorker(): void {
  if (workerRunning) {
    workerScheduled = true
    return
  }
  void processQueue()
}

async function processQueue(): Promise<void> {
  if (workerRunning) return
  workerRunning = true
  try {
    while (true) {
      const next = claimNextRun()
      if (!next) break
      await executeRun(next)
    }
  } finally {
    workerRunning = false
    if (workerScheduled) {
      workerScheduled = false
      void processQueue()
    }
  }
}

export function retryRun(runId: string, fromStage?: string | null): void {
  if (fromStage) {
    const work = path.join(runDir(runId), 'work')
    const idx = STAGE_NAMES.indexOf(fromStage)
    if (idx !== -1) {
      for (const name of STAGE_NAMES.slice(idx)) {
        const artifact = path.join(work, `${name}.json`)
        if (fs.existsSync(artifact)) fs.unlinkSync(artifact)
        setStage(runId, name, 'pending')
      }
    }
  }
  updateRun(runId, { status: 'queued', error: null })
  wakeWorker()
}

export function deleteRunAndFiles(runId: string): void {
  dbDeleteRun(runId)
  fs.rmSync(runDir(runId), { recursive: true, force: true })
}

export function runDetail(runId: string): Record<string, unknown> | null {
  const run = getRun(runId)
  if (!run) return null
  const stageRows = new Map(listStages(runId).map((s) => [s.name, s]))
  const stages = STAGES.map(({ name, label }) => {
    const row = stageRows.get(name)
    let durationSeconds: number | undefined
    if (row?.started_at) {
      const started = new Date(row.started_at).getTime()
      const finished = row.finished_at ? new Date(row.finished_at).getTime() : Date.now()
      durationSeconds = Math.round(Math.max(0, (finished - started) / 1000) * 10) / 10
    }
    return {
      name,
      label,
      status: row?.status ?? 'pending',
      error: row?.error ?? null,
      started_at: row?.started_at ?? null,
      finished_at: row?.finished_at ?? null,
      duration_seconds: durationSeconds,
    }
  })

  const workDir = path.join(runDir(runId), 'work')
  let sourceDuration: number | null = null
  let campaignPlan: unknown = null
  let campaignQualityChecks: unknown = null

  const downloadFile = path.join(workDir, 'download.json')
  if (fs.existsSync(downloadFile)) {
    const parsed = JSON.parse(fs.readFileSync(downloadFile, 'utf-8')) as { duration_seconds?: number }
    sourceDuration = parsed.duration_seconds ?? null
  }
  const selectFile = path.join(workDir, 'select.json')
  if (fs.existsSync(selectFile)) {
    const parsed = JSON.parse(fs.readFileSync(selectFile, 'utf-8')) as { campaign_plan?: unknown }
    campaignPlan = parsed.campaign_plan ?? null
  }
  const renderFile = path.join(workDir, 'render.json')
  if (fs.existsSync(renderFile)) {
    const parsed = JSON.parse(fs.readFileSync(renderFile, 'utf-8')) as { quality_checks?: unknown }
    campaignQualityChecks = parsed.quality_checks ?? null
  }

  const clips = listClips(runId).map((c) => ({
    id: c.id,
    run_id: c.run_id,
    rank: c.rank,
    start_seconds: c.start_seconds,
    end_seconds: c.end_seconds,
    duration_seconds: c.duration_seconds,
    title: c.title,
    post_title: c.post_title,
    caption: c.caption,
    hashtags: c.hashtags,
    rationale: c.rationale,
    score: c.score,
    transcript: c.transcript,
    status: c.status,
    error: c.error,
    filename: c.file_path ? path.basename(c.file_path) : null,
    video_url: `/api/clips/${c.id}/video`,
    poster_url: `/api/clips/${c.id}/poster`,
    download_url: `/api/clips/${c.id}/video?download=true`,
  }))

  return {
    ...run,
    source_duration: sourceDuration,
    campaign_plan: campaignPlan,
    campaign_quality_checks: campaignQualityChecks,
    stages,
    clips,
    posts: listPosts({ runId }),
  }
}
