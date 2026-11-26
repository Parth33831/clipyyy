export type RunStatus = 'queued' | 'running' | 'completed' | 'failed'
export type StageStatus = 'pending' | 'running' | 'done' | 'failed'
export type AspectRatio = '9:16' | '4:5' | '1:1'
export type CaptionStyle = 'bold' | 'highlight' | 'minimal'
export type PublishMode = 'queue' | 'now' | 'schedule' | 'draft'

export interface CampaignTextOverlay {
  rank: number
  text: string
  start_seconds: number
  end_seconds: number
  position_x: number
  position_y: number
  font_size_percent: number
  rotation_degrees?: number
  z_index?: number
  font_family?: 'Arial' | 'Georgia' | 'Impact' | 'Trebuchet MS' | 'Verdana'
  font_weight?: 'regular' | 'bold'
  text_effect?: 'none' | 'shadow' | 'outline'
  color: string
  animation: 'none' | 'fade' | 'pop' | 'slide'
  background: boolean
}

export interface ClipOptions {
  clip_count: number
  min_seconds: number
  max_seconds: number
  aspect_ratio: AspectRatio
  captions: boolean
  normalize_audio: boolean
  remove_filler_words: boolean
  source_has_subtitles: boolean
  caption_style: CaptionStyle
  face_tracking: boolean
  broll: boolean
  language: string
  instructions: string
  campaign_mode: boolean
  campaign_brief: string
  campaign_url: string
  campaign_music_path: string | null
  campaign_music_volume?: number
  campaign_source_audio_volume?: number
  campaign_music_ducking?: boolean
  campaign_music_start_seconds?: number
  campaign_music_fade_in_seconds?: number
  campaign_music_fade_out_seconds?: number
  campaign_auto_broll: boolean
  campaign_camera_motion: boolean
  campaign_transition_style: 'auto' | 'cut' | 'cinematic' | 'dynamic'
  campaign_conversation_hook?: boolean
  campaign_lyrics: string
  campaign_lyric_words?: { word: string; start: number; end: number; track_start?: number }[]
  campaign_lyrics_source?: string | null
  campaign_lyrics_style?: 'dynamic' | 'cinematic' | 'minimal' | 'karaoke'
  campaign_lyrics_color?: string
  campaign_lyrics_highlight_color?: string
  campaign_lyrics_words_on_screen?: 1 | 2 | 3
  campaign_lyrics_position_x?: number
  campaign_lyrics_position_y?: number
  campaign_lyrics_scale_percent?: number
  campaign_lyrics_rotation_degrees?: number
  campaign_lyric_phrase_edits?: CampaignLyricPhraseEdit[]
  campaign_lyrics_behind_subject?: boolean
  campaign_text_overlays?: CampaignTextOverlay[]
  campaign_hook_text?: string
  include_campaign_hook?: boolean
  model: string | null
}

export interface Run {
  id: string
  source: string
  title: string | null
  status: RunStatus
  current_stage: string | null
  error: string | null
  options: ClipOptions
  created_at: string
  updated_at: string
  clip_count?: number
}

export interface Stage {
  name: string
  label: string
  status: StageStatus
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
  duration_seconds?: number
}

export interface Clip {
  id: string
  run_id: string
  rank: number
  start_seconds: number
  end_seconds: number
  duration_seconds: number | null
  filler_words_removed?: number
  title: string
  post_title: string
  caption: string
  hashtags: string[]
  rationale: string
  score: number | null
  transcript: string
  status: 'ready' | 'failed'
  error: string | null
  filename: string | null
  video_url: string
  poster_url: string
  download_url: string
}

export interface Post {
  id: string
  clip_id: string
  channel_id: string
  channel_name: string | null
  service: string | null
  mode: PublishMode
  scheduled_at: string | null
  status: 'sent_to_buffer' | 'failed'
  error: string | null
  created_at: string
}

export interface CampaignPlan {
  [key: string]: string | number | boolean | string[] | null | undefined
}

export interface CampaignShot {
  source_index: number
  start_seconds: number
  end_seconds: number
  reason: string
}

export interface CampaignLyricResyncProposal {
  lyrics: string
  words: { word: string; start: number; end: number }[]
  language: string | null
  word_count: number
  matched_count?: number
  match_percent?: number
  unmatched_words?: string[]
  mode?: 'transcription' | 'alignment'
  saved: false
  rendered: false
}

export interface CampaignLyricWordEdit {
  word_index: number
  word?: string
  start?: number
  end?: number
}

export interface CampaignLyricPhraseEdit {
  phrase_index: number
  start_seconds?: number
  end_seconds?: number
  position_x?: number
  position_y?: number
  scale_percent?: number
  rotation_degrees?: number
  animation_style?: "dynamic" | "cinematic" | "minimal" | "karaoke"
}

export interface CampaignEdit {
  rank: number
  title: string
  shots: CampaignShot[]
}

export interface CampaignAiEditProposal {
  proposal: CampaignEdit
  notes: string[]
  saved: false
  rendered: false
}

export interface CampaignConcept {
  id: string
  name: string
  summary: string
  edits: CampaignEdit[]
  refined_edits?: CampaignEdit[]
  refinement_notes?: string[]
}

export interface CampaignSource {
  index: number
  title: string
  duration_seconds: number
}

export interface CampaignEnergySection {
  start_seconds: number
  end_seconds: number
  level: 'low' | 'medium' | 'high'
  average_energy: number
}

export interface CampaignBeatMarker {
  time_seconds: number
  strength: number
  energy: number
}

export interface CampaignMusicAnalysis {
  duration_seconds: number
  selected_start_seconds: number
  selected_section: string
  estimated_bpm: number | null
  detected_beats: number
  beat_markers?: CampaignBeatMarker[]
  energy_sections?: CampaignEnergySection[]
}

export interface CampaignWaveform {
  duration_seconds: number
  peaks: number[]
}

export interface CampaignQualityChecks {
  [key: string]: string | boolean | number | null | CampaignMusicAnalysis | undefined
  music_analysis?: CampaignMusicAnalysis | null
}

export interface RunDetail extends Run {
  campaign_plan: CampaignPlan | null
  campaign_edits: CampaignEdit[]
  campaign_original_edits: CampaignEdit[]
  campaign_concepts?: CampaignConcept[]
  campaign_sources: CampaignSource[]
  campaign_quality_checks: CampaignQualityChecks | null
  source_duration: number | null
  stages: Stage[]
  clips: Clip[]
  posts: Post[]
}

export interface Setting {
  key: string
  value: string
  is_set: boolean
  secret: boolean
  source: 'app' | 'env' | 'default'
  env: string
  description: string
}

export interface Check {
  name: string
  label: string
  ok: boolean
  required: boolean
  detail: string
}

export interface Health {
  version: string
  checks: Check[]
  queue: { queued: number; running: number }
  worker: boolean
}

export interface Model {
  id: string
  name: string
  context_length: number | null
  prompt_price_per_million: number | null
  completion_price_per_million: number | null
}

export interface Channel {
  id: string
  name: string
  service: string
  avatar: string
}

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join('; ')
    } catch {
      /* not JSON */
    }
    throw new ApiError(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<Health>('/api/health'),
  settings: () => request<Setting[]>('/api/settings'),
  saveSettings: (values: Record<string, string | null>) =>
    request<Setting[]>('/api/settings', { method: 'PUT', body: JSON.stringify({ values }) }),
  models: () => request<Model[]>('/api/models'),
  runs: () => request<Run[]>('/api/runs'),
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  createRuns: (sources: string[], options: ClipOptions) =>
    request<Run[]>('/api/runs', { method: 'POST', body: JSON.stringify({ sources, options }) }),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ source: string; name: string }>('/api/uploads', { method: 'POST', body: form })
  },
  attachCampaignMusic: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ name: string; attached: boolean }>(`/api/runs/${id}/campaign-music`, { method: 'POST', body: form })
  },
  campaignWaveform: (id: string, bins = 640) =>
    request<CampaignWaveform>(`/api/runs/${id}/campaign-waveform?bins=${bins}`),
  saveCampaignAudio: (id: string, musicVolume: number, sourceAudioVolume: number, duckMusic: boolean, musicStartSeconds: number, fadeInSeconds: number, fadeOutSeconds: number) =>
    request<{ saved: boolean; rendered: boolean; outputs: number }>(`/api/runs/${id}/campaign-audio`, {
      method: 'PUT',
      body: JSON.stringify({ music_volume: musicVolume, source_audio_volume: sourceAudioVolume, duck_music: duckMusic, music_start_seconds: musicStartSeconds, fade_in_seconds: fadeInSeconds, fade_out_seconds: fadeOutSeconds }),
    }),
  saveCampaignLyrics: (
    id: string,
    lyrics: string,
    lyricsStyle: 'dynamic' | 'cinematic' | 'minimal' | 'karaoke' | 'zoom' | 'bounce' | 'pulse' | 'glitch',
    hookText: string,
    includeHook: boolean,
    lyricsColor: string,
    highlightColor: string,
    wordsOnScreen: 1 | 2 | 3,
    lyricsBehindSubject: boolean,
    positionX: number,
    positionY: number,
    scalePercent: number,
    rotationDegrees: number,
    phraseEdits: CampaignLyricPhraseEdit[] = [],
    wordEdits: CampaignLyricWordEdit[] = [],
    replaceWords?: { word: string; start: number; end: number }[],
  ) =>
    request<{ saved: boolean; rendered: boolean; characters: number; outputs: number }>(`/api/runs/${id}/campaign-lyrics`, {
      method: 'PUT',
      body: JSON.stringify({ lyrics, lyrics_style: lyricsStyle, hook_text: hookText, include_hook: includeHook, lyrics_color: lyricsColor, highlight_color: highlightColor, words_on_screen: wordsOnScreen, lyrics_behind_subject: lyricsBehindSubject, position_x: positionX, position_y: positionY, scale_percent: scalePercent, rotation_degrees: rotationDegrees, phrase_edits: phraseEdits, word_edits: wordEdits, ...(replaceWords ? { replace_words: replaceWords } : {}) }),
    }),
  resyncCampaignLyrics: (id: string) =>
    request<CampaignLyricResyncProposal>(`/api/runs/${id}/campaign-lyrics-resync`, { method: 'POST' }),
  alignCampaignLyrics: (id: string, lyrics: string) =>
    request<CampaignLyricResyncProposal>(`/api/runs/${id}/campaign-lyrics-align`, {
      method: 'POST',
      body: JSON.stringify({ lyrics }),
    }),
  saveCampaignTextOverlays: (id: string, overlays: CampaignTextOverlay[]) =>
    request<{ saved: boolean; rendered: boolean; overlays: number; outputs: number }>(`/api/runs/${id}/campaign-text-overlays`, {
      method: 'PUT',
      body: JSON.stringify({ overlays }),
    }),
  saveCampaignMontage: (id: string, edits: CampaignEdit[]) =>
    request<{ saved: boolean; rendered: boolean; outputs: number }>(`/api/runs/${id}/campaign-montage`, {
      method: 'PUT',
      body: JSON.stringify({ edits }),
    }),
  generateCampaignAiEdit: (id: string, currentEdit: CampaignEdit, creativeDirection: string) =>
    request<CampaignAiEditProposal>(`/api/runs/${id}/campaign-ai-edit`, {
      method: 'POST',
      body: JSON.stringify({ current_edit: currentEdit, creative_direction: creativeDirection }),
    }),
  retry: (id: string, fromStage?: string) =>
    request<RunDetail>(`/api/runs/${id}/retry`, {
      method: 'POST',
      body: JSON.stringify({ from_stage: fromStage ?? null }),
    }),
  deleteRun: (id: string) => request<{ deleted: string }>(`/api/runs/${id}`, { method: 'DELETE' }),
  channels: () => request<Channel[]>('/api/buffer/channels'),
  organizations: () => request<{ id: string; name: string }[]>('/api/buffer/organizations'),
  publish: (
    clipId: string,
    body: { channel_ids: string[]; mode: PublishMode; scheduled_at?: string | null; text?: string; title?: string },
  ) => request<Post[]>(`/api/clips/${clipId}/publish`, { method: 'POST', body: JSON.stringify(body) }),
}

export const DEFAULT_OPTIONS: ClipOptions = {
  clip_count: 3,
  min_seconds: 20,
  max_seconds: 60,
  aspect_ratio: '9:16',
  captions: true,
  normalize_audio: false,
  remove_filler_words: false,
  source_has_subtitles: false,
  caption_style: 'bold',
  face_tracking: true,
  broll: false,
  language: 'auto',
  instructions: '',
  campaign_mode: false,
  campaign_brief: '',
  campaign_url: '',
  campaign_music_path: null,
  campaign_auto_broll: false,
  campaign_camera_motion: true,
  campaign_transition_style: 'auto',
  campaign_conversation_hook: false,
  campaign_lyrics: '',
  model: null,
}
