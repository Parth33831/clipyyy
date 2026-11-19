import fs from 'node:fs'
import path from 'node:path'
import archiver from 'archiver'
import express, { type NextFunction, type Request, type Response } from 'express'
import multer from 'multer'
import { listModels } from './server/llm.js'
import { findFfmpeg, findYtdlp, makePoster, posterPath } from './server/media.js'
import {
  deleteRunAndFiles,
  retryRun,
  runDetail,
  STAGE_NAMES,
  wakeWorker,
} from './server/pipeline.js'
import { BufferClient, PublishError, publishClip, storageConfigured } from './server/publish.js'
import {
  createRun,
  getClip,
  getRun,
  getSetting,
  getStoredSetting,
  listClips,
  listRuns,
  mask,
  newId,
  queueCounts,
  setSetting,
  SETTINGS,
  uploadsDir,
} from './server/store.js'
import type { ClipOptions, PublishMode } from './server/types.js'

const PORT = 3000
const HOST = '0.0.0.0'

const app = express()
app.use(express.json({ limit: '4mb' }))

const upload = multer({
  storage: multer.diskStorage({
    destination: (_req, _file, cb) => cb(null, uploadsDir()),
    filename: (_req, file, cb) => {
      const safeName = path.basename(file.originalname || 'upload.mp4')
      cb(null, `${newId()}-${safeName}`)
    },
  }),
  limits: { fileSize: 1024 * 1024 * 1024 },
})

const DEFAULT_OPTIONS: ClipOptions = {
  clip_count: 3,
  min_seconds: 20,
  max_seconds: 60,
  aspect_ratio: '9:16',
  captions: true,
  source_has_subtitles: false,
  caption_style: 'bold',
  face_tracking: true,
  broll: false,
  language: 'auto',
  instructions: '',
  campaign_mode: false,
  campaign_brief: '',
  campaign_music_path: null,
  campaign_lyrics: '',
  model: null,
}

function buildSettingsPayload() {
  return Object.entries(SETTINGS).map(([key, spec]) => {
    const stored = getStoredSetting(key)
    const value = getSetting(key)
    const source = stored ? 'app' : process.env[spec.env] ? 'env' : 'default'
    return {
      key,
      value: spec.secret ? mask(value) : value,
      is_set: Boolean(value),
      secret: spec.secret,
      source,
      env: spec.env,
      description: spec.description,
    }
  })
}

// ── Health & Settings ────────────────────────────────────────────────────────

app.get('/api/health', async (_req: Request, res: Response) => {
  const [ff, ytdlp] = await Promise.all([findFfmpeg(), findYtdlp()])
  const provider = getSetting('llm_provider') || 'openrouter'
  const keySetting = provider === 'openrouter' ? 'openrouter_api_key' : provider === 'gemini' ? 'gemini_api_key' : ''
  const llmKey = keySetting ? Boolean(getSetting(keySetting)) : false
  const llmReady = provider === 'ollama' || llmKey
  const llmDetail =
    provider === 'ollama'
      ? `Ollama (local) · ${getSetting('llm_model') || 'qwen2.5:1.5b'}`
      : llmReady
        ? `${provider} · ${getSetting('llm_model')}`
        : `add a ${provider} API key or select the local Ollama provider`

  res.json({
    version: '0.1.0',
    checks: [
      {
        name: 'ffmpeg',
        label: 'FFmpeg',
        ok: Boolean(ff.ffmpeg && ff.ffprobe),
        required: true,
        detail: ff.ffmpeg && ff.ffprobe ? ff.ffmpeg : 'ffmpeg and ffprobe not found',
      },
      {
        name: 'captions',
        label: 'Captions',
        ok: ff.libass,
        required: true,
        detail: ff.libass ? 'ffmpeg has libass' : "this ffmpeg can't draw captions (no libass)",
      },
      {
        name: 'downloads',
        label: 'YouTube downloads',
        ok: Boolean(ytdlp),
        required: false,
        detail: ytdlp
          ? `yt-dlp ready (${ytdlp})`
          : 'upload a video file or direct .mp4 URL (yt-dlp unavailable in Node.js container)',
      },
      {
        name: 'llm',
        label: 'AI model',
        ok: llmReady,
        required: true,
        detail: llmDetail,
      },
      {
        name: 'broll',
        label: 'B-roll',
        ok: Boolean(getSetting('pexels_api_key')),
        required: false,
        detail: getSetting('pexels_api_key') ? 'Pexels key set' : 'optional: add a Pexels key',
      },
      {
        name: 'buffer',
        label: 'Buffer',
        ok: Boolean(getSetting('buffer_api_key')),
        required: false,
        detail: getSetting('buffer_api_key') ? 'Buffer key set' : 'optional: add a Buffer key',
      },
      {
        name: 'storage',
        label: 'Storage',
        ok: storageConfigured(),
        required: false,
        detail: storageConfigured() ? 'S3 storage set' : 'optional: needed to publish to Buffer',
      },
    ],
    queue: queueCounts(),
    worker: true,
  })
})

app.get('/api/settings', (_req: Request, res: Response) => {
  res.json(buildSettingsPayload())
})

app.put('/api/settings', (req: Request, res: Response) => {
  const values = (req.body as { values?: Record<string, string | null> })?.values ?? {}
  for (const [key, value] of Object.entries(values)) {
    if (!(key in SETTINGS)) {
      res.status(400).json({ detail: `Unknown setting: ${key}` })
      return
    }
    if (SETTINGS[key].secret && value && value.includes('••••')) {
      continue
    }
    setSetting(key, value)
  }
  res.json(buildSettingsPayload())
})

app.get('/api/models', async (_req: Request, res: Response) => {
  try {
    res.json(await listModels())
  } catch (err) {
    res.status(502).json({ detail: `Could not load models: ${err instanceof Error ? err.message : String(err)}` })
  }
})

// ── Uploads & Runs ───────────────────────────────────────────────────────────

app.post('/api/uploads', upload.single('file'), (req: Request, res: Response) => {
  if (!req.file) {
    res.status(400).json({ detail: 'No file uploaded' })
    return
  }
  res.json({ source: req.file.path, name: req.file.originalname })
})

app.post('/api/runs', (req: Request, res: Response) => {
  const body = req.body as { sources?: string[]; options?: Partial<ClipOptions> }
  const sources = (body.sources ?? []).map((s) => s.trim()).filter(Boolean)
  if (!sources.length) {
    res.status(400).json({ detail: 'At least one source video is required' })
    return
  }
  const options: ClipOptions = { ...DEFAULT_OPTIONS, ...(body.options ?? {}) }
  if (!options.campaign_mode && options.max_seconds < options.min_seconds + 5) {
    res.status(400).json({ detail: 'max_seconds must be at least 5 seconds more than min_seconds' })
    return
  }

  let runs
  if (options.campaign_mode) {
    if (!options.campaign_brief.trim()) {
      res.status(400).json({ detail: 'Paste the campaign brief before starting the campaign editor.' })
      return
    }
    if (sources.length < 1 || sources.length > 6) {
      res.status(400).json({ detail: 'A campaign edit needs between 1 and 6 source videos.' })
      return
    }
    runs = [createRun(JSON.stringify(sources), options)]
  } else {
    runs = sources.map((src) => createRun(src, options))
  }
  wakeWorker()
  res.json(runs)
})

app.get('/api/runs', (_req: Request, res: Response) => {
  res.json(listRuns())
})

app.get('/api/runs/:runId', (req: Request, res: Response) => {
  const detail = runDetail(String(req.params.runId))
  if (!detail) {
    res.status(404).json({ detail: 'Run not found' })
    return
  }
  res.json(detail)
})

app.post('/api/runs/:runId/retry', (req: Request, res: Response) => {
  const runId = String(req.params.runId)
  const run = getRun(runId)
  if (!run) {
    res.status(404).json({ detail: 'Run not found' })
    return
  }
  if (run.status === 'queued' || run.status === 'running') {
    res.status(409).json({ detail: 'Run is already queued or running' })
    return
  }
  const fromStage = (req.body as { from_stage?: string | null })?.from_stage ?? null
  if (fromStage && !STAGE_NAMES.includes(fromStage)) {
    res.status(400).json({ detail: `Unknown stage: ${fromStage}` })
    return
  }
  retryRun(runId, fromStage)
  res.json(runDetail(runId))
})

app.delete('/api/runs/:runId', (req: Request, res: Response) => {
  const runId = String(req.params.runId)
  const run = getRun(runId)
  if (!run) {
    res.status(404).json({ detail: 'Run not found' })
    return
  }
  if (run.status === 'running') {
    res.status(409).json({ detail: 'Wait for the run to finish before deleting it' })
    return
  }
  deleteRunAndFiles(runId)
  res.json({ deleted: runId })
})

app.get('/api/runs/:runId/download', (req: Request, res: Response) => {
  const runId = String(req.params.runId)
  const run = getRun(runId)
  if (!run) {
    res.status(404).json({ detail: 'Run not found' })
    return
  }
  const clips = listClips(runId).filter((c) => c.status === 'ready' && c.file_path && fs.existsSync(c.file_path))
  if (!clips.length) {
    res.status(404).json({ detail: 'No clips to download yet' })
    return
  }
  const safeTitle = (run.title || runId).toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40) || runId
  res.setHeader('Content-Type', 'application/zip')
  res.setHeader('Content-Disposition', `attachment; filename="clipyyy-${safeTitle}.zip"`)

  const archive = archiver('zip', { store: true })
  archive.on('error', (err) => {
    if (!res.headersSent) res.status(500).json({ detail: err.message })
  })
  archive.pipe(res)
  for (const c of clips) {
    archive.file(c.file_path!, { name: path.basename(c.file_path!) })
  }
  archive.append(JSON.stringify(clips, null, 2), { name: 'clips.json' })
  void archive.finalize()
})

// ── Clips & Buffer Publishing ────────────────────────────────────────────────

app.get('/api/clips/:clipId/video', (req: Request, res: Response) => {
  const clip = getClip(String(req.params.clipId))
  if (!clip || !clip.file_path || !fs.existsSync(clip.file_path)) {
    res.status(404).json({ detail: 'Clip file not found' })
    return
  }
  const download = req.query.download === 'true'
  if (download) {
    res.download(clip.file_path, path.basename(clip.file_path))
  } else {
    res.sendFile(path.resolve(clip.file_path))
  }
})

app.get('/api/clips/:clipId/poster', async (req: Request, res: Response) => {
  const clip = getClip(String(req.params.clipId))
  if (!clip || !clip.file_path || !fs.existsSync(clip.file_path)) {
    res.status(404).json({ detail: 'Clip file not found' })
    return
  }
  const poster = posterPath(clip.file_path)
  if (!fs.existsSync(poster)) {
    await makePoster(clip.file_path, 1.0)
  }
  res.sendFile(path.resolve(poster))
})

app.get('/api/buffer/channels', async (_req: Request, res: Response) => {
  try {
    res.json(await new BufferClient().channels())
  } catch (err) {
    res.status(err instanceof PublishError ? 400 : 500).json({ detail: err instanceof Error ? err.message : String(err) })
  }
})

app.get('/api/buffer/organizations', async (_req: Request, res: Response) => {
  try {
    res.json(await new BufferClient().organizations())
  } catch (err) {
    res.status(err instanceof PublishError ? 400 : 500).json({ detail: err instanceof Error ? err.message : String(err) })
  }
})

app.post('/api/clips/:clipId/publish', async (req: Request, res: Response) => {
  const body = req.body as {
    channel_ids?: string[]
    mode?: PublishMode
    scheduled_at?: string | null
    text?: string
    title?: string
  }
  if (!body.channel_ids?.length) {
    res.status(400).json({ detail: 'Select at least one channel' })
    return
  }
  try {
    const posts = await publishClip(
      String(req.params.clipId),
      body.channel_ids,
      body.mode ?? 'queue',
      body.scheduled_at,
      body.text,
      body.title,
    )
    res.json(posts)
  } catch (err) {
    res.status(err instanceof PublishError ? 400 : 500).json({ detail: err instanceof Error ? err.message : String(err) })
  }
})

app.use('/api', (_req: Request, res: Response) => {
  res.status(404).json({ detail: 'Not found' })
})

app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
  const msg = err instanceof Error ? err.message : 'Internal server error'
  res.status(500).json({ detail: msg })
})

// ── Frontend Serving (Vite dev middleware in dev, dist/public in prod) ───────

async function start() {
  if (process.env.NODE_ENV !== 'production') {
    const { createServer: createViteServer } = await import('vite')
    const vite = await createViteServer({
      root: path.resolve('frontend'),
      configFile: path.resolve('frontend/vite.config.ts'),
      server: { middlewareMode: true },
      appType: 'spa',
    })
    app.use(vite.middlewares)
  } else {
    const publicDir = path.resolve('dist/public')
    app.use(express.static(publicDir))
    app.get('*', (_req, res) => {
      res.sendFile(path.join(publicDir, 'index.html'))
    })
  }

  app.listen(PORT, HOST, () => {
    console.log(`clipyyy server listening on http://${HOST}:${PORT}`)
  })
}

void start()
