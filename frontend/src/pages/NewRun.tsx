import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, FileVideo, KeyRound, Upload, X } from 'lucide-react'
import { useRef, useState, type DragEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { api, DEFAULT_OPTIONS, type AspectRatio, type CaptionStyle, type ClipOptions } from '../api'
import { ModelInput } from '../components/ModelInput'
import { Button, Eyebrow, Field, Input, Panel, Select, Stepper, Textarea, Toggle, cn } from '../components/ui'

const LANGUAGES = [
  ['auto', 'Detect automatically'],
  ['en', 'English'],
  ['es', 'Spanish'],
  ['pt', 'Portuguese'],
  ['fr', 'French'],
  ['de', 'German'],
  ['it', 'Italian'],
  ['nl', 'Dutch'],
  ['hi', 'Hindi'],
  ['ar', 'Arabic'],
  ['ja', 'Japanese'],
  ['ko', 'Korean'],
  ['zh', 'Chinese'],
]

const ASPECTS: { value: AspectRatio; label: string; w: number; h: number }[] = [
  { value: '9:16', label: 'Shorts · Reels', w: 18, h: 32 },
  { value: '4:5', label: 'Feed', w: 24, h: 30 },
  { value: '1:1', label: 'Square', w: 28, h: 28 },
]

const STYLES: { value: CaptionStyle; label: string; sample: ReactNode }[] = [
  {
    value: 'bold',
    label: 'Bold',
    sample: (
      <span className="lowercase">
        make <span className="text-white/45">it</span> <span className="text-[#FFD400]">pop</span>
      </span>
    ),
  },
  {
    value: 'highlight',
    label: 'Highlight',
    sample: (
      <span>
        MAKE <span className="text-[#2BE36F]">IT</span> POP
      </span>
    ),
  },
  { value: 'minimal', label: 'Minimal', sample: <span className="font-sans text-[11px] font-semibold">Make it pop</span> },
]

const LENGTH_PRESETS: [number, number][] = [
  [15, 30],
  [20, 60],
  [45, 90],
]

export function NewRunPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [musicFile, setMusicFile] = useState<File | null>(null)
  const [options, setOptions] = useState<ClipOptions>(DEFAULT_OPTIONS)
  const [dragging, setDragging] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const health = useQuery({ queryKey: ['health'], queryFn: api.health })
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })

  const checks = Object.fromEntries((health.data?.checks ?? []).map((c) => [c.name, c]))
  const blockers = (health.data?.checks ?? []).filter((c) => c.required && !c.ok && c.name !== 'llm')
  const needsKey = health.data && !checks.llm?.ok
  const defaultModel = settings.data?.find((s) => s.key === 'llm_model')?.value
  const set = <K extends keyof ClipOptions>(key: K, value: ClipOptions[K]) => setOptions((o) => ({ ...o, [key]: value }))

  const urls = text
    .split(/\s+/)
    .map((s) => s.trim())
    .filter((s) => /^https?:\/\//.test(s))
  const count = urls.length + files.length

  const submit = useMutation({
    mutationFn: async () => {
      const uploaded = []
      for (const file of files) uploaded.push((await api.upload(file)).source)
      const music = musicFile ? (await api.upload(musicFile)).source : null
      return api.createRuns([...urls, ...uploaded], { ...options, campaign_music_path: music })
    },
    onSuccess: (runs) => {
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      toast.success(options.campaign_mode ? 'Campaign montage queued' : runs.length === 1 ? 'Clipping started' : `${runs.length} videos queued`)
      navigate(runs.length === 1 ? `/runs/${runs[0].id}` : '/runs')
    },
    onError: (error) => toast.error(error.message),
  })

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    const dropped = Array.from(event.dataTransfer.files).filter((f) => f.type.startsWith('video/'))
    if (dropped.length) setFiles((current) => [...current, ...dropped])
    else toast.error('Drop a video file')
  }

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-4">
        <Eyebrow>New run</Eyebrow>
        <h1 className="display max-w-3xl text-[44px] sm:text-[56px]">
          Long video in, shorts out.
        </h1>
        <p className="max-w-xl text-[15px] leading-relaxed text-body">
          Paste a link or drop a recording. clipyyy transcribes it on your machine, lets an AI pick the moments worth posting, then
          reframes and captions each one.
        </p>
      </header>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex flex-col gap-6">
          {needsKey && <ConnectModel onSaved={() => queryClient.invalidateQueries()} />}
          {blockers.map((c) => (
            <Panel key={c.name} className="border-bad/40 bg-bad-soft p-4 text-sm text-bad">
              {c.label}: {c.detail}
            </Panel>
          ))}

          <section
            className={cn('px flex flex-col bg-ink text-white transition-shadow', dragging && 'shadow-[0_0_0_4px_var(--color-acid)]')}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <div className="flex items-center justify-between px-6 pt-6">
              <Eyebrow tone="light">Source</Eyebrow>
              {count > 0 && (
                <span className="label text-acid">
                  {count} video{count > 1 ? 's' : ''} ready
                </span>
              )}
            </div>
            <textarea
              aria-label="Video links"
              rows={Math.min(6, Math.max(2, text.split('\n').length))}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={options.campaign_mode ? 'Paste 1–6 source video links, one per line. They will be combined into one campaign edit.' : 'https://www.youtube.com/watch?v=…\nOne link per line to clip a batch.'}
              className="resize-none bg-transparent px-6 pt-4 font-mono text-[15px] leading-relaxed text-white outline-none placeholder:text-white/30"
            />

            <div className="px-6 pt-4">
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                className={cn(
                  'film flex w-full cursor-pointer items-center justify-center gap-3 border border-dashed border-white/20 px-4 py-8 text-sm text-white/60 transition-colors hover:border-acid hover:text-white',
                  dragging && 'border-acid text-white',
                )}
              >
                <Upload className="h-4 w-4" />
                <span>
                  Drop a video file, or <span className="text-acid underline underline-offset-4">browse</span>
                </span>
              </button>
              <input
                ref={fileInput}
                type="file"
                accept="video/*"
                multiple
                hidden
                onChange={(e) => setFiles((current) => [...current, ...Array.from(e.target.files ?? [])])}
              />
              {files.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {files.map((file, i) => (
                    <span key={i} className="px-sm flex items-center gap-2 bg-ink-3 px-2.5 py-1.5 text-[13px]">
                      <FileVideo className="h-3.5 w-3.5 text-acid" />
                      <span className="max-w-[240px] truncate">{file.name}</span>
                      <span className="font-mono text-[11px] text-white/40">{(file.size / 1e6).toFixed(0)} MB</span>
                      <button aria-label={`Remove ${file.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))} className="text-white/40 hover:text-white">
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="mt-6 flex flex-wrap items-center gap-4 border-t border-white/10 px-6 py-4">
              <p className="label text-white/45">
                {options.clip_count} clips · {options.min_seconds}–{options.max_seconds}s · {options.aspect_ratio}
                {options.captions && !options.source_has_subtitles ? ` · ${options.caption_style} captions` : options.source_has_subtitles ? ' · original subtitles' : ''}
                {options.broll ? ' · b-roll' : ''}
              </p>
              <Button
                variant="acid"
                size="lg"
                className="ml-auto disabled:!bg-ink-3 disabled:!text-white/35 disabled:!opacity-100"
                disabled={count === 0 || !!needsKey || blockers.length > 0 || (options.campaign_mode && (count > 6 || !options.campaign_brief.trim()))}
                loading={submit.isPending}
                onClick={() => submit.mutate()}
              >
                {options.campaign_mode ? 'Create campaign edit' : count > 1 ? `Clip ${count} videos` : 'Find clips'} <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
            {options.campaign_mode && count > 6 && (
              <p className="px-6 pb-3 text-xs text-red-300">Campaigns support up to 6 source videos per edit.</p>
            )}
          </section>

          <ol className="grid gap-px border border-line bg-line sm:grid-cols-3">
            {[
              ['01', 'Transcribe', 'Whisper runs locally with word timings. Nothing leaves your machine but the transcript text.'],
              ['02', 'Pick moments', 'Your chosen model reads the transcript and ranks hooks that stand on their own.'],
              ['03', 'Cut & caption', 'Each clip is reframed on the speaker and gets word-by-word captions, ready to post.'],
            ].map(([n, title, body]) => (
              <li key={n} className="flex flex-col gap-2 bg-surface p-5">
                <span className="label text-faint">{n}</span>
                <span className="font-semibold">{title}</span>
                <span className="text-[13px] leading-relaxed text-muted">{body}</span>
              </li>
            ))}
          </ol>
        </div>

        <Panel className="flex flex-col lg:sticky lg:top-8">
          <Section title="Clips">
            <div className="flex items-end gap-4">
              <Field label="How many" group>
                <Stepper label="Number of clips" value={options.clip_count} min={1} max={10} onChange={(v) => set('clip_count', v)} />
              </Field>
              {options.campaign_mode ? (
                <Field label="Target duration (seconds)" group className="flex-1">
                  <Input aria-label="Target duration" type="number" min={10} max={180} value={options.max_seconds} onChange={(e) => set('max_seconds', Number(e.target.value))} className="font-mono" />
                </Field>
              ) : (
                <Field label="Length (seconds)" group className="flex-1">
                  <div className="flex items-center gap-2">
                    <Input aria-label="Minimum seconds" type="number" min={5} value={options.min_seconds} onChange={(e) => set('min_seconds', Number(e.target.value))} className="font-mono" />
                    <span className="text-faint">–</span>
                    <Input aria-label="Maximum seconds" type="number" max={180} value={options.max_seconds} onChange={(e) => set('max_seconds', Number(e.target.value))} className="font-mono" />
                  </div>
                </Field>
              )}
            </div>
            {!options.campaign_mode && <div className="flex gap-1.5">
              {LENGTH_PRESETS.map(([min, max]) => {
                const on = options.min_seconds === min && options.max_seconds === max
                return (
                  <button
                    key={min}
                    type="button"
                    onClick={() => setOptions((o) => ({ ...o, min_seconds: min, max_seconds: max }))}
                    className={cn('label px-sm cursor-pointer px-2 py-1 transition-colors', on ? 'bg-ink text-white' : 'bg-sunk text-muted hover:text-ink')}
                  >
                    {min}–{max}s
                  </button>
                )
              })}
            </div>}
          </Section>

          <Section title="Format">
            <div className="grid grid-cols-3 gap-2">
              {ASPECTS.map((a) => {
                const on = options.aspect_ratio === a.value
                return (
                  <button
                    key={a.value}
                    type="button"
                    aria-pressed={on}
                    onClick={() => set('aspect_ratio', a.value)}
                    className={cn(
                      'flex cursor-pointer flex-col items-center gap-2 border px-2 pb-2.5 pt-3 transition-colors',
                      on ? 'border-ink bg-paper' : 'border-line hover:border-line-strong',
                    )}
                  >
                    <span className="flex h-9 items-center">
                      <span className={cn('border-2', on ? 'border-ink bg-acid' : 'border-faint')} style={{ width: a.w, height: a.h }} />
                    </span>
                    <span className="font-mono text-[13px] font-semibold">{a.value}</span>
                    <span className="text-[11px] text-muted">{a.label}</span>
                  </button>
                )
              })}
            </div>
          </Section>

          {!options.campaign_mode && <Section title="Captions">
            <Toggle checked={options.captions} onChange={(v) => set('captions', v)} label="Animated captions" hint="Word by word, burned into the video" />
            <Toggle checked={options.source_has_subtitles} onChange={(v) => set('source_has_subtitles', v)} label="Video already has subtitles" hint="Skip Clipyyy captions to avoid showing two subtitle layers. Use this for subtitles already visible in the source video." />
            <div className="grid grid-cols-3 gap-2">
              {STYLES.map((style) => {
                const on = options.caption_style === style.value
                return (
                  <button
                    key={style.value}
                    type="button"
                    aria-pressed={on}
                    disabled={!options.captions || options.source_has_subtitles}
                    onClick={() => set('caption_style', style.value)}
                    className={cn(
                      'flex cursor-pointer flex-col gap-1.5 border p-1.5 transition disabled:cursor-not-allowed disabled:opacity-35',
                      on ? 'border-ink' : 'border-line hover:border-line-strong',
                    )}
                  >
                    <span className="px-sm flex h-14 items-end justify-center bg-ink pb-2 font-display text-[12px] text-white">{style.sample}</span>
                    <span className={cn('text-[12px]', on ? 'font-semibold' : 'text-muted')}>{style.label}</span>
                  </button>
                )
              })}
            </div>
          </Section>}

          {!options.campaign_mode && <Section title="Edit">
            <Toggle checked={options.face_tracking} onChange={(v) => set('face_tracking', v)} label="Follow the speaker" hint="Keeps the face in frame. Off uses a centre crop" />
            <Toggle
              checked={options.broll}
              onChange={(v) => set('broll', v)}
              disabled={!checks.broll?.ok}
              label="B-roll"
              hint={checks.broll?.ok ? 'Cuts in matching stock footage from Pexels' : 'Add a free Pexels key in Settings to enable'}
            />
            <Field label="Spoken language">
              <Select value={options.language} onChange={(e) => set('language', e.target.value)}>
                {LANGUAGES.map(([code, name]) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </Select>
            </Field>
          </Section>}

          <Section title="Campaign editor">
            <Toggle
              checked={options.campaign_mode}
              onChange={(v) => set('campaign_mode', v)}
              label="Use campaign requirements"
              hint="AI samples scenes from every source, selects matching moments and assembles a complete campaign montage. Multiple source videos become one edit run."
            />
            {options.campaign_mode && (
              <>
              <Field label="Campaign brief" hint="Paste the complete campaign rules, music, mood, subject, text requirements, platform rules and examples. Campaign montage creation requires Gemini vision; it does not use paid APIs beyond your configured provider quota.">
                <Textarea
                  rows={7}
                  value={options.campaign_brief}
                  onChange={(e) => set('campaign_brief', e.target.value)}
                  placeholder={"Example: Anime edit for Midnight Sunlight by Pyo. Music is the focus. Use emotional anime moments that fit the song's mood. Show a lyric line on screen. English text only. No voice audio."}
                />
              </Field>
              <Field label="Campaign music (optional)" hint="Upload a track you have permission to use. If the campaign requires an official TikTok/Instagram sound, leave this empty and add that sound inside the platform after export.">
                <input type="file" accept="audio/*" onChange={(e) => setMusicFile(e.target.files?.[0] ?? null)} className="block w-full text-sm text-muted file:mr-3 file:border file:border-line file:bg-surface file:px-3 file:py-2 file:text-ink" />
                {musicFile && <p className="text-xs text-muted">{musicFile.name}</p>}
              </Field>
              <Field label="Lyrics / exact on-screen text (optional)" hint="Paste only the lines you are allowed to use. They will be displayed in sequence across the edit.">
                <Textarea rows={3} value={options.campaign_lyrics} onChange={(e) => set('campaign_lyrics', e.target.value)} placeholder="One line per screen..." />
              </Field>
              </>
            )}
          </Section>
          <Section title="AI" last>
            <Field label="Instructions" hint="Optional. e.g. “Only funny moments” or “End captions with: Follow for part 2”">
              <Textarea rows={2} value={options.instructions} onChange={(e) => set('instructions', e.target.value)} />
            </Field>
            <Field label="Model" hint="Empty uses your default from Settings">
              <ModelInput placeholder={defaultModel} value={options.model ?? ''} onChange={(v) => set('model', v.trim() || null)} />
            </Field>
          </Section>
        </Panel>
      </div>
    </div>
  )
}

function Section({ title, children, last }: { title: string; children: ReactNode; last?: boolean }) {
  return (
    <div className={cn('flex flex-col gap-4 p-5', !last && 'border-b border-line')}>
      <p className="label text-ink">{title}</p>
      {children}
    </div>
  )
}

function ConnectModel({ onSaved }: { onSaved: () => void }) {
  const [key, setKey] = useState('')
  const save = useMutation({
    mutationFn: () => api.saveSettings({ openrouter_api_key: key.trim() }),
    onSuccess: () => {
      toast.success('Key saved on this machine')
      onSaved()
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <Panel className="flex flex-col gap-4 border-l-4 border-l-acid p-5 sm:flex-row sm:items-center">
      <div className="flex flex-1 items-start gap-3">
        <KeyRound className="mt-0.5 h-5 w-5 shrink-0" />
        <div>
          <p className="font-semibold">Connect a model to start</p>
          <p className="text-[13px] leading-relaxed text-muted">
            clipyyy picks clips with any model on{' '}
            <a href="https://openrouter.ai/keys" target="_blank" rel="noreferrer" className="text-ink underline underline-offset-2">
              OpenRouter
            </a>
            . Your key is stored only on this machine.
          </p>
        </div>
      </div>
      <form
        className="flex gap-2 sm:w-[340px]"
        onSubmit={(e) => {
          e.preventDefault()
          if (key.trim()) save.mutate()
        }}
      >
        <Input type="password" placeholder="sk-or-…" value={key} onChange={(e) => setKey(e.target.value)} aria-label="OpenRouter API key" />
        <Button type="submit" loading={save.isPending} disabled={!key.trim()}>
          Save
        </Button>
      </form>
    </Panel>
  )
}
