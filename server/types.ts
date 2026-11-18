export type RunStatus = 'queued' | 'running' | 'completed' | 'failed'
export type StageStatus = 'pending' | 'running' | 'done' | 'failed'
export type AspectRatio = '9:16' | '4:5' | '1:1'
export type CaptionStyle = 'bold' | 'highlight' | 'minimal'
export type PublishMode = 'queue' | 'now' | 'schedule' | 'draft'

export interface ClipOptions {
  clip_count: number
  min_seconds: number
  max_seconds: number
  aspect_ratio: AspectRatio
  captions: boolean
  source_has_subtitles: boolean
  caption_style: CaptionStyle
  face_tracking: boolean
  broll: boolean
  language: string
  instructions: string
  campaign_mode: boolean
  campaign_brief: string
  campaign_music_path: string | null
  campaign_lyrics: string
  model: string | null
}

export interface RunRecord {
  id: string
  source: string
  title: string | null
  status: RunStatus
  current_stage: string | null
  error: string | null
  options: ClipOptions
  created_at: string
  updated_at: string
}

export interface StageRecord {
  run_id: string
  name: string
  status: StageStatus
  error: string | null
  started_at: string | null
  finished_at: string | null
}

export interface ClipRecord {
  id: string
  run_id: string
  rank: number
  start_seconds: number
  end_seconds: number
  duration_seconds: number | null
  title: string
  post_title: string
  caption: string
  hashtags: string[]
  rationale: string
  score: number | null
  transcript: string
  file_path: string | null
  width: number | null
  height: number | null
  status: 'ready' | 'failed'
  error: string | null
  created_at: string
}

export interface PostRecord {
  id: string
  clip_id: string
  channel_id: string
  channel_name: string | null
  service: string | null
  mode: PublishMode
  scheduled_at: string | null
  status: 'sent_to_buffer' | 'failed'
  buffer_post_id?: string | null
  media_url?: string | null
  error: string | null
  created_at: string
}

export interface WordTiming {
  word: string
  start: number
  end: number
}

export interface Sentence {
  start: number
  end: number
  text: string
}

export interface Transcript {
  language: string
  sentences: Sentence[]
  words: WordTiming[]
  note?: string
}

export interface SourceItem {
  source: string
  title: string
  uploader: string
  duration_seconds: number
  width: number
  height: number
  video_path: string
  source_index?: number
}

export interface SourceResult {
  source: string
  title: string
  uploader?: string
  duration_seconds: number
  width: number
  height: number
  video_path: string
  sources?: SourceItem[]
}

export interface TimelineWindow {
  index: number
  type: 'speaker' | 'broll'
  start: number
  end: number
  duration: number
  text: string
  query: string | null
  broll_path?: string
  broll_credit?: string
  broll_page?: string
  note?: string
}

export interface TimelineClip {
  rank: number
  start_seconds: number
  end_seconds: number
  duration_seconds: number
  windows: TimelineWindow[]
}
