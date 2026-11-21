import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, ArrowUpRight, Check, ChevronDown, Copy, Download, RotateCcw, Send, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { api, type CampaignEdit, type CampaignMusicAnalysis, type CampaignShot, type CampaignSource, type Clip, type Post, type RunDetail } from '../api'
import { PublishDialog } from '../components/PublishDialog'
import { Button, Eyebrow, Panel, Squares, StatusChip, cn, formatDuration, sourceHost, sourceLabel, timeAgo } from '../components/ui'

export function RunDetailPage() {
  const { runId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const run = useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.run(runId),
    refetchInterval: (query) => (['queued', 'running'].includes(query.state.data?.status ?? '') ? 2000 : false),
  })
  const health = useQuery({ queryKey: ['health'], queryFn: api.health })
  const canPublish = ['buffer', 'storage'].every((name) => health.data?.checks.find((c) => c.name === name)?.ok)
  const [publishing, setPublishing] = useState<Clip | null>(null)
  const [focused, setFocused] = useState<number | null>(null)
  const [musicFile, setMusicFile] = useState<File | null>(null)
  const [lyricsText, setLyricsText] = useState('')
  const [lyricsStyle, setLyricsStyle] = useState<
    'dynamic' | 'cinematic' | 'minimal' | 'karaoke' | 'zoom' | 'bounce' | 'pulse' | 'glitch'
  >('dynamic')
  const [hookText, setHookText] = useState('')
  const [includeHook, setIncludeHook] = useState(false)
  const [lyricsColor, setLyricsColor] = useState('#FFFFFF')
  const [lyricsHighlightColor, setLyricsHighlightColor] = useState('#00D7FF')
  const [lyricsWordsOnScreen, setLyricsWordsOnScreen] = useState<1 | 2 | 3>(3)
  const [campaignEdits, setCampaignEdits] = useState<CampaignEdit[]>([])
  useEffect(() => {
    setLyricsText(run.data?.options.campaign_lyrics ?? '')
    setLyricsStyle(run.data?.options.campaign_lyrics_style ?? 'dynamic')
    setHookText(run.data?.options.campaign_hook_text ?? String(run.data?.campaign_plan?.generated_hook ?? ''))
    setIncludeHook(Boolean(run.data?.options.include_campaign_hook))
    setLyricsColor(run.data?.options.campaign_lyrics_color ?? '#FFFFFF')
    setLyricsHighlightColor(run.data?.options.campaign_lyrics_highlight_color ?? '#00D7FF')
    setLyricsWordsOnScreen(run.data?.options.campaign_lyrics_words_on_screen ?? 3)
    setCampaignEdits(run.data?.campaign_edits ?? [])
  }, [runId, run.data?.campaign_edits, run.data?.options.campaign_lyrics, run.data?.options.campaign_lyrics_style, run.data?.options.campaign_hook_text, run.data?.options.include_campaign_hook, run.data?.options.campaign_lyrics_color, run.data?.options.campaign_lyrics_highlight_color, run.data?.options.campaign_lyrics_words_on_screen, run.data?.campaign_plan?.generated_hook])

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['run', runId] })
    queryClient.invalidateQueries({ queryKey: ['runs'] })
  }
  const retry = useMutation({
    mutationFn: (fromStage?: string) => api.retry(runId, fromStage),
    onSuccess: () => {
      toast.success('Queued again')
      refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  const attachMusic = useMutation({
    mutationFn: (file: File) => api.attachCampaignMusic(runId, file),
    onSuccess: (result) => {
      toast.success(`Attached ${result.name}. Choose Pick again to render the campaign with music.`)
      setMusicFile(null)
      refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  const saveLyrics = useMutation({
    mutationFn: () => api.saveCampaignLyrics(runId, lyricsText, lyricsStyle, hookText, includeHook, lyricsColor, lyricsHighlightColor, lyricsWordsOnScreen),
    onSuccess: (result) => {
      toast.success(`Applied to ${result.outputs} existing edit(s) — no re-picking or lyric transcription.`)
      refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  const saveMontage = useMutation({
    mutationFn: () => api.saveCampaignMontage(runId, campaignEdits),
    onSuccess: (result) => {
      toast.success(`Rebuilt ${result.outputs} campaign edit(s) from your storyboard.`)
      refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  const remove = useMutation({
    mutationFn: () => api.deleteRun(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      navigate('/runs')
    },
    onError: (e) => toast.error(e.message),
  })

  if (run.isLoading) return <p className="text-muted">Loading…</p>
  if (run.error || !run.data)
    return (
      <div className="flex flex-col gap-3">
        <p className="display text-3xl">Run not found</p>
        <Link to="/runs" className="label underline underline-offset-4">
          Back to runs
        </Link>
      </div>
    )
  const data = run.data
  const busy = data.status === 'queued' || data.status === 'running'
  const readyClips = data.clips.filter((c) => c.status === 'ready')

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-end gap-6">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <Eyebrow>
            Run {data.id} · {timeAgo(data.created_at)}
          </Eyebrow>
          <h1 className="display line-clamp-2 text-4xl">{sourceLabel(data)}</h1>
          <div className="label flex flex-wrap items-center gap-x-3 gap-y-1 text-muted">
            <StatusChip status={data.status} />
            {data.options.campaign_mode ? (
              <span>{(() => {
                try {
                  const parsed = JSON.parse(data.source)
                  return `Campaign montage · ${Array.isArray(parsed) ? parsed.length : 1} source videos`
                } catch {
                  return 'Campaign montage'
                }
              })()}</span>
            ) : /^https?:\/\//.test(data.source) ? (
              <a href={data.source} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-ink">
                {sourceHost(data.source)} <ArrowUpRight className="h-3 w-3" />
              </a>
            ) : (
              <span>Local file</span>
            )}
            {data.source_duration != null && <span>{formatDuration(data.source_duration)} source</span>}
            <span>{data.options.aspect_ratio}</span>
            <span>
              {data.options.min_seconds}–{data.options.max_seconds}s
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          {readyClips.length > 0 && (
            <a href={`/api/runs/${data.id}/download`}>
              <Button variant="ink">
                <Download className="h-4 w-4" /> Download all
              </Button>
            </a>
          )}
          {!busy && (
            <Button variant="line" loading={retry.isPending} onClick={() => retry.mutate(data.status === 'completed' ? 'select' : undefined)}>
              <RotateCcw className="h-4 w-4" /> {data.status === 'completed' ? 'Pick again' : 'Retry'}
            </Button>
          )}
          <Button
            variant="danger"
            aria-label="Delete run"
            disabled={data.status === 'running'}
            loading={remove.isPending}
            onClick={() => confirm('Delete this run and its clips?') && remove.mutate()}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </header>

      {data.options.campaign_mode && !busy && (
        <div className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-4">
          <div className="flex flex-col gap-2 border-b border-line pb-4">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium">Opening text hook</span>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={includeHook} onChange={(event) => setIncludeHook(event.target.checked)} />
                Include in video
              </label>
            </div>
            {typeof data.campaign_plan?.generated_hook === 'string' && data.campaign_plan.generated_hook && (
              <p className="text-xs text-muted">AI suggestion: {data.campaign_plan.generated_hook}</p>
            )}
            <textarea value={hookText} onChange={(event) => setHookText(event.target.value)} rows={2} maxLength={160}
              placeholder="Write your own opening text, or leave blank for no text hook."
              className="w-full rounded-lg border border-line bg-panel p-3 text-sm text-ink placeholder:text-muted" />
            <span className="text-xs text-muted">Off by default. Your edit does not need campaign branding or AI-generated text.</span>
          </div>
          <div className="flex flex-wrap items-end gap-3">
          <label className="flex min-w-0 flex-1 flex-col gap-2 text-sm">
            <span className="font-medium">Campaign music</span>
            <input
              type="file"
              accept="audio/*"
              onChange={(event) => setMusicFile(event.target.files?.[0] ?? null)}
              className="block w-full text-sm text-muted file:mr-3 file:border file:border-line file:bg-panel file:px-3 file:py-2 file:text-ink"
            />
            <span className="text-xs text-muted">
              {data.options.campaign_music_path
                ? data.campaign_plan?.official_platform_sound_required
                  ? 'A track is attached and will be included in the export. TikTok’s official sound must still be selected separately when publishing.'
                  : 'A track is attached and will be included in the export. Upload another to replace it.'
                : 'No track attached. Add your downloaded campaign track here.'}
            </span>
          </label>
          <Button
            variant="line"
            disabled={!musicFile}
            loading={attachMusic.isPending}
            onClick={() => musicFile && attachMusic.mutate(musicFile)}
          >
            Attach music
          </Button>
          </div>
          <div className="flex flex-col gap-3 text-sm">
            <span className="font-medium">Lyrics animation preset</span>
            <div className="grid gap-2 sm:grid-cols-2">
              {([
                ['dynamic', '01 · Pop Punch', 'Quick zoom + colour hit', 'lyric-preview-pop'],
                ['karaoke', '02 · Karaoke Sweep', 'Word-by-word highlight', 'lyric-preview-karaoke'],
                ['cinematic', '03 · Cinematic Fade', 'Smooth, clean entrance', 'lyric-preview-fade'],
                ['minimal', '04 · Minimal', 'Simple readable lyrics', 'lyric-preview-minimal'],
                ['zoom', '05 · Zoom Burst', 'Big pop-in, settle back', 'lyric-preview-zoom'],
                ['bounce', '06 · Elastic Bounce', 'Springy movement', 'lyric-preview-bounce'],
                ['pulse', '07 · Beat Pulse', 'Scale pulse on each phrase', 'lyric-preview-pulse'],
                ['glitch', '08 · Tilt Pop', 'Tilted punch and settle', 'lyric-preview-tilt'],
              ] as const).map(([value, title, description, animationClass]) => (
                <button key={value} type="button" onClick={() => setLyricsStyle(value)}
                  aria-pressed={lyricsStyle === value}
                  className={cn('flex items-center gap-3 rounded-lg border p-3 text-left transition-colors',
                    lyricsStyle === value ? 'border-ink bg-sunk' : 'border-line bg-panel hover:border-line-strong')}>
                  <span className="flex h-12 w-24 shrink-0 items-center justify-center overflow-hidden rounded-md bg-ink">
                    <span className={cn('text-sm font-black tracking-tight', animationClass)}
                      style={{ color: lyricsColor, textShadow: '0 1px 3px #000' }}>Lyric!</span>
                  </span>
                  <span className="flex min-w-0 flex-col gap-1">
                    <span className="font-medium">{title}</span>
                    <span className="text-xs text-muted">{description}</span>
                    {lyricsStyle === value && <span className="text-[10px] font-semibold uppercase tracking-wider text-ok">Selected</span>}
                  </span>
                </button>
              ))}
            </div>
            <span className="text-xs text-muted">Each tile previews the motion. Change the preset or lyrics, then apply it to the existing montage; saved shots and Whisper word timings are reused.</span>
          </div>
          <div className="flex flex-col gap-2 rounded-lg border border-line bg-panel p-3 text-sm">
            <span className="font-medium">Words on screen at once</span>
            <div className="flex gap-2">
              {([1, 2, 3] as const).map((count) => (
                <button key={count} type="button" onClick={() => setLyricsWordsOnScreen(count)}
                  aria-pressed={lyricsWordsOnScreen === count}
                  className={cn('flex-1 rounded-lg border px-3 py-2 font-semibold transition-colors',
                    lyricsWordsOnScreen === count ? 'border-ink bg-sunk text-ink' : 'border-line bg-panel text-muted hover:border-line-strong')}>
                  {count} {count === 1 ? 'word' : 'words'}
                </button>
              ))}
            </div>
            <span className="text-xs text-muted">Shows a rolling group of 1, 2, or 3 words as the song progresses. Default: 3.</span>
          </div>
          <div className="grid gap-4 rounded-lg border border-line bg-panel p-3 sm:grid-cols-2">
            <label className="flex items-center justify-between gap-3 text-sm">
              <span className="flex flex-col gap-1"><span className="font-medium">Lyrics color</span><span className="text-xs text-muted">Main caption text</span></span>
              <input type="color" aria-label="Lyrics text color" value={lyricsColor} onChange={(event) => setLyricsColor(event.target.value.toUpperCase())} className="h-10 w-14 cursor-pointer rounded border border-line bg-transparent p-1" />
            </label>
            <label className="flex items-center justify-between gap-3 text-sm">
              <span className="flex flex-col gap-1"><span className="font-medium">Highlight color</span><span className="text-xs text-muted">Second color / alternating words</span></span>
              <input type="color" aria-label="Lyrics highlight color" value={lyricsHighlightColor} onChange={(event) => setLyricsHighlightColor(event.target.value.toUpperCase())} className="h-10 w-14 cursor-pointer rounded border border-line bg-transparent p-1" />
            </label>
            <div className="flex flex-wrap gap-2 sm:col-span-2">
              {[
                ['White', '#FFFFFF'], ['Red', '#FF3B4F'], ['Blue', '#3488FF'], ['Yellow', '#FFE14A'],
                ['Pink', '#FF62B8'], ['Purple', '#A978FF'], ['Green', '#45D483'], ['Orange', '#FF963D'],
              ].map(([name, value]) => (
                <button key={value} type="button" onClick={() => setLyricsColor(value)} aria-label={name + ' lyrics color'} aria-pressed={lyricsColor === value}
                  className={cn('h-7 w-7 rounded-full border-2 transition-transform', lyricsColor === value ? 'scale-110 border-ink' : 'border-line')}
                  style={{ backgroundColor: value }} />
              ))}
            </div>
            <div className="flex items-center justify-center rounded-lg bg-ink px-4 py-5 sm:col-span-2">
              <p className="text-center text-xl font-extrabold tracking-wide" style={{ textShadow: '0 2px 4px #000, 0 0 10px #000' }}>
                <span style={{ color: lyricsColor }}>Pop </span><span style={{ color: lyricsHighlightColor }}>it, </span>
                <span style={{ color: lyricsColor }}>feel </span><span style={{ color: lyricsHighlightColor }}>the </span>
                <span style={{ color: lyricsColor }}>beat</span>
              </p>
            </div>
            <p className="text-xs text-muted sm:col-span-2">Colors are independent of animation style. Apply updates the existing edit without re-picking footage or re-transcribing the song.</p>
          </div>
          <label className="flex flex-col gap-2 text-sm">
            <span className="font-medium">Lyrics / timed captions</span>
            <textarea
              value={lyricsText}
              onChange={(event) => setLyricsText(event.target.value)}
              rows={5}
              maxLength={12000}
              placeholder={'Local Whisper will draft lyrics from the attached song. You can correct them here.\nFor precise timing, use LRC lines such as [00:12.40] lyric text.'}
              className="w-full rounded-lg border border-line bg-panel p-3 text-sm text-ink placeholder:text-muted"
            />
            <span className="text-xs text-muted">
              {data.options.campaign_lyrics_source || 'No lyric draft yet. Attach music and choose Pick again to create a local draft.'}
              {' '}Singing recognition can be inaccurate; review the words before publishing.
            </span>
          </label>
          <div className="flex justify-end">
            <Button variant="ink" loading={saveLyrics.isPending} onClick={() => saveLyrics.mutate()}>
              Apply to existing edit
            </Button>
          </div>
        </div>
      )}

      {(busy || data.status === 'failed') && <Progress run={data} />}

      {data.options.campaign_mode && !busy && campaignEdits.length > 0 && (
        <CampaignStoryboardEditor
          runId={runId}
          edits={campaignEdits}
          savedEdits={data.campaign_edits}
          originalEdits={data.campaign_original_edits ?? data.campaign_edits}
          sources={data.campaign_sources ?? []}
          musicAnalysis={data.campaign_quality_checks?.music_analysis ?? null}
          transitionStyle={data.options.campaign_transition_style ?? 'auto'}
          saving={saveMontage.isPending}
          onChange={setCampaignEdits}
          onSave={() => saveMontage.mutate()}
          onReset={() => setCampaignEdits(data.campaign_original_edits ?? data.campaign_edits)}
        />
      )}

      {data.campaign_plan && <CampaignPlanCard plan={data.campaign_plan} checks={data.campaign_quality_checks} />}

      {data.clips.length > 0 && data.source_duration && !data.options.campaign_mode ? (
        <Timeline run={data} focused={focused} onFocus={setFocused} />
      ) : null}

      {data.clips.length > 0 && (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {data.clips.map((clip) => (
            <ClipCard
              key={clip.id}
              clip={clip}
              focused={focused === clip.rank}
              onHover={setFocused}
              posts={data.posts.filter((p) => p.clip_id === clip.id)}
              canPublish={canPublish}
              onPublish={() => setPublishing(clip)}
            />
          ))}
        </div>
      )}

      {data.status === 'completed' && !canPublish && readyClips.length > 0 && (
        <p className="text-[13px] text-muted">
          Want to post straight to TikTok, Reels or Shorts?{' '}
          <Link to="/settings" className="text-ink underline underline-offset-2">
            Connect Buffer
          </Link>
          .
        </p>
      )}

      {publishing && <PublishDialog clip={publishing} onClose={() => setPublishing(null)} onDone={refresh} />}
    </div>
  )
}

function CampaignStoryboardEditor({
  runId,
  edits,
  savedEdits,
  originalEdits,
  sources,
  musicAnalysis,
  transitionStyle,
  saving,
  onChange,
  onSave,
  onReset,
}: {
  runId: string
  edits: CampaignEdit[]
  savedEdits: CampaignEdit[]
  originalEdits: CampaignEdit[]
  sources: CampaignSource[]
  musicAnalysis: CampaignMusicAnalysis | null
  transitionStyle: 'auto' | 'cut' | 'cinematic' | 'dynamic'
  saving: boolean
  onChange: (edits: CampaignEdit[]) => void
  onSave: () => void
  onReset: () => void
}) {
  const sourceByIndex = new Map(sources.map((source) => [source.index, source]))
  const changed = JSON.stringify(edits) !== JSON.stringify(savedEdits)
  const resetAvailable = JSON.stringify(savedEdits) !== JSON.stringify(originalEdits) || changed
  const shotCount = edits.reduce((total, edit) => total + edit.shots.length, 0)

  const updateShot = (editIndex: number, shotIndex: number, patch: Partial<CampaignShot>) => {
    onChange(edits.map((edit, index) => index !== editIndex ? edit : {
      ...edit,
      shots: edit.shots.map((shot, position) => position === shotIndex ? { ...shot, ...patch } : shot),
    }))
  }
  const moveShot = (editIndex: number, shotIndex: number, direction: -1 | 1) => {
    onChange(edits.map((edit, index) => {
      if (index !== editIndex) return edit
      const target = shotIndex + direction
      if (target < 0 || target >= edit.shots.length) return edit
      const shots = [...edit.shots]
      ;[shots[shotIndex], shots[target]] = [shots[target], shots[shotIndex]]
      return { ...edit, shots }
    }))
  }
  const removeShot = (editIndex: number, shotIndex: number) => {
    onChange(edits.map((edit, index) => index !== editIndex ? edit : {
      ...edit,
      shots: edit.shots.filter((_, position) => position !== shotIndex),
    }))
  }

  return (
    <Panel className="flex flex-col gap-5 p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Eyebrow>Campaign editor</Eyebrow>
          <h2 className="display mt-1 text-2xl">Edit your storyboard</h2>
          <p className="mt-1 text-[13px] text-muted">
            Reorder shots, adjust source in/out points or remove a shot. Saving rebuilds the montage from cached footage.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="line" disabled={!resetAvailable || saving} onClick={onReset}>
            <RotateCcw className="h-4 w-4" /> Reset AI plan
          </Button>
          <Button variant="ink" disabled={!changed || saving || edits.some((edit) => edit.shots.length < 3)} loading={saving} onClick={onSave}>
            Save &amp; re-render
          </Button>
        </div>
      </div>
      <p className="label text-muted">{edits.length} output(s) · {shotCount} shots · Keep at least 3 shots per output; each shot must be 1.5–5 seconds.</p>
      {edits.map((edit, editIndex) => (
        <section key={edit.rank} className="flex flex-col gap-3 border-t border-line pt-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-semibold">#{edit.rank} · {edit.title}</h3>
            <span className="label text-muted">{edit.shots.length} shots</span>
          </div>
          <CampaignTimeline
            edit={edit}
            runId={runId}
            sources={sources}
            musicAnalysis={musicAnalysis}
            transitionStyle={transitionStyle}
          />
          <ol className="flex flex-col gap-2">
            {edit.shots.map((shot, shotIndex) => {
              const source = sourceByIndex.get(shot.source_index)
              return (
                <li id={`campaign-shot-${edit.rank}-${shotIndex}`} key={`${edit.rank}-${shotIndex}-${shot.source_index}`} className="grid gap-3 rounded-lg border border-line bg-panel p-3 md:grid-cols-[112px_minmax(0,1fr)_150px_150px_auto] md:items-center">
                  <img
                    src={`/api/runs/${runId}/campaign-frame?source_index=${shot.source_index}&timestamp=${shot.start_seconds.toFixed(1)}`}
                    alt={`Preview of shot ${shotIndex + 1}`}
                    loading="lazy"
                    className="h-20 w-28 rounded-md border border-line bg-surface object-cover"
                  />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="label shrink-0 text-faint">SHOT {String(shotIndex + 1).padStart(2, '0')}</span>
                      <span className="truncate text-sm font-medium">{source?.title ?? `Source ${shot.source_index + 1}`}</span>
                    </div>
                    <p className="mt-1 text-xs text-muted">{shot.reason || 'AI-selected campaign moment'}</p>
                    <p className="mt-1 font-mono text-[11px] text-faint">
                      {formatDuration(shot.start_seconds)} → {formatDuration(shot.end_seconds)}
                      {source ? ` / ${formatDuration(source.duration_seconds)} source` : ''}
                    </p>
                  </div>
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Start (seconds)
                    <input type="number" min={0} max={source?.duration_seconds} step={0.1} value={shot.start_seconds}
                      onChange={(event) => updateShot(editIndex, shotIndex, { start_seconds: Number(event.target.value) })} disabled={saving}
                      className="w-full rounded-md border border-line bg-surface px-2 py-2 font-mono text-sm text-ink" />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    End (seconds)
                    <input type="number" min={0} max={source?.duration_seconds} step={0.1} value={shot.end_seconds}
                      onChange={(event) => updateShot(editIndex, shotIndex, { end_seconds: Number(event.target.value) })} disabled={saving}
                      className="w-full rounded-md border border-line bg-surface px-2 py-2 font-mono text-sm text-ink" />
                  </label>
                  <div className="flex items-center justify-end gap-1">
                    <button type="button" title="Move shot up" aria-label="Move shot up" disabled={saving || shotIndex === 0}
                      onClick={() => moveShot(editIndex, shotIndex, -1)} className="rounded-md border border-line p-2 text-muted hover:text-ink disabled:opacity-30">
                      <ArrowUp className="h-4 w-4" />
                    </button>
                    <button type="button" title="Move shot down" aria-label="Move shot down" disabled={saving || shotIndex === edit.shots.length - 1}
                      onClick={() => moveShot(editIndex, shotIndex, 1)} className="rounded-md border border-line p-2 text-muted hover:text-ink disabled:opacity-30">
                      <ArrowDown className="h-4 w-4" />
                    </button>
                    <button type="button" title="Remove shot" aria-label="Remove shot" disabled={saving}
                      onClick={() => removeShot(editIndex, shotIndex)} className="rounded-md border border-line p-2 text-muted hover:text-bad">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </li>
              )
            })}
          </ol>
          {edit.shots.length < 3 && <p className="text-xs text-bad">Restore the AI plan or keep at least 3 shots in this output.</p>}
        </section>
      ))}
    </Panel>
  )
}

function CampaignTimeline({
  edit,
  runId,
  sources,
  musicAnalysis,
  transitionStyle,
}: {
  edit: CampaignEdit
  runId: string
  sources: CampaignSource[]
  musicAnalysis: CampaignMusicAnalysis | null
  transitionStyle: 'auto' | 'cut' | 'cinematic' | 'dynamic'
}) {
  const sourceByIndex = new Map(sources.map((source) => [source.index, source]))
  const hasBeats = (musicAnalysis?.detected_beats ?? 0) > 0
  const useFades = transitionStyle === 'cinematic' || transitionStyle === 'dynamic' || (transitionStyle === 'auto' && !hasBeats)
  const shots = edit.shots.map((shot, index) => ({
    shot,
    index,
    duration: Math.max(0.1, shot.end_seconds - shot.start_seconds - (useFades && index > 0 ? 0.24 : 0)),
  }))
  const total = Math.max(0.1, shots.reduce((sum, item) => sum + item.duration, 0))
  const musicStart = musicAnalysis?.selected_start_seconds ?? 0

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-line bg-panel p-3">
      <div className="flex items-center justify-between gap-3">
        <span className="label text-muted">Video timeline</span>
        <span className="font-mono text-[11px] text-faint">{formatDuration(total)} estimated</span>
      </div>
      <div className="overflow-x-auto">
        <div className="flex min-w-[680px] gap-1 rounded-md bg-surface p-2">
          {shots.map(({ shot, index, duration }) => {
            const source = sourceByIndex.get(shot.source_index)
            return (
              <button
                key={`${edit.rank}-timeline-${index}`}
                type="button"
                title={`Shot ${index + 1}: ${source?.title ?? `Source ${shot.source_index + 1}`} · ${formatDuration(shot.end_seconds - shot.start_seconds)}`}
                aria-label={`Jump to shot ${index + 1} in the storyboard editor`}
                onClick={() => document.getElementById(`campaign-shot-${edit.rank}-${index}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                className="group min-w-[104px] flex-1 overflow-hidden rounded-md border border-line bg-paper text-left transition-colors hover:border-ink"
                style={{ flex: `${duration} 1 0%` }}
              >
                <img
                  src={`/api/runs/${runId}/campaign-frame?source_index=${shot.source_index}&timestamp=${shot.start_seconds.toFixed(1)}`}
                  alt=""
                  loading="lazy"
                  className="h-14 w-full object-cover"
                />
                <span className="flex items-center justify-between gap-1 px-2 py-1.5">
                  <span className="label truncate text-faint">SHOT {String(index + 1).padStart(2, '0')}</span>
                  <span className="font-mono text-[10px] text-muted">{formatDuration(shot.end_seconds - shot.start_seconds)}</span>
                </span>
              </button>
            )
          })}
        </div>
      </div>
      <div className="label flex justify-between px-1 text-faint">
        <span>0:00</span>
        <span>{formatDuration(total / 2)}</span>
        <span>{formatDuration(total)}</span>
      </div>
      {musicAnalysis && (
        <div className="flex flex-col gap-2 border-t border-line pt-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="label text-muted">Music energy track</span>
            <span className="font-mono text-[11px] text-faint">
              {musicAnalysis.estimated_bpm ? `${musicAnalysis.estimated_bpm} BPM` : 'Energy profile'}
              {' · '}{musicAnalysis.detected_beats} transients
            </span>
          </div>
          <div className="overflow-x-auto">
            <div className="relative h-9 min-w-[680px] overflow-hidden rounded-md bg-surface">
              {musicAnalysis.energy_sections.map((section, index) => {
                const left = Math.max(0, section.start_seconds - 0.25 - musicStart)
                const right = Math.min(total, section.end_seconds + 0.25 - musicStart)
                if (right <= left) return null
                return (
                  <div
                    key={`energy-${index}`}
                    title={`${section.level} energy · ${formatDuration(section.start_seconds)}–${formatDuration(section.end_seconds)}`}
                    className={cn(
                      'absolute inset-y-0 flex items-center overflow-hidden border-r border-paper/40 px-1',
                      section.level === 'high' ? 'bg-acid text-ink' : section.level === 'medium' ? 'bg-sunk text-ink' : 'bg-line text-muted',
                    )}
                    style={{ left: `${(left / total) * 100}%`, width: `${Math.max(0.5, ((right - left) / total) * 100)}%` }}
                  >
                    <span className="label truncate !text-[9px]">{section.level}</span>
                  </div>
                )
              })}
            </div>
          </div>
          <div className="flex flex-wrap gap-3 text-[10px] text-faint">
            <span>Selected track window: {musicAnalysis.selected_section}</span>
            <span>High energy · Medium energy · Low energy</span>
          </div>
        </div>
      )}
    </div>
  )
}


function Progress({ run }: { run: RunDetail }) {
  return (
    <Panel>
      <ol className="grid grid-cols-2 gap-px bg-line sm:grid-cols-4 lg:grid-cols-7">
        {run.stages.map((stage, i) => (
          <li key={stage.name} className="flex flex-col gap-3 bg-surface p-4">
            <span className="label text-faint">{String(i + 1).padStart(2, '0')}</span>
            <span className={cn('text-sm font-medium', stage.status === 'pending' && 'text-faint')}>{stage.label}</span>
            {stage.duration_seconds != null && stage.status !== 'pending' && (
              <span className="font-mono text-[11px] text-muted">{formatDuration(stage.duration_seconds)}</span>
            )}
            <span
              className={cn(
                'h-1.5 w-full',
                stage.status === 'done' && 'bg-ink',
                stage.status === 'running' && 'working',
                stage.status === 'failed' && 'bg-bad',
                stage.status === 'pending' && 'bg-line',
              )}
            />
          </li>
        ))}
      </ol>
      {(run.status === 'queued' || run.error || run.current_stage === 'transcribe') && (
        <div className="border-t border-line px-5 py-4 text-[13px]">
          {run.status === 'queued' && <p className="text-muted">Waiting in the queue. Runs are processed one at a time.</p>}
          {run.status === 'running' && run.current_stage === 'transcribe' && (
            <p className="text-muted">Transcribing locally. Time depends on video length, the Whisper model and your CPU.</p>
          )}
          {run.error && <p className="font-mono text-[12px] leading-relaxed text-bad">{run.error}</p>}
        </div>
      )}
    </Panel>
  )
}

/** The whole source as a strip, with every clip marked where it was cut from. */
function Timeline({ run, focused, onFocus }: { run: RunDetail; focused: number | null; onFocus: (rank: number | null) => void }) {
  const total = run.source_duration ?? 1
  const ticks = 6
  return (
    <div className="flex flex-col gap-2">
      <div className="label flex justify-between text-faint">
        <span>Where the clips came from</span>
        <span>
          {run.clips.length} clips · {formatDuration(total)} source
        </span>
      </div>
      <div className="relative h-12 border border-line bg-[repeating-linear-gradient(90deg,var(--color-sunk)_0_2px,transparent_2px_6px)]">
        {run.clips.map((clip) => (
          <button
            key={clip.id}
            type="button"
            onMouseEnter={() => onFocus(clip.rank)}
            onMouseLeave={() => onFocus(null)}
            onClick={() => document.getElementById(`clip-${clip.rank}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
            title={`#${clip.rank} ${clip.title}`}
            className={cn(
              'absolute inset-y-1 flex min-w-6 cursor-pointer items-center justify-center font-mono text-[11px] font-semibold transition-colors',
              focused === clip.rank ? 'bg-ink text-acid' : 'bg-acid text-ink',
            )}
            style={{ left: `${(clip.start_seconds / total) * 100}%`, width: `${((clip.end_seconds - clip.start_seconds) / total) * 100}%` }}
          >
            {clip.rank}
          </button>
        ))}
      </div>
      <div className="label flex justify-between text-faint">
        {Array.from({ length: ticks + 1 }, (_, i) => (
          <span key={i}>{formatDuration((total / ticks) * i)}</span>
        ))}
      </div>
    </div>
  )
}

function ClipCard({
  clip,
  posts,
  canPublish,
  onPublish,
  focused,
  onHover,
}: {
  clip: Clip
  posts: Post[]
  canPublish: boolean
  onPublish: () => void
  focused: boolean
  onHover: (rank: number | null) => void
}) {
  const [why, setWhy] = useState(false)
  const caption = `${clip.caption}\n\n${clip.hashtags.join(' ')}`.trim()
  return (
    <article
      id={`clip-${clip.rank}`}
      onMouseEnter={() => onHover(clip.rank)}
      onMouseLeave={() => onHover(null)}
      className={cn('flex flex-col border bg-surface transition-colors', focused ? 'border-ink' : 'border-line')}
    >
      <div className="relative bg-ink">
        {clip.status === 'ready' ? (
          <video src={clip.video_url} poster={clip.poster_url} controls preload="none" className="aspect-[9/16] max-h-[540px] w-full object-contain" />
        ) : (
          <div className="flex aspect-[9/16] max-h-[540px] items-center justify-center p-8 text-center font-mono text-[12px] text-bad">
            {clip.error ?? 'This clip failed to render'}
          </div>
        )}
        <span className="px-sm pointer-events-none absolute left-3 top-3 bg-acid px-2 py-1 font-mono text-[12px] font-bold text-ink">#{clip.rank}</span>
        <span className="label px-sm pointer-events-none absolute right-3 top-3 bg-ink/80 px-2 py-1 text-white">
          {formatDuration(clip.duration_seconds ?? clip.end_seconds - clip.start_seconds)}
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-4 p-5">
        <div className="flex flex-col gap-2">
          <h3 className="text-[17px] font-semibold leading-snug tracking-tight">{clip.title}</h3>
          <div className="label flex items-center gap-3 text-faint">
            {clip.score != null && (
              <span className="flex items-center gap-2">
                <Squares total={10} filled={Math.round(clip.score)} size="h-1.5 w-1.5" />
                <span className="text-ink">{clip.score.toFixed(1)}</span>
              </span>
            )}
            <span>
              {formatDuration(clip.start_seconds)} → {formatDuration(clip.end_seconds)}
            </span>
            {Boolean(clip.filler_words_removed) && (
              <span className="text-ok">
                {clip.filler_words_removed} filler {clip.filler_words_removed === 1 ? 'word' : 'words'} removed
              </span>
            )}
          </div>
        </div>

        {clip.rationale && (
          <button type="button" onClick={() => setWhy(!why)} className="flex cursor-pointer items-start gap-1.5 text-left text-[13px] text-muted hover:text-ink">
            <ChevronDown className={cn('mt-0.5 h-3.5 w-3.5 shrink-0 transition-transform', why && 'rotate-180')} />
            {why ? clip.rationale : 'Why this clip'}
          </button>
        )}

        <CopyBlock label="Title" text={clip.post_title} />
        <CopyBlock label="Caption" text={caption} />

        {posts.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {posts.map((p) => (
              <span
                key={p.id}
                title={p.error ?? undefined}
                className={cn('label px-sm px-2 py-1 !text-[10px]', p.status === 'failed' ? 'bg-bad-soft text-bad' : 'bg-sunk text-ink')}
              >
                {p.channel_name ?? p.service} · {p.status === 'failed' ? 'failed' : p.mode}
              </span>
            ))}
          </div>
        )}

        {clip.status === 'ready' && (
          <div className="mt-auto flex gap-2 pt-1">
            <a href={clip.download_url} className="flex-1">
              <Button variant="ink" className="w-full">
                <Download className="h-4 w-4" /> Download
              </Button>
            </a>
            {canPublish && (
              <Button variant="line" onClick={onPublish} className="flex-1">
                <Send className="h-4 w-4" /> Post
              </Button>
            )}
          </div>
        )}
      </div>
    </article>
  )
}

function CopyBlock({ label, text }: { label: string; text: string }) {
  const [copied, setCopied] = useState(false)
  if (!text) return null
  return (
    <div className="group relative border-l-2 border-line bg-paper py-2.5 pl-3 pr-9 text-[13px] leading-relaxed transition-colors hover:border-ink">
      <span className="label mb-1 block !text-[10px] text-faint">{label}</span>
      <p className="whitespace-pre-line text-body">{text}</p>
      <button
        className="absolute right-2 top-2 cursor-pointer p-1 text-faint hover:text-ink"
        aria-label={`Copy ${label.toLowerCase()}`}
        onClick={() => {
          navigator.clipboard.writeText(text)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        }}
      >
        {copied ? <Check className="h-4 w-4 text-ok" /> : <Copy className="h-4 w-4" />}
      </button>
    </div>
  )
}


function CampaignPlanCard({ plan, checks }: { plan: NonNullable<RunDetail['campaign_plan']>; checks: RunDetail['campaign_quality_checks'] }) {
  const labels: Record<string, string> = {
    campaign_name: 'Campaign',
    generated_hook: 'Suggested opening hook',
    platform: 'Platform',
    content_type: 'Content type',
    subject_or_theme: 'Subject / theme',
    source_requirements: 'Source requirements',
    reference_urls: 'Reference URLs (not auto-opened)',
    mood: 'Mood',
    language: 'Language',
    output_count: 'Output count',
    target_duration_seconds: 'Target duration',
    aspect_ratio: 'Aspect ratio',
    audio_mode: 'Audio mode',
    track_or_sound: 'Track / sound',
    official_platform_sound_required: 'Official platform sound required',
    on_screen_text_requirements: 'On-screen text',
    mandatory_content: 'Must include',
    prohibited_content: 'Must avoid',
    visual_style_and_pacing: 'Visual style & pacing',
    post_upload_actions: 'After upload (manual actions)',
    performance_eligibility: 'Performance requirements (after publishing)',
    payout_or_submission_caps: 'Payout / submission caps',
    rights_or_permissions_to_confirm: 'Rights / permissions to confirm',
    campaign_asset_discovery: 'Automatic footage discovery',
    discovered_assets: 'Discovered stock footage credits',
    unresolved_questions: 'Unresolved questions',
  }
  const entries = Object.entries(labels).filter(([key]) => {
    const value = plan[key]
    return value !== null && value !== undefined && value !== '' && (!Array.isArray(value) || value.length > 0)
  })
  if (!entries.length && !checks) return null
  return (
    <Panel className="flex flex-col gap-4 p-5">
      <div>
        <Eyebrow>Campaign intelligence</Eyebrow>
        <h2 className="display mt-1 text-2xl">What the AI understood</h2>
        <p className="mt-1 text-[13px] text-muted">Extracted from your brief. Unknown details are left blank rather than guessed.</p>
      </div>
      <dl className="grid gap-3 sm:grid-cols-2">
        {entries.map(([key, label]) => {
          const value = plan[key]
          return (
            <div key={key} className="border-t border-line pt-2">
              <dt className="label text-muted">{label}</dt>
              <dd className="mt-1 whitespace-pre-wrap text-sm">
                {Array.isArray(value) ? value.join(' · ') : typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value)}
              </dd>
            </div>
          )
        })}
      </dl>
      {checks && (
        <div className="border-t border-line pt-3">
          <h3 className="label mb-3">Export checks</h3>
          <dl className="grid gap-3 sm:grid-cols-2">
            {Object.entries(checks).map(([key, value]) => (
              <div key={key}>
                <dt className="label text-muted">{key.replaceAll('_', ' ')}</dt>
                <dd className="mt-1 text-sm">
                  {key === 'lyrics_overlay' && value === false
                    ? 'Not added — no lyric lines were available or configured.'
                    : key === 'music_track_added' && value === true
                      ? 'Yes — attached local track is mixed into the export.'
                      : typeof value === 'boolean'
                        ? (value ? 'Yes' : 'No')
                        : typeof value === 'object' && value !== null
                          ? Object.entries(value).map(([name, detail]) => `${name.replaceAll('_', ' ')}: ${detail}`).join(' · ')
                          : String(value)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </Panel>
  )
}
