import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, ArrowUpRight, Check, ChevronDown, Copy, Download, RotateCcw, Scissors, Send, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useUndoRedo } from '../hooks/useUndoRedo'
import { toast } from 'sonner'
import { api, type CampaignEdit, type CampaignTextOverlay, type CampaignMusicAnalysis, type CampaignLyricPhraseEdit, type CampaignShot, type CampaignSource, type Clip, type Post, type RunDetail } from '../api'
import { PublishDialog } from '../components/PublishDialog'
import { Button, Eyebrow, Panel, Squares, StatusChip, cn, formatDuration, sourceHost, sourceLabel, timeAgo } from '../components/ui'
type CampaignPreviewLyric = {
  text: string
  start_seconds: number
  end_seconds: number
  position_x: number
  position_y: number
  scale_percent: number
  rotation_degrees: number
}


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
  const [musicVolume, setMusicVolume] = useState(90)
  const [musicFadeIn, setMusicFadeIn] = useState(0.4)
  const [musicFadeOut, setMusicFadeOut] = useState(0.8)
  const [lyricsText, setLyricsText] = useState('')
  const [lyricsStyle, setLyricsStyle] = useState<
    'dynamic' | 'cinematic' | 'minimal' | 'karaoke' | 'zoom' | 'bounce' | 'pulse' | 'glitch'
  >('dynamic')
  const [hookText, setHookText] = useState('')
  const [includeHook, setIncludeHook] = useState(false)
  const [lyricsColor, setLyricsColor] = useState('#FFFFFF')
  const [lyricsHighlightColor, setLyricsHighlightColor] = useState('#00D7FF')
  const [lyricsWordsOnScreen, setLyricsWordsOnScreen] = useState<1 | 2 | 3>(3)
  const [lyricsBehindSubject, setLyricsBehindSubject] = useState(false)
  const [lyricsPositionX, setLyricsPositionX] = useState(50)
  const [lyricsPositionY, setLyricsPositionY] = useState(84)
  const [lyricsScale, setLyricsScale] = useState(100)
  const [lyricsRotation, setLyricsRotation] = useState(0)
  const [phraseEdits, setPhraseEdits] = useState<CampaignLyricPhraseEdit[]>([])
  const [selectedLyricPhrase, setSelectedLyricPhrase] = useState(0)
  const campaignHistory = useUndoRedo({
    edits: [] as CampaignEdit[],
    overlays: [] as CampaignTextOverlay[],
  })
  const {
    value: campaignHistoryValue,
    set: setCampaignHistory,
    reset: resetCampaignHistory,
    undo: undoCampaignEdits,
    redo: redoCampaignEdits,
    canUndo: canUndoCampaignEdits,
    canRedo: canRedoCampaignEdits,
  } = campaignHistory
  const campaignEdits = campaignHistoryValue.edits
  const campaignTextOverlays = campaignHistoryValue.overlays
  const setCampaignEdits = useCallback((next: CampaignEdit[] | ((current: CampaignEdit[]) => CampaignEdit[])) => {
    setCampaignHistory((current) => ({
      ...current,
      edits: typeof next === 'function' ? next(current.edits) : next,
    }))
  }, [setCampaignHistory])
  const setCampaignTextOverlays = useCallback((next: CampaignTextOverlay[] | ((current: CampaignTextOverlay[]) => CampaignTextOverlay[])) => {
    setCampaignHistory((current) => ({
      ...current,
      overlays: typeof next === 'function' ? next(current.overlays) : next,
    }))
  }, [setCampaignHistory])
  useEffect(() => {
    setMusicVolume(Math.round((run.data?.options.campaign_music_volume ?? 0.9) * 100))
    setMusicFadeIn(run.data?.options.campaign_music_fade_in_seconds ?? 0.4)
    setMusicFadeOut(run.data?.options.campaign_music_fade_out_seconds ?? 0.8)
    setLyricsText(run.data?.options.campaign_lyrics ?? '')
    setLyricsStyle(run.data?.options.campaign_lyrics_style ?? 'dynamic')
    setHookText(run.data?.options.campaign_hook_text ?? String(run.data?.campaign_plan?.generated_hook ?? ''))
    setIncludeHook(Boolean(run.data?.options.include_campaign_hook))
    setLyricsColor(run.data?.options.campaign_lyrics_color ?? '#FFFFFF')
    setLyricsHighlightColor(run.data?.options.campaign_lyrics_highlight_color ?? '#00D7FF')
    setLyricsWordsOnScreen(run.data?.options.campaign_lyrics_words_on_screen ?? 3)
    setLyricsBehindSubject(Boolean(run.data?.options.campaign_lyrics_behind_subject))
    setLyricsPositionX(run.data?.options.campaign_lyrics_position_x ?? 50)
    setLyricsPositionY(run.data?.options.campaign_lyrics_position_y ?? 84)
    setLyricsScale(run.data?.options.campaign_lyrics_scale_percent ?? 100)
    setLyricsRotation(run.data?.options.campaign_lyrics_rotation_degrees ?? 0)
    setPhraseEdits(run.data?.options.campaign_lyric_phrase_edits ?? [])
    setSelectedLyricPhrase(0)
    resetCampaignHistory({
      edits: run.data?.campaign_edits ?? [],
      overlays: run.data?.options.campaign_text_overlays ?? [],
    })
  }, [runId, run.data?.campaign_edits, run.data?.options.campaign_music_volume, run.data?.options.campaign_music_fade_in_seconds, run.data?.options.campaign_music_fade_out_seconds, run.data?.options.campaign_lyrics, run.data?.options.campaign_lyrics_style, run.data?.options.campaign_hook_text, run.data?.options.include_campaign_hook, run.data?.options.campaign_lyrics_color, run.data?.options.campaign_lyrics_highlight_color, run.data?.options.campaign_lyrics_words_on_screen, run.data?.options.campaign_lyrics_behind_subject, run.data?.options.campaign_lyrics_position_x, run.data?.options.campaign_lyrics_position_y, run.data?.options.campaign_lyrics_scale_percent, run.data?.options.campaign_lyrics_rotation_degrees, run.data?.options.campaign_lyric_phrase_edits, run.data?.options.campaign_text_overlays, run.data?.campaign_plan?.generated_hook, resetCampaignHistory])

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
  const saveCampaignAudio = useMutation({
    mutationFn: () => api.saveCampaignAudio(runId, musicVolume / 100, musicFadeIn, musicFadeOut),
    onSuccess: (result) => {
      toast.success(`Applied music mix to ${result.outputs} campaign edit(s).`)
      refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  const saveLyrics = useMutation({
    mutationFn: () => api.saveCampaignLyrics(runId, lyricsText, lyricsStyle, hookText, includeHook, lyricsColor, lyricsHighlightColor, lyricsWordsOnScreen, lyricsBehindSubject, lyricsPositionX, lyricsPositionY, lyricsScale, lyricsRotation, phraseEdits),
    onSuccess: (result) => {
      toast.success(`Applied to ${result.outputs} existing edit(s) — no re-picking or lyric transcription.`)
      refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  const lyricRows = lyricsText.split(/\r?\n/).map((line) => {
    const text = line.replace(/^\[\d{1,2}:\d{2}(?:\.\d{1,2})?\]\s*/, '').trim()
    const match = line.trim().match(/^\[(\d{1,2}):(\d{2})(?:\.(\d{1,2}))?\]/)
    const start = match
      ? Number(match[1]) * 60 + Number(match[2]) + Number((match[3] ?? '0').padEnd(2, '0').slice(0, 2)) / 100
      : null
    return { text, start }
  }).filter((phrase) => phrase.text)
  const lyricPhrases = lyricRows.map((phrase) => phrase.text)
  const lyricPhraseTimes = lyricRows.map((phrase) => phrase.start)
  const campaignTimelineLyrics: CampaignPreviewLyric[] = lyricRows.flatMap((phrase, index) => {
    if (phrase.start == null) return []
    const phraseEdit = phraseEdits.find((edit) => edit.phrase_index === index)
    const start = phraseEdit?.start_seconds ?? phrase.start
    const nextTimedStart = lyricRows.slice(index + 1).find((row) => row.start != null)?.start
    const end = phraseEdit?.end_seconds ?? nextTimedStart ?? start + 3
    if (end <= start) return []
    return [{
      text: phrase.text,
      start_seconds: start,
      end_seconds: end,
      position_x: phraseEdit?.position_x ?? lyricsPositionX,
      position_y: phraseEdit?.position_y ?? lyricsPositionY,
      scale_percent: phraseEdit?.scale_percent ?? lyricsScale,
      rotation_degrees: phraseEdit?.rotation_degrees ?? lyricsRotation,
    }]
  })
  const selectedPhraseEdit = phraseEdits.find((edit) => edit.phrase_index === selectedLyricPhrase)
  const selectedPhraseStart = selectedPhraseEdit?.start_seconds ?? lyricPhraseTimes[selectedLyricPhrase]
  const selectedPhraseEnd = selectedPhraseEdit?.end_seconds ?? (
    lyricPhraseTimes[selectedLyricPhrase + 1] ?? (selectedPhraseStart == null ? null : selectedPhraseStart + 3)
  )
  const previewPositionX = selectedPhraseEdit?.position_x ?? lyricsPositionX
  const previewPositionY = selectedPhraseEdit?.position_y ?? lyricsPositionY
  const previewScale = selectedPhraseEdit?.scale_percent ?? lyricsScale
  const previewRotation = selectedPhraseEdit?.rotation_degrees ?? lyricsRotation
  const updateSelectedPhrase = (patch: Partial<CampaignLyricPhraseEdit>) => {
    setPhraseEdits((current) => {
      const existing = current.find((edit) => edit.phrase_index === selectedLyricPhrase)
      const next = { phrase_index: selectedLyricPhrase, ...existing, ...patch }
      return [...current.filter((edit) => edit.phrase_index !== selectedLyricPhrase), next].sort((left, right) => left.phrase_index - right.phrase_index)
    })
  }
  const saveCampaignTextOverlays = useMutation({
    mutationFn: () => api.saveCampaignTextOverlays(runId, campaignTextOverlays),
    onSuccess: (result) => {
      toast.success(`Applied ${result.overlays} text overlay(s) to ${result.outputs} campaign edit(s).`)
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

  useEffect(() => {
    if (!run.data?.options.campaign_mode || ['queued', 'running'].includes(run.data.status)) return
    const handleEditorShortcut = (event: KeyboardEvent) => {
      if (!event.ctrlKey && !event.metaKey) return
      const target = event.target as HTMLElement | null
      if (target?.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName ?? '')) return
      const key = event.key.toLowerCase()
      if (key === 'z' && event.shiftKey) {
        if (!canRedoCampaignEdits) return
        event.preventDefault()
        redoCampaignEdits()
      } else if (key === 'z') {
        if (!canUndoCampaignEdits) return
        event.preventDefault()
        undoCampaignEdits()
      } else if (key === 'y') {
        if (!canRedoCampaignEdits) return
        event.preventDefault()
        redoCampaignEdits()
      }
    }
    window.addEventListener('keydown', handleEditorShortcut)
    return () => window.removeEventListener('keydown', handleEditorShortcut)
  }, [run.data?.options.campaign_mode, run.data?.status, canUndoCampaignEdits, canRedoCampaignEdits, undoCampaignEdits, redoCampaignEdits])

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
  const savedMusicVolume = Math.round((data.options.campaign_music_volume ?? 0.9) * 100)
  const savedMusicFadeIn = data.options.campaign_music_fade_in_seconds ?? 0.4
  const savedMusicFadeOut = data.options.campaign_music_fade_out_seconds ?? 0.8
  const musicSettingsChanged = musicVolume !== savedMusicVolume || musicFadeIn !== savedMusicFadeIn || musicFadeOut !== savedMusicFadeOut
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
          {data.options.campaign_music_path && (
            <div className="flex flex-col gap-4 rounded-lg border border-line bg-panel p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">Music mix</span>
                <span className="text-xs text-muted">Adjust the attached track, then re-render</span>
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                <label className="flex flex-col gap-2">
                  <span className="flex justify-between gap-2"><span className="font-medium">Music volume</span><span className="font-mono text-muted">{musicVolume}%</span></span>
                  <input type="range" min={0} max={200} step={5} value={musicVolume} onChange={(event) => setMusicVolume(Number(event.target.value))} className="w-full accent-current" />
                  <span className="text-xs text-muted">0% mute · 100% original level · 200% boost</span>
                </label>
                <label className="flex flex-col gap-2">
                  <span className="flex justify-between gap-2"><span className="font-medium">Fade in</span><span className="font-mono text-muted">{musicFadeIn.toFixed(1)}s</span></span>
                  <input type="range" min={0} max={5} step={0.1} value={musicFadeIn} onChange={(event) => setMusicFadeIn(Number(event.target.value))} className="w-full accent-current" />
                  <span className="text-xs text-muted">How quickly music reaches its set level</span>
                </label>
                <label className="flex flex-col gap-2">
                  <span className="flex justify-between gap-2"><span className="font-medium">Fade out</span><span className="font-mono text-muted">{musicFadeOut.toFixed(1)}s</span></span>
                  <input type="range" min={0} max={5} step={0.1} value={musicFadeOut} onChange={(event) => setMusicFadeOut(Number(event.target.value))} className="w-full accent-current" />
                  <span className="text-xs text-muted">How quickly music fades at the end</span>
                </label>
              </div>
              <div className="flex justify-end">
                <Button variant="ink" disabled={!musicSettingsChanged || saveCampaignAudio.isPending} loading={saveCampaignAudio.isPending} onClick={() => saveCampaignAudio.mutate()}>
                  Apply music mix &amp; re-render
                </Button>
              </div>
            </div>
          )}
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
          <LyricsPositionPreview
            frameUrl={campaignEdits[0]?.shots[0] ? `/api/runs/${runId}/campaign-frame?source_index=${campaignEdits[0].shots[0].source_index}&timestamp=${campaignEdits[0].shots[0].start_seconds.toFixed(1)}` : null}
            text={lyricPhrases[selectedLyricPhrase] ?? 'Your lyrics appear here'}
            x={previewPositionX}
            y={previewPositionY}
            scale={previewScale}
            rotation={previewRotation}
            aspectRatio={data.options.aspect_ratio}
            onPositionChange={(x, y) => lyricPhrases.length ? updateSelectedPhrase({ position_x: x, position_y: y }) : (setLyricsPositionX(x), setLyricsPositionY(y))}
          />
          {lyricPhrases.length > 0 && (
            <div className="flex flex-col gap-3 rounded-lg border border-line bg-panel p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">Individual lyric phrase</span>
                <span className="text-xs text-muted">Overrides only the selected phrase</span>
              </div>
              <label className="flex flex-col gap-2">
                <span className="text-xs text-muted">Select phrase</span>
                <select value={selectedLyricPhrase} onChange={(event) => setSelectedLyricPhrase(Number(event.target.value))}
                  className="rounded-lg border border-line bg-panel p-2 text-ink">
                  {lyricPhrases.map((phrase, index) => <option key={index} value={index}>{index + 1}. {phrase.slice(0, 70)}</option>)}
                </select>
              </label>
              {selectedPhraseStart != null && selectedPhraseEnd != null && (
                <div className="grid gap-3 border-t border-line pt-3 sm:grid-cols-2">
                  <label className="flex flex-col gap-1">
                    <span className="font-medium">Phrase start (song seconds)</span>
                    <input type="number" min={0} step={0.05} value={selectedPhraseStart}
                      onChange={(event) => {
                        const start = Math.max(0, Number(event.target.value))
                        updateSelectedPhrase({ start_seconds: start, ...(selectedPhraseEnd <= start ? { end_seconds: start + 0.2 } : {}) })
                      }}
                      className="rounded-lg border border-line bg-panel p-2 text-ink" />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="font-medium">Phrase end (song seconds)</span>
                    <input type="number" min={selectedPhraseStart + 0.05} step={0.05} value={selectedPhraseEnd}
                      onChange={(event) => updateSelectedPhrase({ end_seconds: Math.max(selectedPhraseStart + 0.05, Number(event.target.value)) })}
                      className="rounded-lg border border-line bg-panel p-2 text-ink" />
                  </label>
                  <p className="text-xs text-muted sm:col-span-2">Times are measured against the original song, so changing this phrase does not move the following phrases.</p>
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                {([
                  ['position_x', 'Horizontal position', 5, 95, lyricsPositionX, '%'],
                  ['position_y', 'Vertical position', 5, 95, lyricsPositionY, '%'],
                  ['scale_percent', 'Text size', 50, 200, lyricsScale, '%'],
                  ['rotation_degrees', 'Rotation', -30, 30, lyricsRotation, '°'],
                ] as const).map(([key, label, min, max, fallback, suffix]) => {
                  const value = selectedPhraseEdit?.[key] ?? fallback
                  return (
                    <label key={key} className="flex flex-col gap-2">
                      <span className="flex justify-between"><span>{label}</span><span className="font-mono text-muted">{value}{suffix}</span></span>
                      <input type="range" min={min} max={max} step={key === 'scale_percent' ? 5 : 1} value={value}
                        onChange={(event) => updateSelectedPhrase({ [key]: Number(event.target.value) })}
                        className="w-full accent-current" />
                    </label>
                  )
                })}
              </div>
              <label className="flex flex-col gap-2">
                <span className="text-xs text-muted">Animation style</span>
                <select
                  value={selectedPhraseEdit?.animation_style ?? 'global'}
                  onChange={(event) => updateSelectedPhrase({ animation_style: event.target.value === 'global' ? undefined : event.target.value as CampaignLyricPhraseEdit['animation_style'] })}
                  className="rounded-lg border border-line bg-panel p-2 text-ink"
                >
                  <option value="global">Use global style</option>
                  <option value="dynamic">Dynamic pop</option>
                  <option value="cinematic">Cinematic fade</option>
                  <option value="minimal">Minimal fade</option>
                  <option value="karaoke">Karaoke highlight</option>
                </select>
              </label>
              <div className="flex justify-end">
                <button type="button" className="text-xs underline text-muted"
                  onClick={() => setPhraseEdits((current) => current.filter((edit) => edit.phrase_index !== selectedLyricPhrase))}>
                  Reset this phrase to global settings
                </button>
              </div>
              <p className="text-xs text-muted">Phrase-level transforms currently apply to line-timed lyrics (LRC or manually entered lines). Word-by-word Whisper timing continues to use the global lyric transform.</p>
            </div>
          )}
          <div className="grid gap-4 rounded-lg border border-line bg-panel p-3 text-sm sm:grid-cols-2">
            <label className="flex flex-col gap-2">
              <span className="flex justify-between"><span className="font-medium">Horizontal position</span><span className="font-mono text-muted">{lyricsPositionX}%</span></span>
              <input type="range" min={5} max={95} value={lyricsPositionX} onChange={(event) => setLyricsPositionX(Number(event.target.value))} className="w-full accent-current" />
            </label>
            <label className="flex flex-col gap-2">
              <span className="flex justify-between"><span className="font-medium">Vertical position</span><span className="font-mono text-muted">{lyricsPositionY}%</span></span>
              <input type="range" min={5} max={95} value={lyricsPositionY} onChange={(event) => setLyricsPositionY(Number(event.target.value))} className="w-full accent-current" />
            </label>
            <label className="flex flex-col gap-2">
              <span className="flex justify-between"><span className="font-medium">Text size</span><span className="font-mono text-muted">{lyricsScale}%</span></span>
              <input type="range" min={50} max={200} step={5} value={lyricsScale} onChange={(event) => setLyricsScale(Number(event.target.value))} className="w-full accent-current" />
            </label>
            <label className="flex flex-col gap-2">
              <span className="flex justify-between"><span className="font-medium">Rotation</span><span className="font-mono text-muted">{lyricsRotation}°</span></span>
              <input type="range" min={-30} max={30} value={lyricsRotation} onChange={(event) => setLyricsRotation(Number(event.target.value))} className="w-full accent-current" />
            </label>
            <p className="text-xs text-muted sm:col-span-2">These controls position, resize and rotate the complete timed lyric layer. Defaults preserve the existing lower-center layout. Changes are applied when you re-render.</p>
          </div>
          <label className="flex items-start gap-3 rounded-lg border border-line bg-panel p-3 text-sm">
            <input
              type="checkbox"
              checked={lyricsBehindSubject}
              onChange={(event) => setLyricsBehindSubject(event.target.checked)}
              className="mt-1 h-4 w-4 accent-current"
            />
            <span className="flex flex-col gap-1">
              <span className="font-medium">Place lyrics behind the person (AI depth effect)</span>
              <span className="text-xs text-muted">
                Uses AI person segmentation to keep the foreground subject in front of the words.
                This takes extra processing time. If segmentation is unavailable, CLIPYYY safely uses normal lyrics.
              </span>
            </span>
          </label>
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
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-panel px-4 py-3">
          <div>
            <span className="label text-muted">Campaign edit history</span>
            <p className="mt-1 text-xs text-faint">Undo or redo shot edits and independent text overlays together · Ctrl+Z to undo · Ctrl+Shift+Z or Ctrl+Y to redo.</p>
          </div>
          <div className="flex gap-2">
            <Button variant="line" disabled={!canUndoCampaignEdits} onClick={undoCampaignEdits}>Undo</Button>
            <Button variant="line" disabled={!canRedoCampaignEdits} onClick={redoCampaignEdits}>Redo</Button>
          </div>
        </div>
      )}

      {data.options.campaign_mode && !busy && campaignEdits.length > 0 && (
        <CampaignStoryboardEditor
          runId={runId}
          edits={campaignEdits}
          savedEdits={data.campaign_edits}
          originalEdits={data.campaign_original_edits ?? data.campaign_edits}
          sources={data.campaign_sources ?? []}
          musicAnalysis={data.campaign_quality_checks?.music_analysis ?? null}
          hasMusic={Boolean(data.options.campaign_music_path)}
          lyrics={campaignTimelineLyrics}
          lyricsColor={lyricsColor}
          lyricsHighlightColor={lyricsHighlightColor}
          textOverlays={campaignTextOverlays}
          onUpdateTextOverlay={(overlayIndex, patch) => setCampaignTextOverlays((current) => current.map((overlay, index) => index === overlayIndex ? { ...overlay, ...patch } : overlay))}
          transitionStyle={data.options.campaign_transition_style ?? 'auto'}
          saving={saveMontage.isPending}
          onChange={setCampaignEdits}
          onSave={() => saveMontage.mutate()}
          onReset={() => setCampaignEdits(data.campaign_original_edits ?? data.campaign_edits)}
        />
      )}

      {data.options.campaign_mode && !busy && campaignEdits.length > 0 && (
        <CampaignTextOverlayEditor
          overlays={campaignTextOverlays}
          savedOverlays={data.options.campaign_text_overlays ?? []}
          outputs={readyClips.map((clip) => ({ rank: clip.rank, duration_seconds: clip.duration_seconds ?? 0, poster_url: clip.poster_url }))}
          saving={saveCampaignTextOverlays.isPending}
          onChange={setCampaignTextOverlays}
          onSave={() => saveCampaignTextOverlays.mutate()}
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
  hasMusic,
  lyrics,
  lyricsColor,
  lyricsHighlightColor,
  textOverlays,
  onUpdateTextOverlay,
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
  hasMusic: boolean
  lyrics: CampaignPreviewLyric[]
  lyricsColor: string
  lyricsHighlightColor: string
  textOverlays: CampaignTextOverlay[]
  onUpdateTextOverlay: (overlayIndex: number, patch: Partial<CampaignTextOverlay>) => void
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
  const moveShotTo = (editIndex: number, fromIndex: number, toIndex: number) => {
    onChange(edits.map((edit, index) => {
      if (index !== editIndex || fromIndex === toIndex) return edit
      if (fromIndex < 0 || toIndex < 0 || fromIndex >= edit.shots.length || toIndex >= edit.shots.length) return edit
      const shots = [...edit.shots]
      const [moved] = shots.splice(fromIndex, 1)
      shots.splice(toIndex, 0, moved)
      return { ...edit, shots }
    }))
  }
  const moveShot = (editIndex: number, shotIndex: number, direction: -1 | 1) => {
    moveShotTo(editIndex, shotIndex, shotIndex + direction)
  }
  const removeShot = (editIndex: number, shotIndex: number) => {
    onChange(edits.map((edit, index) => index !== editIndex ? edit : {
      ...edit,
      shots: edit.shots.filter((_, position) => position !== shotIndex),
    }))
  }
  const splitShot = (editIndex: number, shotIndex: number) => {
    onChange(edits.map((edit, index) => {
      if (index !== editIndex || edit.shots.length >= 40) return edit
      const shot = edit.shots[shotIndex]
      if (!shot || shot.end_seconds - shot.start_seconds < 3) return edit
      const midpoint = Math.round(((shot.start_seconds + shot.end_seconds) / 2) * 1000) / 1000
      const first = { ...shot, end_seconds: midpoint }
      const second = { ...shot, start_seconds: midpoint }
      return {
        ...edit,
        shots: [...edit.shots.slice(0, shotIndex), first, second, ...edit.shots.slice(shotIndex + 1)],
      }
    }))
  }

  return (
    <Panel className="flex flex-col gap-5 p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Eyebrow>Campaign editor</Eyebrow>
          <h2 className="display mt-1 text-2xl">Edit your storyboard</h2>
          <p className="mt-1 text-[13px] text-muted">
            Reorder, trim, split or remove shots. Splitting keeps the original source range and creates two consecutive shots.
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
            hasMusic={hasMusic}
            lyrics={lyrics}
            lyricsColor={lyricsColor}
            lyricsHighlightColor={lyricsHighlightColor}
            textOverlays={textOverlays}
            onUpdateTextOverlay={onUpdateTextOverlay}
            transitionStyle={transitionStyle}
            onMoveShot={(fromIndex, toIndex) => moveShotTo(editIndex, fromIndex, toIndex)}
            onUpdateShot={(shotIndex, patch) => updateShot(editIndex, shotIndex, patch)}
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
                    <button type="button" title="Split shot in half" aria-label="Split shot in half"
                      disabled={saving || edit.shots.length >= 40 || shot.end_seconds - shot.start_seconds < 3}
                      onClick={() => splitShot(editIndex, shotIndex)} className="rounded-md border border-line p-2 text-muted hover:text-ink disabled:opacity-30">
                      <Scissors className="h-4 w-4" />
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

function CampaignTextOverlayEditor({
  overlays,
  savedOverlays,
  outputs,
  saving,
  onChange,
  onSave,
}: {
  overlays: CampaignTextOverlay[]
  savedOverlays: CampaignTextOverlay[]
  outputs: { rank: number; duration_seconds: number; poster_url?: string }[]
  saving: boolean
  onChange: (overlays: CampaignTextOverlay[]) => void
  onSave: () => void
}) {
  const changed = JSON.stringify(overlays) !== JSON.stringify(savedOverlays)
  const addOverlay = () => {
    const output = outputs[0]
    if (!output || output.duration_seconds < 0.2 || overlays.length >= 30) return
    onChange([
      ...overlays,
      {
        rank: output.rank,
        text: 'YOUR MESSAGE',
        start_seconds: 0,
        end_seconds: Math.min(2.5, output.duration_seconds),
        position_x: 50,
        position_y: 50,
        font_size_percent: 100,
        color: '#FFFFFF',
        animation: 'fade',
        background: true,
      },
    ])
  }
  const update = (index: number, patch: Partial<CampaignTextOverlay>) => {
    onChange(overlays.map((overlay, position) => position === index ? { ...overlay, ...patch } : overlay))
  }

  return (
    <Panel className="flex flex-col gap-4 p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Eyebrow>Independent text layers</Eyebrow>
          <h2 className="display mt-1 text-2xl">Add campaign titles &amp; messages</h2>
          <p className="mt-1 text-[13px] text-muted">
            Add timed titles, calls to action or labels separately from the song lyrics. Each layer has its own output, timing, position and style.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="line" disabled={saving || overlays.length >= 30 || outputs.length === 0} onClick={addOverlay}>
            Add text layer
          </Button>
          <Button variant="ink" disabled={!changed || saving} loading={saving} onClick={onSave}>
            Save &amp; re-render
          </Button>
        </div>
      </div>
      {overlays.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line p-5 text-sm text-muted">
          No extra text layers yet. Add a campaign title, product name, offer or call to action without changing the timed lyric captions.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {overlays.map((overlay, index) => {
            const output = outputs.find((item) => item.rank === overlay.rank)
            return (
              <section key={index} className="flex flex-col gap-3 rounded-lg border border-line bg-panel p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="label text-muted">TEXT LAYER {String(index + 1).padStart(2, '0')}</span>
                  <button type="button" disabled={saving} onClick={() => onChange(overlays.filter((_, position) => position !== index))}
                    className="rounded-md border border-line px-3 py-1.5 text-xs text-muted hover:text-bad disabled:opacity-40">
                    Remove
                  </button>
                </div>
                <label className="flex flex-col gap-1 text-xs text-muted">
                  Message
                  <textarea maxLength={160} rows={2} value={overlay.text}
                    onChange={(event) => update(index, { text: event.target.value })}
                    className="w-full resize-y rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink" />
                </label>
                <div className="flex flex-wrap items-center gap-4 rounded-lg border border-line bg-surface p-3">
                  <div className="w-full max-w-[210px]">
                    <div
                      className="relative mx-auto aspect-[9/16] w-full touch-none select-none overflow-hidden rounded-lg border border-white/15 bg-gradient-to-br from-slate-800 via-slate-950 to-black shadow-lg"
                      onPointerDown={(event: ReactPointerEvent<HTMLDivElement>) => {
                        event.preventDefault()
                        event.currentTarget.setPointerCapture(event.pointerId)
                        const bounds = event.currentTarget.getBoundingClientRect()
                        update(index, {
                          position_x: Math.max(5, Math.min(95, Math.round(((event.clientX - bounds.left) / bounds.width) * 100))),
                          position_y: Math.max(5, Math.min(95, Math.round(((event.clientY - bounds.top) / bounds.height) * 100))),
                        })
                      }}
                      onPointerMove={(event: ReactPointerEvent<HTMLDivElement>) => {
                        if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
                        const bounds = event.currentTarget.getBoundingClientRect()
                        update(index, {
                          position_x: Math.max(5, Math.min(95, Math.round(((event.clientX - bounds.left) / bounds.width) * 100))),
                          position_y: Math.max(5, Math.min(95, Math.round(((event.clientY - bounds.top) / bounds.height) * 100))),
                        })
                      }}
                      onPointerUp={(event: ReactPointerEvent<HTMLDivElement>) => {
                        if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
                      }}
                      onPointerCancel={(event: ReactPointerEvent<HTMLDivElement>) => {
                        if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
                      }}
                      aria-label="Drag the text overlay to change its position"
                    >
                      {output?.poster_url && (
                        <img src={output.poster_url} alt="" draggable={false} className="absolute inset-0 h-full w-full object-cover" />
                      )}
                      <div className="absolute inset-0 bg-gradient-to-t from-black/45 via-black/10 to-black/25" />
                      <div className="absolute left-2 top-2 rounded bg-black/55 px-2 py-1 text-[9px] font-semibold tracking-widest text-white/80">
                        POSITION PREVIEW
                      </div>
                      <div
                        className="pointer-events-none absolute max-w-[84%] -translate-x-1/2 -translate-y-1/2 whitespace-pre-wrap break-words rounded-md px-2 py-1 text-center font-bold leading-tight shadow-lg"
                        style={{
                          left: String(overlay.position_x) + "%",
                          top: String(overlay.position_y) + "%",
                          color: overlay.color,
                          fontSize: String(Math.max(12, 15 * overlay.font_size_percent / 100)) + "px",
                          backgroundColor: overlay.background ? "rgba(0,0,0,0.62)" : "transparent",
                          textShadow: overlay.background ? "none" : "0 2px 8px rgba(0,0,0,0.9)",
                        }}
                      >
                        {overlay.text || 'YOUR MESSAGE'}
                      </div>
                    </div>
                    <p className="mt-2 text-center text-[10px] text-muted">Drag the text to position it · 9:16 preview</p>
                  </div>
                  <div className="min-w-[180px] flex-1 text-xs text-muted">
                    <p className="font-semibold text-ink">Direct positioning</p>
                    <p className="mt-1">Move the message inside the frame. The X/Y controls below update immediately and stay in sync with this preview.</p>
                    <p className="mt-2 font-mono tabular-nums">X {overlay.position_x}% · Y {overlay.position_y}%</p>
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Output
                    <select value={overlay.rank} onChange={(event) => update(index, { rank: Number(event.target.value) })}
                      className="rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
                      {outputs.map((item) => <option key={item.rank} value={item.rank}>Edit #{item.rank}</option>)}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Starts (seconds)
                    <input type="number" min={0} max={output?.duration_seconds ?? 0} step={0.1} value={overlay.start_seconds}
                      onChange={(event) => update(index, { start_seconds: Number(event.target.value) })}
                      className="rounded-md border border-line bg-surface px-2 py-2 font-mono text-sm text-ink" />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Ends (seconds)
                    <input type="number" min={0.1} max={output?.duration_seconds ?? 0} step={0.1} value={overlay.end_seconds}
                      onChange={(event) => update(index, { end_seconds: Number(event.target.value) })}
                      className="rounded-md border border-line bg-surface px-2 py-2 font-mono text-sm text-ink" />
                  </label>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Horizontal position · {overlay.position_x}%
                    <input type="range" min={5} max={95} value={overlay.position_x}
                      onChange={(event) => update(index, { position_x: Number(event.target.value) })} />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Vertical position · {overlay.position_y}%
                    <input type="range" min={5} max={95} value={overlay.position_y}
                      onChange={(event) => update(index, { position_y: Number(event.target.value) })} />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Text size · {overlay.font_size_percent}%
                    <input type="range" min={60} max={200} step={5} value={overlay.font_size_percent}
                      onChange={(event) => update(index, { font_size_percent: Number(event.target.value) })} />
                  </label>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <label className="flex items-center justify-between gap-3 text-xs text-muted">
                    Text color
                    <input type="color" value={overlay.color} onChange={(event) => update(index, { color: event.target.value.toUpperCase() })}
                      className="h-9 w-12 cursor-pointer rounded border border-line bg-transparent p-1" />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Entrance animation
                    <select value={overlay.animation} onChange={(event) => update(index, { animation: event.target.value as CampaignTextOverlay['animation'] })}
                      className="rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
                      <option value="none">None</option>
                      <option value="fade">Fade</option>
                      <option value="pop">Pop</option>
                      <option value="slide">Slide up</option>
                    </select>
                  </label>
                  <label className="flex items-center gap-2 text-xs text-muted">
                    <input type="checkbox" checked={overlay.background}
                      onChange={(event) => update(index, { background: event.target.checked })} />
                    Background panel
                  </label>
                </div>
                <p className="text-[11px] text-muted">
                  This is a separate text layer. It does not replace or retime the music lyrics.
                </p>
              </section>
            )
          })}
        </div>
      )}
    </Panel>
  )
}

function CampaignTimeline({
  edit,
  runId,
  sources,
  musicAnalysis,
  hasMusic,
  lyrics,
  lyricsColor,
  lyricsHighlightColor,
  textOverlays,
  onUpdateTextOverlay,
  onMoveShot,
  onUpdateShot,
}: {
  edit: CampaignEdit
  runId: string
  sources: CampaignSource[]
  musicAnalysis: CampaignMusicAnalysis | null
  hasMusic: boolean
  lyrics: CampaignPreviewLyric[]
  lyricsColor: string
  lyricsHighlightColor: string
  textOverlays: CampaignTextOverlay[]
  onUpdateTextOverlay: (overlayIndex: number, patch: Partial<CampaignTextOverlay>) => void
  transitionStyle: 'auto' | 'cut' | 'cinematic' | 'dynamic'
  onMoveShot: (fromIndex: number, toIndex: number) => void
  onUpdateShot: (shotIndex: number, patch: Partial<CampaignShot>) => void
}) {
  const [previewShotIndex, setPreviewShotIndex] = useState(0)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const advancingShotRef = useRef(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [playheadSeconds, setPlayheadSeconds] = useState(0)
  const [activeOverlayTrim, setActiveOverlayTrim] = useState<{
    pointerId: number
    overlayIndex: number
    side: 'move' | 'start' | 'end'
    startX: number
    initialStart: number
    initialEnd: number
    trackWidth: number
    initialTotal: number
  } | null>(null)
  const [activeTrim, setActiveTrim] = useState<{
    pointerId: number
    shotIndex: number
    side: 'start' | 'end'
    startX: number
    initialStart: number
    initialEnd: number
    trackWidth: number
    initialTotal: number
  } | null>(null)
  const sourceByIndex = new Map(sources.map((source) => [source.index, source]))
  const shots = edit.shots.map((shot, index) => ({
    shot,
    index,
    // Preview playback uses hard cuts; transition overlap is not composited in this player.
    duration: Math.max(0.1, shot.end_seconds - shot.start_seconds),
  }))
  const total = Math.max(0.1, shots.reduce((sum, item) => sum + item.duration, 0))
  const musicStart = musicAnalysis?.selected_start_seconds ?? 0

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-line bg-panel p-3">
      <div className="flex items-center justify-between gap-3">
        <span className="label text-muted">Video timeline · drag shots to reorder</span>
        <span className="font-mono text-[11px] text-faint">{formatDuration(total)} estimated</span>
      </div>
      {shots.length > 0 && (() => {
        const preview = shots[previewShotIndex] ?? shots[0]
        const source = sourceByIndex.get(preview.shot.source_index)
        const shotTimelineStart = shots.slice(0, preview.index).reduce((sum, item) => sum + item.duration, 0)
        const activeOverlay = textOverlays.find((overlay) =>
          overlay.rank === edit.rank && playheadSeconds >= overlay.start_seconds && playheadSeconds <= overlay.end_seconds
        )
        const activeLyric = lyrics.find((lyric) =>
          playheadSeconds >= lyric.start_seconds && playheadSeconds <= lyric.end_seconds
        )
        const selectShot = (index: number) => {
          videoRef.current?.pause()
          audioRef.current?.pause()
          setIsPlaying(false)
          const bounded = Math.max(0, Math.min(shots.length - 1, index))
          setPreviewShotIndex(bounded)
          setPlayheadSeconds(shots.slice(0, bounded).reduce((sum, item) => sum + item.duration, 0))
        }
        const togglePlayback = async () => {
          const video = videoRef.current
          const audio = audioRef.current
          if (!video) return
          if (isPlaying) {
            video.pause()
            audio?.pause()
            setIsPlaying(false)
            return
          }
          if (video.currentTime < preview.shot.start_seconds || video.currentTime >= preview.shot.end_seconds) {
            video.currentTime = preview.shot.start_seconds
          }
          if (audio) {
            audio.currentTime = musicStart + playheadSeconds
            try { await audio.play() } catch { /* Video preview can still be reviewed if audio is unavailable. */ }
          }
          try {
            await video.play()
            setIsPlaying(true)
          } catch {
            audio?.pause()
            setIsPlaying(false)
          }
        }
        return (
          <div className="grid gap-3 rounded-md border border-line bg-surface p-3 sm:grid-cols-[minmax(0,1.4fr)_minmax(180px,1fr)] sm:items-center">
            <div className="relative overflow-hidden rounded-md bg-black">
              <video
                ref={videoRef}
                key={String(preview.index) + "-" + String(preview.shot.source_index) + "-" + String(preview.shot.start_seconds)}
                playsInline
                preload="metadata"
                src={"/api/runs/" + runId + "/campaign-source?source_index=" + preview.shot.source_index}
                onLoadedMetadata={(event) => {
                  advancingShotRef.current = false
                  event.currentTarget.currentTime = preview.shot.start_seconds
                  if (isPlaying) {
                    const audio = audioRef.current
                    if (audio) {
                      audio.currentTime = musicStart + shotTimelineStart
                      void audio.play().catch(() => undefined)
                    }
                    void event.currentTarget.play().catch(() => setIsPlaying(false))
                  }
                }}
                onTimeUpdate={(event) => {
                  const localElapsed = Math.max(0, event.currentTarget.currentTime - preview.shot.start_seconds)
                  const nextPlayhead = shotTimelineStart + localElapsed
                  setPlayheadSeconds(nextPlayhead)
                  const audio = audioRef.current
                  if (audio && isPlaying) {
                    const target = musicStart + nextPlayhead
                    if (Math.abs(audio.currentTime - target) > 0.45) audio.currentTime = target
                  }
                  if (event.currentTarget.currentTime >= preview.shot.end_seconds - 0.04 && !advancingShotRef.current) {
                    advancingShotRef.current = true
                    if (preview.index < shots.length - 1) {
                      setPreviewShotIndex(preview.index + 1)
                    } else {
                      event.currentTarget.pause()
                      audio?.pause()
                      setIsPlaying(false)
                    }
                  }
                }}
                className="max-h-64 w-full bg-black object-contain"
              />
              {activeLyric && (
                <div
                  className="pointer-events-none absolute flex w-[90%] justify-center px-3"
                  style={{
                    left: activeLyric.position_x + '%',
                    top: activeLyric.position_y + '%',
                    transform: 'translate(-50%, -50%) rotate(' + activeLyric.rotation_degrees + 'deg)',
                  }}
                >
                  <span
                    className="text-center font-extrabold leading-tight"
                    style={{
                      color: lyricsColor,
                      fontSize: 'clamp(14px, ' + (22 * activeLyric.scale_percent / 100) + 'px, 42px)',
                      textShadow: '0 2px 8px #000, 0 0 12px ' + lyricsHighlightColor,
                    }}
                  >{activeLyric.text}</span>
                </div>
              )}
              {activeOverlay && (
                <div className="pointer-events-none absolute flex items-center justify-center px-4"
                  style={{ left: activeOverlay.position_x + '%', top: activeOverlay.position_y + '%', transform: 'translate(-50%, -50%)', width: '90%' }}>
                  <span className="text-center font-extrabold leading-tight"
                    style={{
                      color: activeOverlay.color,
                      fontSize: 'clamp(14px, ' + (activeOverlay.font_size_percent * 0.22) + 'vw, 44px)',
                      textShadow: activeOverlay.background ? 'none' : '0 2px 8px #000',
                      background: activeOverlay.background ? 'rgba(0,0,0,.62)' : 'transparent',
                      padding: activeOverlay.background ? '0.25em 0.5em' : 0,
                      borderRadius: '0.3em',
                    }}>{activeOverlay.text}</span>
                </div>
              )}
            </div>
            <div className="flex flex-col gap-2">
              <span className="label text-muted">Synchronized campaign preview · shot {preview.index + 1} of {shots.length}</span>
              <span className="text-sm font-medium">{source?.title ?? "Source " + (preview.shot.source_index + 1)}</span>
              <span className="font-mono text-xs text-faint">
                {formatDuration(preview.shot.start_seconds)} → {formatDuration(preview.shot.end_seconds)}
                {' · '}Timeline {formatDuration(playheadSeconds)} / {formatDuration(total)}
              </span>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => void togglePlayback()}
                  className="rounded-md bg-ink px-4 py-2 text-sm font-semibold text-paper">
                  {isPlaying ? 'Pause preview' : 'Play synchronized preview'}
                </button>
                <button type="button" onClick={() => selectShot(Math.max(0, preview.index - 1))}
                  disabled={preview.index === 0}
                  className="rounded-md border border-line px-3 py-2 text-sm disabled:opacity-40">Previous</button>
                <button type="button" onClick={() => selectShot(Math.min(shots.length - 1, preview.index + 1))}
                  disabled={preview.index === shots.length - 1}
                  className="rounded-md border border-line px-3 py-2 text-sm disabled:opacity-40">Next</button>
              </div>
              <p className="mt-1 text-xs text-muted">One controller plays the selected footage and soundtrack together, automatically advancing through the remaining shots. Timed campaign text appears over the preview.</p>
            </div>
          </div>
        )
      })()}
      {hasMusic && <audio ref={audioRef} preload="metadata" src={"/api/runs/" + runId + "/campaign-music"} className="hidden" />}
      <div className="overflow-x-auto">
        <div data-campaign-timeline-track className="relative flex min-w-[680px] gap-1 rounded-md bg-surface p-2">
          {shots.map(({ shot, index, duration }) => {
            const source = sourceByIndex.get(shot.source_index)
            return (
              <button
                key={`${edit.rank}-timeline-${index}`}
                type="button"
                title={`Shot ${index + 1}: ${source?.title ?? `Source ${shot.source_index + 1}`} · ${formatDuration(shot.end_seconds - shot.start_seconds)}`}
                aria-label={`Jump to shot ${index + 1} in the storyboard editor`}
                onClick={() => {
                  videoRef.current?.pause()
                  audioRef.current?.pause()
                  setIsPlaying(false)
                  setPreviewShotIndex(index)
                  setPlayheadSeconds(shots.slice(0, index).reduce((sum, item) => sum + item.duration, 0))
                  document.getElementById(`campaign-shot-${edit.rank}-${index}`)?.scrollIntoView({ behavior: "smooth", block: "center" })
                }}
                draggable
                onDragStart={(event) => {
                  event.dataTransfer.effectAllowed = 'move'
                  event.dataTransfer.setData('text/plain', String(index))
                }}
                onDragOver={(event) => {
                  event.preventDefault()
                  event.dataTransfer.dropEffect = 'move'
                }}
                onDrop={(event) => {
                  event.preventDefault()
                  const draggedIndex = event.dataTransfer.getData('text/plain')
                  if (!draggedIndex.trim()) return
                  const fromIndex = Number(draggedIndex)
                  if (Number.isInteger(fromIndex)) { onMoveShot(fromIndex, index); setPreviewShotIndex(index) }
                }}
                className="group relative min-w-[104px] flex-1 cursor-grab overflow-hidden rounded-md border border-line bg-paper text-left transition-colors hover:border-ink active:cursor-grabbing"
                style={{ flex: `${duration} 1 0%` }}
              >
                {(['start', 'end'] as const).map((side) => {
                  const sourceDuration = source?.duration_seconds ?? shot.end_seconds
                  const value = side === 'start' ? shot.start_seconds : shot.end_seconds
                  const min = side === 'start' ? Math.max(0, shot.end_seconds - 5) : shot.start_seconds + 1.5
                  const max = side === 'start' ? shot.end_seconds - 1.5 : Math.min(sourceDuration, shot.start_seconds + 5)
                  const applyTrim = (nextValue: number) => {
                    const bounded = Math.max(min, Math.min(max, nextValue))
                    onUpdateShot(index, side === 'start'
                      ? { start_seconds: Math.round(bounded * 1000) / 1000 }
                      : { end_seconds: Math.round(bounded * 1000) / 1000 })
                  }
                  return (
                    <span
                      key={side}
                      role="slider"
                      tabIndex={0}
                      aria-label={`Shot ${index + 1} ${side === 'start' ? 'in' : 'out'} point`}
                      aria-valuemin={min}
                      aria-valuemax={max}
                      aria-valuenow={value}
                      aria-valuetext={formatDuration(value)}
                      title={`Drag to adjust shot ${side === 'start' ? 'start' : 'end'} · use arrow keys for fine control`}
                      onPointerDown={(event) => {
                        event.preventDefault()
                        event.stopPropagation()
                        const track = event.currentTarget.closest('[data-campaign-timeline-track]')
                        const trackWidth = track?.getBoundingClientRect().width ?? 0
                        if (trackWidth <= 0) return
                        event.currentTarget.setPointerCapture(event.pointerId)
                        setActiveTrim({
                          pointerId: event.pointerId,
                          shotIndex: index,
                          side,
                          startX: event.clientX,
                          initialStart: shot.start_seconds,
                          initialEnd: shot.end_seconds,
                          trackWidth,
                          initialTotal: total,
                        })
                      }}
                      onPointerMove={(event) => {
                        if (!activeTrim || activeTrim.pointerId !== event.pointerId || activeTrim.shotIndex !== index || activeTrim.side !== side) return
                        const delta = ((event.clientX - activeTrim.startX) / activeTrim.trackWidth) * activeTrim.initialTotal
                        const start = activeTrim.initialStart
                        const end = activeTrim.initialEnd
                        const next = side === 'start'
                          ? Math.max(0, Math.min(end - 1.5, Math.max(end - 5, start + delta)))
                          : Math.max(start + 1.5, Math.min(Math.min(sourceDuration, start + 5), end + delta))
                        onUpdateShot(index, side === 'start'
                          ? { start_seconds: Math.round(next * 1000) / 1000 }
                          : { end_seconds: Math.round(next * 1000) / 1000 })
                      }}
                      onPointerUp={(event) => {
                        if (activeTrim?.pointerId !== event.pointerId) return
                        if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
                        setActiveTrim(null)
                      }}
                      onPointerCancel={() => setActiveTrim(null)}
                      onDragStart={(event) => event.preventDefault()}
                      onClick={(event) => event.stopPropagation()}
                      onKeyDown={(event) => {
                        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
                        event.preventDefault()
                        applyTrim(value + (event.key === 'ArrowRight' ? 0.1 : -0.1))
                      }}
                      className={cn(
                        'absolute inset-y-0 z-10 w-3 touch-none border border-paper/80 bg-white/80 shadow-sm outline-none hover:bg-acid focus-visible:bg-acid',
                        side === 'start' ? 'left-0 cursor-ew-resize rounded-l-md' : 'right-0 cursor-ew-resize rounded-r-md',
                        activeTrim?.shotIndex === index && activeTrim.side === side ? 'bg-acid' : '',
                      )}
                    />
                  )
                })}
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
          <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 z-20 w-0.5 bg-red-500 shadow-[0_0_5px_rgba(239,68,68,0.9)]" style={{ left: 'calc(' + Math.max(0, Math.min(100, (playheadSeconds / total) * 100)) + '%)' }} />
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
          {(musicAnalysis.energy_sections ?? []).length > 0 ? (
            <div className="overflow-x-auto">
              <div className="relative h-9 min-w-[680px] overflow-hidden rounded-md bg-surface">
                {(musicAnalysis.energy_sections ?? []).map((section, index) => {
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
          ) : (
            <p className="text-xs text-faint">Energy detail is unavailable for this saved run.</p>
          )}
          <div className="flex flex-wrap gap-3 text-[10px] text-faint">
            <span>Selected track window: {musicAnalysis.selected_section}</span>
            <span>High energy · Medium energy · Low energy</span>
          </div>
        </div>
      )}
      <div className="flex flex-col gap-2 border-t border-line pt-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="label text-muted">Independent text overlay track</span>
          <span className="text-[10px] text-faint">Times are relative to this finished edit</span>
        </div>
        <div className="overflow-x-auto">
          <div className="relative h-10 min-w-[680px] overflow-hidden rounded-md border border-line bg-surface">
            {textOverlays.filter((overlay) => overlay.rank === edit.rank).map((overlay, index) => {
              const left = Math.max(0, Math.min(total, overlay.start_seconds))
              const right = Math.max(left, Math.min(total, overlay.end_seconds))
              if (right <= left) return null
              return (
                <div
                  key={"text-overlay-" + edit.rank + "-" + index}
                  title={overlay.text + " · " + formatDuration(overlay.start_seconds) + "–" + formatDuration(overlay.end_seconds)}
                  className="absolute inset-y-1 flex min-w-0 items-center overflow-hidden rounded border px-1.5"
                  style={{
                    left: String((left / total) * 100) + "%",
                    width: String(Math.max(0.8, ((right - left) / total) * 100)) + "%",
                    borderColor: overlay.color,
                    color: overlay.color,
                    backgroundColor: overlay.background ? "rgba(0, 0, 0, 0.78)" : "rgba(255, 255, 255, 0.06)",
                  }}
                >
                  <span className="truncate text-[10px] font-semibold">{overlay.text}</span>
                </div>
              )
            })}
            {textOverlays.every((overlay) => overlay.rank !== edit.rank) && (
              <span className="absolute inset-0 flex items-center px-3 text-[10px] text-faint">
                No independent text layers on this edit yet
              </span>
            )}
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-2 border-t border-line pt-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="label text-muted">Independent text overlay track</span>
          <span className="text-[10px] text-faint">Drag a block to move it · drag either edge to trim</span>
        </div>
        <div className="overflow-x-auto">
          <div
            data-campaign-overlay-track
            className="relative h-10 min-w-[680px] touch-none overflow-hidden rounded-md border border-line bg-surface"
            onPointerMove={(event) => {
              if (!activeOverlayTrim || event.pointerId !== activeOverlayTrim.pointerId) return
              const delta = ((event.clientX - activeOverlayTrim.startX) / activeOverlayTrim.trackWidth) * activeOverlayTrim.initialTotal
              const length = activeOverlayTrim.initialEnd - activeOverlayTrim.initialStart
              if (activeOverlayTrim.side === 'move') {
                const start = Math.max(0, Math.min(activeOverlayTrim.initialTotal - length, activeOverlayTrim.initialStart + delta))
                onUpdateTextOverlay(activeOverlayTrim.overlayIndex, {
                  start_seconds: Math.round(start * 100) / 100,
                  end_seconds: Math.round((start + length) * 100) / 100,
                })
              } else if (activeOverlayTrim.side === 'start') {
                const start = Math.max(0, Math.min(activeOverlayTrim.initialEnd - 0.1, activeOverlayTrim.initialStart + delta))
                onUpdateTextOverlay(activeOverlayTrim.overlayIndex, { start_seconds: Math.round(start * 100) / 100 })
              } else {
                const end = Math.max(activeOverlayTrim.initialStart + 0.1, Math.min(activeOverlayTrim.initialTotal, activeOverlayTrim.initialEnd + delta))
                onUpdateTextOverlay(activeOverlayTrim.overlayIndex, { end_seconds: Math.round(end * 100) / 100 })
              }
            }}
            onPointerUp={(event) => {
              if (activeOverlayTrim?.pointerId === event.pointerId) setActiveOverlayTrim(null)
            }}
            onPointerCancel={() => setActiveOverlayTrim(null)}
          >
            {textOverlays.map((overlay, overlayIndex) => ({ overlay, overlayIndex }))
              .filter(({ overlay }) => overlay.rank === edit.rank)
              .map(({ overlay, overlayIndex }) => {
                const left = Math.max(0, Math.min(total, overlay.start_seconds))
                const right = Math.max(left, Math.min(total, overlay.end_seconds))
                if (right <= left) return null
                const beginDrag = (event: React.PointerEvent<HTMLDivElement>, side: 'move' | 'start' | 'end') => {
                  event.preventDefault()
                  event.stopPropagation()
                  const track = event.currentTarget.closest('[data-campaign-overlay-track]') as HTMLDivElement | null
                  if (!track) return
                  const trackWidth = track.getBoundingClientRect().width
                  if (trackWidth <= 0) return
                  track.setPointerCapture(event.pointerId)
                  setActiveOverlayTrim({
                    pointerId: event.pointerId,
                    overlayIndex,
                    side,
                    startX: event.clientX,
                    initialStart: overlay.start_seconds,
                    initialEnd: overlay.end_seconds,
                    trackWidth,
                    initialTotal: total,
                  })
                }
                return (
                  <div
                    key={"text-overlay-" + edit.rank + "-" + overlayIndex}
                    title={overlay.text + " · " + formatDuration(overlay.start_seconds) + "–" + formatDuration(overlay.end_seconds)}
                    onPointerDown={(event) => beginDrag(event, 'move')}
                    className="group absolute inset-y-1 flex min-w-0 cursor-grab touch-none items-center overflow-hidden rounded border px-1.5 active:cursor-grabbing"
                    style={{
                      left: String((left / total) * 100) + "%",
                      width: String(Math.max(1.2, ((right - left) / total) * 100)) + "%",
                      borderColor: overlay.color,
                      color: overlay.color,
                      backgroundColor: overlay.background ? "rgba(0, 0, 0, 0.78)" : "rgba(255, 255, 255, 0.06)",
                    }}
                  >
                    <div
                      role="slider"
                      aria-label={"Trim start of " + overlay.text}
                      aria-valuemin={0}
                      aria-valuemax={overlay.end_seconds - 0.1}
                      aria-valuenow={overlay.start_seconds}
                      onPointerDown={(event) => beginDrag(event, 'start')}
                      className="absolute inset-y-0 left-0 z-10 w-2 cursor-ew-resize bg-white/40 opacity-0 transition-opacity group-hover:opacity-100"
                    />
                    <span className="pointer-events-none truncate text-[10px] font-semibold">{overlay.text}</span>
                    <div
                      role="slider"
                      aria-label={"Trim end of " + overlay.text}
                      aria-valuemin={overlay.start_seconds + 0.1}
                      aria-valuemax={total}
                      aria-valuenow={overlay.end_seconds}
                      onPointerDown={(event) => beginDrag(event, 'end')}
                      className="absolute inset-y-0 right-0 z-10 w-2 cursor-ew-resize bg-white/40 opacity-0 transition-opacity group-hover:opacity-100"
                    />
                  </div>
                )
              })}
            {textOverlays.every((overlay) => overlay.rank !== edit.rank) && (
              <span className="absolute inset-0 flex items-center px-3 text-[10px] text-faint">
                No independent text layers on this edit yet
              </span>
            )}
          </div>
        </div>
      </div>
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
              <span
                className="flex items-center gap-2"
                title="AI virality estimate based on hook, value, clarity, retention and shareability — not a performance guarantee."
              >
                <Squares total={10} filled={Math.round(clip.score)} size="h-1.5 w-1.5" />
                <span className="text-ink">{clip.score.toFixed(1)}</span>
                <span className="label text-faint">AI score</span>
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
            {Object.entries(checks).filter(([key]) => key !== 'music_analysis').map(([key, value]) => (
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


function LyricsPositionPreview({
  frameUrl,
  text,
  x,
  y,
  scale,
  rotation,
  aspectRatio,
  onPositionChange,
}: {
  frameUrl: string | null
  text: string
  x: number
  y: number
  scale: number
  rotation: number
  aspectRatio: string
  onPositionChange: (x: number, y: number) => void
}) {
  const [dragging, setDragging] = useState(false)
  const updatePosition = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging && event.type !== 'pointerdown') return
    const bounds = event.currentTarget.getBoundingClientRect()
    const nextX = Math.max(5, Math.min(95, Math.round(((event.clientX - bounds.left) / bounds.width) * 100)))
    const nextY = Math.max(5, Math.min(95, Math.round(((event.clientY - bounds.top) / bounds.height) * 100)))
    onPositionChange(nextX, nextY)
  }
  const ratio = aspectRatio.replace(':', ' / ')

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-line bg-panel p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-sm">Drag lyrics on the preview</span>
        <span className="font-mono text-xs text-muted">{x}% · {y}%</span>
      </div>
      <div
        className="relative mx-auto w-full max-w-[280px] touch-none select-none overflow-hidden rounded-lg border border-line bg-ink"
        style={{ aspectRatio: ratio }}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId)
          setDragging(true)
          updatePosition(event)
        }}
        onPointerMove={updatePosition}
        onPointerUp={() => setDragging(false)}
        onPointerCancel={() => setDragging(false)}
        role="group"
        aria-label="Interactive lyric placement preview. Drag to move the text."
      >
        {frameUrl ? (
          <img src={frameUrl} alt="Representative campaign frame" draggable={false} className="absolute inset-0 h-full w-full object-cover" />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-zinc-800 to-zinc-950 px-6 text-center text-xs text-white/60">
            Campaign frame preview will appear after the storyboard has shots.
          </div>
        )}
        <div
          className="pointer-events-none absolute max-w-[90%] whitespace-pre-wrap text-center font-extrabold leading-tight text-white"
          style={{
            left: `${x}%`,
            top: `${y}%`,
            transform: `translate(-50%, -50%) rotate(${rotation}deg) scale(${scale / 100})`,
            transformOrigin: 'center',
            textShadow: '0 2px 4px #000, 0 0 10px #000',
            fontSize: 'clamp(12px, 4vw, 22px)',
          }}
        >
          {text}
        </div>
        <div className="pointer-events-none absolute inset-0 border border-white/20" />
      </div>
      <p className="text-xs text-muted">This is a still-frame placement preview. Drag anywhere inside the frame; the position sliders update with it. Apply to existing edit to render the new placement.</p>
    </div>
  )
}
