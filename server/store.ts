import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import type { ClipOptions, ClipRecord, PostRecord, RunRecord, StageRecord, StageStatus } from './types.js'

export interface SettingSpec {
  env: string
  default: string
  secret: boolean
  description: string
}

export const SETTINGS: Record<string, SettingSpec> = {
  llm_provider: { env: 'CLIPYYY_LLM_PROVIDER', default: 'openrouter', secret: false, description: 'LLM provider' },
  openrouter_api_key: { env: 'OPENROUTER_API_KEY', default: '', secret: true, description: 'OpenRouter API key' },
  gemini_api_key: { env: 'GEMINI_API_KEY', default: '', secret: true, description: 'Google Gemini API key' },
  llm_model: { env: 'CLIPYYY_LLM_MODEL', default: 'google/gemini-3.8-flash', secret: false, description: 'Model used to pick clips' },
  whisper_model: { env: 'CLIPYYY_WHISPER_MODEL', default: 'base', secret: false, description: 'faster-whisper model size' },
  pexels_api_key: { env: 'PEXELS_API_KEY', default: '', secret: true, description: 'Pexels key for B-roll' },
  buffer_api_key: { env: 'BUFFER_API_KEY', default: '', secret: true, description: 'Buffer API key' },
  buffer_organization_id: { env: 'BUFFER_ORGANIZATION_ID', default: '', secret: false, description: 'Buffer organization (auto-picked if you have one)' },
  s3_endpoint_url: { env: 'CLIPYYY_S3_ENDPOINT_URL', default: '', secret: false, description: 'S3-compatible endpoint (R2, B2, MinIO). Empty for AWS' },
  s3_region: { env: 'CLIPYYY_S3_REGION', default: 'auto', secret: false, description: 'S3 region' },
  s3_bucket: { env: 'CLIPYYY_S3_BUCKET', default: '', secret: false, description: 'Bucket that hosts clips for Buffer' },
  s3_access_key_id: { env: 'CLIPYYY_S3_ACCESS_KEY_ID', default: '', secret: true, description: 'S3 key id' },
  s3_secret_access_key: { env: 'CLIPYYY_S3_SECRET_ACCESS_KEY', default: '', secret: true, description: 'S3 secret' },
  s3_public_base_url: { env: 'CLIPYYY_S3_PUBLIC_BASE_URL', default: '', secret: false, description: 'Public URL of the bucket. Empty uses 7-day signed links' },
  ytdlp_cookies_from_browser: { env: 'CLIPYYY_COOKIES_FROM_BROWSER', default: '', secret: false, description: 'Browser whose YouTube login yt-dlp may use (chrome, firefox, brave, edge...)' },
  ytdlp_cookies_file: { env: 'CLIPYYY_COOKIES_FILE', default: '', secret: false, description: 'Path to a cookies.txt file, used instead of a browser' },
  default_instructions: { env: 'CLIPYYY_DEFAULT_INSTRUCTIONS', default: '', secret: false, description: 'Extra guidance added to every clip-selection prompt (tone, CTA, audience)' },
}

export function homeDir(): string {
  const dir = process.env.CLIPYYY_HOME || path.join(os.tmpdir(), 'clipyyy')
  fs.mkdirSync(dir, { recursive: true })
  return dir
}

export function runsDir(): string {
  const dir = path.join(homeDir(), 'runs')
  fs.mkdirSync(dir, { recursive: true })
  return dir
}

export function uploadsDir(): string {
  const dir = path.join(homeDir(), 'uploads')
  fs.mkdirSync(dir, { recursive: true })
  return dir
}

export function runDir(runId: string): string {
  return path.join(runsDir(), runId)
}

export function nowIso(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, '+00:00')
}

export function newId(): string {
  return crypto.randomBytes(6).toString('hex')
}

// In-memory store (ephemeral per AI Studio runtime rules; no native SQLite)
const runsStore = new Map<string, RunRecord>()
const stagesStore = new Map<string, Map<string, StageRecord>>()
const clipsStore = new Map<string, ClipRecord>()
const postsStore = new Map<string, PostRecord>()
const settingsStore = new Map<string, string>()

export function getStoredSetting(key: string): string | null {
  return settingsStore.get(key) ?? null
}

export function getSetting(key: string): string {
  const spec = SETTINGS[key]
  if (!spec) return ''
  const stored = settingsStore.get(key)
  if (stored) return stored
  const envVal = process.env[spec.env]
  if (envVal) return envVal
  return spec.default
}

export function setSetting(key: string, value: string | null): void {
  if (value && value.trim()) {
    settingsStore.set(key, value.trim())
  } else {
    settingsStore.delete(key)
  }
}

export function mask(value: string): string {
  if (!value) return ''
  if (value.length <= 8) return '••••'
  return `${value.slice(0, 3)}••••${value.slice(-4)}`
}

export function createRun(source: string, options: ClipOptions): RunRecord {
  const id = newId()
  const ts = nowIso()
  const run: RunRecord = {
    id,
    source,
    title: null,
    status: 'queued',
    current_stage: null,
    error: null,
    options,
    created_at: ts,
    updated_at: ts,
  }
  runsStore.set(id, run)
  return { ...run }
}

export function getRun(runId: string): RunRecord | null {
  const r = runsStore.get(runId)
  return r ? { ...r } : null
}

export function listRuns(limit = 200): (RunRecord & { clip_count: number })[] {
  const all = Array.from(runsStore.values()).sort((a, b) => b.created_at.localeCompare(a.created_at))
  return all.slice(0, limit).map((run) => ({
    ...run,
    clip_count: listClips(run.id).filter((c) => c.status === 'ready').length,
  }))
}

export function updateRun(runId: string, patch: Partial<RunRecord>): void {
  const existing = runsStore.get(runId)
  if (!existing) return
  runsStore.set(runId, { ...existing, ...patch, updated_at: nowIso() })
}

export function deleteRun(runId: string): void {
  runsStore.delete(runId)
  stagesStore.delete(runId)
  for (const [clipId, clip] of clipsStore.entries()) {
    if (clip.run_id === runId) {
      clipsStore.delete(clipId)
      for (const [postId, post] of postsStore.entries()) {
        if (post.clip_id === clipId) postsStore.delete(postId)
      }
    }
  }
}

export function claimNextRun(): RunRecord | null {
  const queued = Array.from(runsStore.values())
    .filter((r) => r.status === 'queued')
    .sort((a, b) => a.created_at.localeCompare(b.created_at))
  if (!queued.length) return null
  const next = queued[0]
  const updated: RunRecord = { ...next, status: 'running', error: null, updated_at: nowIso() }
  runsStore.set(next.id, updated)
  return { ...updated }
}

export function queueCounts(): { queued: number; running: number } {
  let queued = 0
  let running = 0
  for (const run of runsStore.values()) {
    if (run.status === 'queued') queued += 1
    else if (run.status === 'running') running += 1
  }
  return { queued, running }
}

export function setStage(runId: string, name: string, status: StageStatus, error: string | null = null): void {
  let byName = stagesStore.get(runId)
  if (!byName) {
    byName = new Map()
    stagesStore.set(runId, byName)
  }
  const prev = byName.get(name)
  const ts = nowIso()
  byName.set(name, {
    run_id: runId,
    name,
    status,
    error,
    started_at: status === 'running' ? ts : (prev?.started_at ?? null),
    finished_at: status === 'done' || status === 'failed' ? ts : null,
  })
}

export function listStages(runId: string): StageRecord[] {
  const byName = stagesStore.get(runId)
  return byName ? Array.from(byName.values()) : []
}

export function replaceClips(
  runId: string,
  clips: Omit<ClipRecord, 'id' | 'run_id' | 'created_at'>[],
): ClipRecord[] {
  for (const [id, c] of clipsStore.entries()) {
    if (c.run_id === runId) clipsStore.delete(id)
  }
  const ts = nowIso()
  for (const clip of clips) {
    const id = newId()
    clipsStore.set(id, { ...clip, id, run_id: runId, created_at: ts })
  }
  return listClips(runId)
}

export function listClips(runId: string): ClipRecord[] {
  return Array.from(clipsStore.values())
    .filter((c) => c.run_id === runId)
    .sort((a, b) => a.rank - b.rank)
}

export function getClip(clipId: string): ClipRecord | null {
  const c = clipsStore.get(clipId)
  return c ? { ...c } : null
}

export function createPost(input: Omit<PostRecord, 'id' | 'created_at'>): PostRecord {
  const record: PostRecord = { ...input, id: newId(), created_at: nowIso() }
  postsStore.set(record.id, record)
  return { ...record }
}

export function listPosts(filter: { clipId?: string; runId?: string }): PostRecord[] {
  let clipIds: Set<string> | null = null
  if (filter.runId) {
    clipIds = new Set(listClips(filter.runId).map((c) => c.id))
  }
  return Array.from(postsStore.values())
    .filter((p) => {
      if (filter.clipId) return p.clip_id === filter.clipId
      if (clipIds) return clipIds.has(p.clip_id)
      return true
    })
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
}
