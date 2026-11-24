import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, ArrowUpRight, Check, ChevronDown, Copy, Download, RotateCcw, Scissors, Send, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useUndoRedo } from '../hooks/useUndoRedo'
import { toast } from 'sonner'
import { api, type CampaignEdit, type CampaignConcept, type CampaignTextOverlay, type CampaignMusicAnalysis, type CampaignLyricPhraseEdit, type CampaignShot, type CampaignSource, type Clip, type Post, type RunDetail } from '../api'
import { PublishDialog } from '../components/PublishDialog'
import { Button, Eyebrow, Panel, Squares, StatusChip, cn, formatDuration, sourceHost, sourceLabel, timeAgo } from '../components/ui'
type CampaignPreviewLyric = {
  phrase_index: number
  text: string
  start_seconds: number
  end_seconds: number
  position_x: number
  position_y: number
  scale_percent: number
  rotation_degrees: number
}

type CampaignPreviewWord = { word: string; start_seconds: number; end_seconds: number }


type CreativeConceptPlayerProps = {
  runId: string
  conceptId: string
  edit: CampaignEdit | undefined
  hasMusic: boolean
  musicStartSeconds: number
  musicVolume: number
  sourceAudioVolume: number
  transitionStyle: 'auto' | 'cut' | 'cinematic' | 'dynamic'
  isActive: boolean
  onActivate: (conceptId: string) => void
}

function CreativeConceptPlayer({
  runId,
  conceptId,
  edit,
  hasMusic,
  musicStartSeconds,
  musicVolume,
  sourceAudioVolume,
  transitionStyle,
  isActive,
  onActivate,
}: CreativeConceptPlayerProps) {
  const shots = edit?.shots ?? []
  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const advancingRef = useRef(false)
  const transitionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [transitioning, setTransitioning] = useState(false)
  const transitionDurationMs = transitionStyle === 'cut' ? 0 : transitionStyle === 'cinematic' ? 420 : 220
  const [shotIndex, setShotIndex] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const totalSeconds = shots.reduce((total, shot) => total + Math.max(0, shot.end_seconds - shot.start_seconds), 0)
  const shot = shots[shotIndex]
  const timelineStart = shots.slice(0, shotIndex).reduce(
    (total, item) => total + Math.max(0, item.end_seconds - item.start_seconds),
    0,
  )

  useEffect(() => {
    if (isActive) return
    videoRef.current?.pause()
    audioRef.current?.pause()
    setIsPlaying(false)
  }, [isActive])

  useEffect(() => () => {
    videoRef.current?.pause()
    audioRef.current?.pause()
    if (transitionTimerRef.current) clearTimeout(transitionTimerRef.current)
  }, [])

  const pause = () => {
    videoRef.current?.pause()
    audioRef.current?.pause()
    setIsPlaying(false)
  }

  const play = async () => {
    if (!shot || shots.length === 0) return
    onActivate(conceptId)
    advancingRef.current = false
    setIsPlaying(true)
    const video = videoRef.current
    if (video) {
      if (video.currentTime < shot.start_seconds || video.currentTime >= shot.end_seconds) {
        video.currentTime = shot.start_seconds
      }
      video.volume = sourceAudioVolume / 100
      try {
        await video.play()
      } catch {
        setIsPlaying(false)
        return
      }
    }
    const audio = audioRef.current
    if (audio && hasMusic) {
      audio.volume = musicVolume / 100
      audio.currentTime = musicStartSeconds + elapsedSeconds
      void audio.play().catch(() => undefined)
    }
  }

  const advanceShot = () => {
    if (advancingRef.current) return
    advancingRef.current = true
    if (shotIndex < shots.length - 1) {
      setShotIndex((current) => current + 1)
    } else {
      pause()
      setElapsedSeconds(totalSeconds)
    }
  }

  if (!shot) {
    return <div className="flex aspect-video items-center justify-center rounded-md bg-sunk text-xs text-muted">No playable shots in this direction</div>
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="relative overflow-hidden rounded-md bg-black">
        <video
          ref={videoRef}
          key={shotIndex + "-" + shot.source_index + "-" + shot.start_seconds}
          playsInline
          preload="metadata"
          src={`/api/runs/${runId}/campaign-source?source_index=${shot.source_index}`}
          onLoadedMetadata={(event) => {
            advancingRef.current = false
            if (transitionTimerRef.current) clearTimeout(transitionTimerRef.current)
            if (transitionDurationMs > 0) {
              setTransitioning(true)
              transitionTimerRef.current = setTimeout(() => setTransitioning(false), 40)
            }
            event.currentTarget.currentTime = shot.start_seconds
            event.currentTarget.volume = sourceAudioVolume / 100
            if (isPlaying) void event.currentTarget.play().catch(() => setIsPlaying(false))
          }}
          onTimeUpdate={(event) => {
            const localElapsed = Math.max(0, event.currentTarget.currentTime - shot.start_seconds)
            const nextElapsed = timelineStart + localElapsed
            setElapsedSeconds(Math.min(totalSeconds, nextElapsed))
            const audio = audioRef.current
            if (audio && hasMusic && isPlaying) {
              const target = musicStartSeconds + nextElapsed
              if (Math.abs(audio.currentTime - target) > 0.4) audio.currentTime = target
            }
            if (event.currentTarget.currentTime >= shot.end_seconds - 0.04) advanceShot()
          }}
          onError={() => {
            pause()
          }}
          style={{ opacity: transitioning ? 0 : 1, transition: transitionDurationMs > 0 ? `opacity ${transitionDurationMs}ms ease` : "none" }}
          className="aspect-video w-full bg-black object-contain"
        />
        <span className="absolute bottom-2 left-2 rounded bg-black/75 px-2 py-1 text-[10px] font-medium text-white">
          LIVE CONCEPT PREVIEW · SHOT {shotIndex + 1}/{shots.length}
        </span>
      </div>
      {hasMusic && (
        <audio
          ref={audioRef}
          src={`/api/runs/${runId}/campaign-music`}
          preload="metadata"
          onError={() => undefined}
        />
      )}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => (isPlaying && isActive ? pause() : void play())}
          className="rounded-md border border-line px-3 py-1.5 text-xs font-semibold hover:border-ink"
          aria-label={isPlaying && isActive ? "Pause concept preview" : "Play concept preview"}
        >
          {isPlaying && isActive ? "Pause" : "Play preview"}
        </button>
        <button
          type="button"
          onClick={() => {
            pause()
            advancingRef.current = false
            setShotIndex(0)
            setElapsedSeconds(0)
            if (videoRef.current) videoRef.current.currentTime = shots[0]?.start_seconds ?? 0
            if (audioRef.current) audioRef.current.currentTime = musicStartSeconds
          }}
          className="rounded-md border border-line px-3 py-1.5 text-xs font-semibold hover:border-ink"
        >
          Restart
        </button>
        <span className="ml-auto font-mono text-[11px] text-muted">
          {formatDuration(elapsedSeconds)} / {formatDuration(totalSeconds)}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-sunk" role="progressbar" aria-label={`${edit?.title ?? "Concept"} preview progress`} aria-valuemin={0} aria-valuemax={Math.max(1, totalSeconds)} aria-valuenow={elapsedSeconds}>
        <div className="h-full rounded-full bg-ink transition-[width]" style={{ width: totalSeconds > 0 ? `${(elapsedSeconds / totalSeconds) * 100}%` : "0%" }} />
      </div>
      <p className="text-[10px] text-faint">
        {hasMusic ? "Original source audio and attached campaign music are mixed using your current volume settings." : "Previewing original source audio. Attach campaign music to hear the soundtrack with the edit."}
      </p>
    </div>
  )
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
  const [selectedConceptId, setSelectedConceptId] = useState<string | null>(null)
  const [conceptCutVariants, setConceptCutVariants] = useState<Record<string, 'original' | 'refined'>>({})
  const [activeConceptPreviewId, setActiveConceptPreviewId] = useState<string | null>(null)
  const [activeEditorSection, setActiveEditorSection] = useState('campaign-preview')
  useEffect(() => {
    setSelectedConceptId(null)
    setConceptCutVariants({})
    setActiveConceptPreviewId(null)
  }, [runId])
  const [musicFile, setMusicFile] = useState<File | null>(null)
  const [musicVolume, setMusicVolume] = useState(90)
  const [sourceAudioVolume, setSourceAudioVolume] = useState(100)
  const [musicDucking, setMusicDucking] = useState(false)
  const [musicStartSeconds, setMusicStartSeconds] = useState(0)
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
    setSourceAudioVolume(Math.round((run.data?.options.campaign_source_audio_volume ?? 1) * 100))
    setMusicDucking(Boolean(run.data?.options.campaign_music_ducking))
    setMusicStartSeconds(run.data?.options.campaign_music_start_seconds ?? run.data?.campaign_quality_checks?.music_analysis?.selected_start_seconds ?? 0)
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
  }, [runId, run.data?.campaign_edits, run.data?.options.campaign_music_volume, run.data?.options.campaign_source_audio_volume, run.data?.options.campaign_music_ducking, run.data?.options.campaign_music_start_seconds, run.data?.campaign_quality_checks?.music_analysis?.selected_start_seconds, run.data?.options.campaign_music_fade_in_seconds, run.data?.options.campaign_music_fade_out_seconds, run.data?.options.campaign_lyrics, run.data?.options.campaign_lyrics_style, run.data?.options.campaign_hook_text, run.data?.options.include_campaign_hook, run.data?.options.campaign_lyrics_color, run.data?.options.campaign_lyrics_highlight_color, run.data?.options.campaign_lyrics_words_on_screen, run.data?.options.campaign_lyrics_behind_subject, run.data?.options.campaign_lyrics_position_x, run.data?.options.campaign_lyrics_position_y, run.data?.options.campaign_lyrics_scale_percent, run.data?.options.campaign_lyrics_rotation_degrees, run.data?.options.campaign_lyric_phrase_edits, run.data?.options.campaign_text_overlays, run.data?.campaign_plan?.generated_hook, resetCampaignHistory])

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
    mutationFn: () => api.saveCampaignAudio(runId, musicVolume / 100, sourceAudioVolume / 100, musicDucking, musicStartSeconds, musicFadeIn, musicFadeOut),
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
  const lyricOffset = musicStartSeconds
  const campaignTimelineLyrics: CampaignPreviewLyric[] = lyricRows.flatMap((phrase, index) => {
    if (phrase.start == null) return []
    const phraseEdit = phraseEdits.find((edit) => edit.phrase_index === index)
    const rawStart = phraseEdit?.start_seconds ?? phrase.start
    const nextTimedStart = lyricRows.slice(index + 1).find((row) => row.start != null)?.start
    const rawEnd = phraseEdit?.end_seconds ?? nextTimedStart ?? rawStart + 3
    const start = Math.max(0, rawStart - lyricOffset)
    const end = rawEnd - lyricOffset
    if (end <= start) return []
    return [{
      phrase_index: index,
      text: phrase.text,
      start_seconds: start,
      end_seconds: end,
      position_x: phraseEdit?.position_x ?? lyricsPositionX,
      position_y: phraseEdit?.position_y ?? lyricsPositionY,
      scale_percent: phraseEdit?.scale_percent ?? lyricsScale,
      rotation_degrees: phraseEdit?.rotation_degrees ?? lyricsRotation,
    }]
  })
  const campaignTimelineWords: CampaignPreviewWord[] = (run.data?.options.campaign_lyric_words ?? []).flatMap((item) => {
    const start = Number(item.start) - lyricOffset
    const end = Number(item.end) - lyricOffset
    const word = String(item.word ?? '').trim()
    if (!word || end <= 0 || end <= start) return []
    return [{ word, start_seconds: Math.max(0, start), end_seconds: end }]
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
  const updateLyricPhrase = (phraseIndex: number, patch: Partial<CampaignLyricPhraseEdit>) => {
    setPhraseEdits((current) => {
      const existing = current.find((edit) => edit.phrase_index === phraseIndex)
      const next = { phrase_index: phraseIndex, ...existing, ...patch }
      return [...current.filter((edit) => edit.phrase_index !== phraseIndex), next].sort((left, right) => left.phrase_index - right.phrase_index)
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
    mutationFn: (edits?: CampaignEdit[]) => api.saveCampaignMontage(runId, edits ?? campaignEdits),
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

  useEffect(() => {
    if (!run.data?.options.campaign_mode || ['queued', 'running'].includes(run.data.status)) return
    const sectionIds = [
      'campaign-preview',
      'campaign-hook',
      'campaign-audio',
      'campaign-animations',
      'campaign-lyrics',
      'campaign-text',
      'campaign-storyboard',
    ]
    const sections = sectionIds
      .map((id) => document.getElementById(id))
      .filter((element): element is HTMLElement => element !== null)
    if (!sections.length) return

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0]
        if (visible) setActiveEditorSection(visible.target.id)
      },
      { rootMargin: '-18% 0px -68% 0px', threshold: [0, 0.1, 0.25, 0.5] },
    )
    sections.forEach((section) => observer.observe(section))
    return () => observer.disconnect()
  }, [runId, run.data?.options.campaign_mode, run.data?.status, run.data?.campaign_edits?.length])

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
  const savedSourceAudioVolume = Math.round((data.options.campaign_source_audio_volume ?? 1) * 100)
  const savedMusicDucking = Boolean(data.options.campaign_music_ducking)
  const savedMusicStartSeconds = data.options.campaign_music_start_seconds ?? data.campaign_quality_checks?.music_analysis?.selected_start_seconds ?? 0
  const savedMusicFadeIn = data.options.campaign_music_fade_in_seconds ?? 0.4
  const savedMusicFadeOut = data.options.campaign_music_fade_out_seconds ?? 0.8
  const musicSettingsChanged = musicVolume !== savedMusicVolume || musicDucking !== savedMusicDucking || Math.abs(musicStartSeconds - savedMusicStartSeconds) > 0.01 || musicFadeIn !== savedMusicFadeIn || musicFadeOut !== savedMusicFadeOut
  const sourceAudioSettingsChanged = sourceAudioVolume !== savedSourceAudioVolume
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
        <div className="grid items-start gap-5 lg:grid-cols-[190px_minmax(0,1fr)]">
          <nav aria-label="Campaign editor tools" className="z-10 flex gap-2 overflow-x-auto rounded-xl border border-line bg-surface p-2 lg:sticky lg:top-5 lg:flex-col lg:gap-1 lg:overflow-visible">
            <div className="hidden px-3 py-2 lg:block">
              <p className="label text-faint">YOUR EDITING WORKFLOW</p>
              <p className="mt-1 text-xs leading-relaxed text-muted">Work from top to bottom. You can revisit any step whenever you like.</p>
            </div>
            {[
              ['campaign-preview', 'Video & Timeline', '1'],
              ['campaign-audio', 'Music & Audio', '2'],
              ['campaign-animations', 'Animations', '3'],
              ['campaign-lyrics', 'Lyrics Sync', '4'],
              ['campaign-text', 'Text & Titles', '5'],
              ['campaign-storyboard', 'Shot Editing', '6'],
            ].map(([target, label, step]) => {
              const active = activeEditorSection === target
              return (
                <a
                  key={target}
                  href={`#${target}`}
                  aria-current={active ? 'location' : undefined}
                  className={cn(
                    'flex shrink-0 items-center gap-2 rounded-md border-l-2 px-3 py-2 text-left text-xs font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink lg:w-full',
                    active
                      ? 'border-acid bg-sunk text-ink'
                      : 'border-transparent text-muted hover:bg-sunk hover:text-ink',
                  )}
                >
                  <span className={cn(
                    'flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] tabular-nums',
                    active ? 'bg-acid text-black' : 'bg-panel text-faint',
                  )}>{step}</span>
                  {label}
                </a>
              )
            })}
          </nav>
          <div className="flex min-w-0 flex-col gap-6">
            <div id="campaign-preview" className="scroll-mt-5">
      {data.options.campaign_mode && !busy && campaignEdits.length > 0 && (
        <CampaignStoryboardEditor
          runId={runId}
          edits={campaignEdits}
          savedEdits={data.campaign_edits}
          originalEdits={data.campaign_original_edits ?? data.campaign_edits}
          sources={data.campaign_sources ?? []}
          musicAnalysis={data.campaign_quality_checks?.music_analysis ?? null}
          musicStartSeconds={musicStartSeconds}
          onMusicStartChange={setMusicStartSeconds}
          hasMusic={Boolean(data.options.campaign_music_path)}
          lyricsBehindSubject={lyricsBehindSubject}
          lyrics={campaignTimelineLyrics}
          onUpdateLyric={updateLyricPhrase}
          lyricWords={campaignTimelineWords}
          wordsOnScreen={data.options.campaign_lyrics_words_on_screen ?? 3}
          lyricsColor={lyricsColor}
          lyricsHighlightColor={lyricsHighlightColor}
          textOverlays={campaignTextOverlays}
          onUpdateTextOverlay={(overlayIndex, patch) => setCampaignTextOverlays((current) => current.map((overlay, index) => index === overlayIndex ? { ...overlay, ...patch } : overlay))}
          transitionStyle={data.options.campaign_transition_style ?? 'auto'}
          saving={saveMontage.isPending}
          onChange={setCampaignEdits}
          onSave={() => saveMontage.mutate()}
          onReset={() => setCampaignEdits(data.campaign_original_edits ?? data.campaign_edits)}
          hookText={hookText}
          includeHook={includeHook}
          generatedHook={typeof data.campaign_plan?.generated_hook === 'string' ? data.campaign_plan.generated_hook : null}
          onHookTextChange={setHookText}
          onIncludeHookChange={setIncludeHook}
          musicFile={musicFile}
          onMusicFileChange={setMusicFile}
          onAttachMusic={() => musicFile && attachMusic.mutate(musicFile)}
          attachingMusic={attachMusic.isPending}
          musicTrackDescription={data.options.campaign_music_path
            ? data.campaign_plan?.official_platform_sound_required
              ? 'A track is attached. TikTok’s official sound must still be selected separately when publishing.'
              : 'A soundtrack is attached. Choose another file to replace it.'
            : 'No soundtrack attached yet. Add a local audio file to use it in the export.'}
          musicVolume={musicVolume}
          onMusicVolumeChange={setMusicVolume}
          musicFadeIn={musicFadeIn}
          onMusicFadeInChange={setMusicFadeIn}
          musicFadeOut={musicFadeOut}
          onMusicFadeOutChange={setMusicFadeOut}
          musicDucking={musicDucking}
          onMusicDuckingChange={setMusicDucking}
          sourceAudioVolume={sourceAudioVolume}
          onSourceAudioVolumeChange={setSourceAudioVolume}
          musicSettingsChanged={musicSettingsChanged}
          sourceAudioSettingsChanged={sourceAudioSettingsChanged}
          savingAudio={saveCampaignAudio.isPending}
          savingLyrics={saveLyrics.isPending}
          savingText={saveCampaignTextOverlays.isPending}
          onSaveAudio={() => saveCampaignAudio.mutate()}
          onSaveLyrics={() => saveLyrics.mutate()}
          onSaveText={() => saveCampaignTextOverlays.mutate()}
        />
      )}
            </div>
      {data.options.campaign_mode && !busy && (
        <div className="scroll-mt-5 flex flex-col gap-4 rounded-xl border border-line bg-surface p-4">
          <div id="campaign-animations" className="scroll-mt-5 flex flex-col gap-3 text-sm">
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
          <div id="campaign-lyrics" className="scroll-mt-5 flex flex-col gap-3">
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
        </div>
      )}

      {(busy || data.status === 'failed') && <Progress run={data} />}

      {data.options.campaign_mode && !busy && (data.campaign_concepts?.length ?? 0) > 1 && (
        <section className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-4">
          <div>
            <p className="label text-muted">AI CREATIVE DIRECTOR</p>
            <h2 className="display mt-1 text-2xl">Compare your edit directions</h2>
            <p className="mt-1 text-sm text-muted">Preview the opening frame, shot sequence and pacing side by side. Select a direction to make it your active storyboard, then render when you're ready.</p>
          </div>
          <div className="grid items-stretch gap-3 md:grid-cols-2 xl:grid-cols-3">
            {data.campaign_concepts?.map((concept: CampaignConcept) => {
              const cutVariant = conceptCutVariants[concept.id] ?? 'original'
              const conceptEdits = cutVariant === 'refined' && concept.refined_edits?.length
                ? concept.refined_edits
                : concept.edits
              const edit = conceptEdits[0]
              const shots = edit?.shots ?? []
              const totalSeconds = shots.reduce((total, shot) => total + Math.max(0, shot.end_seconds - shot.start_seconds), 0)
              const averageShot = shots.length ? totalSeconds / shots.length : 0
              const sourceCount = new Set(shots.map((shot) => shot.source_index)).size
              const isSelected = selectedConceptId === concept.id || (!selectedConceptId && concept.id === data.campaign_concepts?.[0]?.id)
              const previewShots = shots.slice(0, 5)
              return (
                <article key={concept.id} className={cn('flex min-w-0 flex-col gap-3 rounded-lg border p-3 transition-colors', isSelected ? 'border-ink bg-panel ring-1 ring-ink/20' : 'border-line bg-panel')}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h3 className="font-semibold">{concept.name}</h3>
                      <p className="mt-1 text-xs leading-relaxed text-muted">{concept.summary}</p>
                    </div>
                    {isSelected && <span className="shrink-0 rounded-full bg-ink px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-panel">Selected</span>}
                  </div>
                  {shots[0] ? (
                    <CreativeConceptPlayer
                      runId={runId}
                      conceptId={concept.id}
                      edit={edit}
                      hasMusic={Boolean(data.options.campaign_music_path)}
                      musicStartSeconds={musicStartSeconds}
                      musicVolume={musicVolume}
                      sourceAudioVolume={sourceAudioVolume}
                      transitionStyle={data.options.campaign_transition_style}
                      isActive={activeConceptPreviewId === concept.id}
                      onActivate={setActiveConceptPreviewId}
                    />
                  ) : (
                    <div className="flex aspect-video items-center justify-center rounded-md bg-sunk text-xs text-muted">No preview shots</div>
                  )}
                  {concept.refined_edits?.length ? (
                    <div className="flex flex-col gap-2 rounded-md border border-line bg-surface p-2">
                      <div className="flex flex-wrap gap-2">
                        <Button variant={cutVariant === 'original' ? 'ink' : 'line'} onClick={() => setConceptCutVariants((current) => ({ ...current, [concept.id]: 'original' }))}>Original cut</Button>
                        <Button variant={cutVariant === 'refined' ? 'ink' : 'line'} onClick={() => setConceptCutVariants((current) => ({ ...current, [concept.id]: 'refined' }))}>AI final cut</Button>
                      </div>
                      {cutVariant === 'refined' && (
                        <p className="text-[11px] leading-relaxed text-muted">
                          {concept.refinement_notes?.length
                            ? concept.refinement_notes.join(' ')
                            : 'No safe changes were supported by the available scene and music evidence. The original cut is preserved.'}
                        </p>
                      )}
                    </div>
                  ) : null}
                  <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
                    <span>{shots.length} shots</span>
                    <span>{totalSeconds.toFixed(1)}s total</span>
                    <span>{averageShot.toFixed(1)}s average shot</span>
                    <span>{sourceCount} source{sourceCount === 1 ? '' : 's'}</span>
                  </div>
                  {previewShots.length > 0 && (
                    <div className="flex flex-col gap-1.5">
                      <div className="flex gap-1 overflow-hidden rounded">
                        {previewShots.map((shot, index) => {
                          const duration = Math.max(0.1, shot.end_seconds - shot.start_seconds)
                          const width = totalSeconds > 0 ? Math.max(8, duration / totalSeconds * 100) : 20
                          return (
                            <div key={index} title={`Shot ${index + 1}: ${duration.toFixed(1)}s`} className="min-w-0 overflow-hidden rounded-sm bg-sunk" style={{ width: `${width}%` }}>
                              <img
                                src={`/api/runs/${runId}/campaign-frame?source_index=${shot.source_index}&timestamp=${shot.start_seconds.toFixed(1)}`}
                                alt={`Shot ${index + 1} preview`}
                                loading="lazy"
                                className="h-12 w-full object-cover"
                              />
                            </div>
                          )
                        })}
                      </div>
                      <p className="text-[10px] text-faint">Opening sequence · segment widths reflect shot duration</p>
                    </div>
                  )}
                  <div className="mt-auto flex flex-wrap gap-2 pt-1">
                    <Button variant={isSelected ? 'ink' : 'line'} disabled={isSelected} onClick={() => setSelectedConceptId(concept.id)}>
                      {isSelected ? 'Active direction' : 'Select to compare'}
                    </Button>
                    <Button variant="line" disabled={saveMontage.isPending} loading={saveMontage.isPending && isSelected} onClick={() => saveMontage.mutate(conceptEdits)}>
                      Use &amp; render
                    </Button>
                  </div>
                </article>
              )
            })}
          </div>
          <p className="text-xs text-muted">The previews use cached source-video frames, not a finished export. Selecting a direction here does not change your current edit until you choose Use &amp; render.</p>
        </section>
      )}

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
        <div id="campaign-text" className="scroll-mt-5">
        <CampaignTextOverlayEditor
          overlays={campaignTextOverlays}
          savedOverlays={data.options.campaign_text_overlays ?? []}
          outputs={readyClips.map((clip) => ({ rank: clip.rank, duration_seconds: clip.duration_seconds ?? 0, poster_url: clip.poster_url }))}
          saving={saveCampaignTextOverlays.isPending}
          onChange={setCampaignTextOverlays}
          onSave={() => saveCampaignTextOverlays.mutate()}
        />
        </div>
      )}

      {data.campaign_plan && <CampaignPlanCard plan={data.campaign_plan} checks={data.campaign_quality_checks} />}

          </div>
        </div>
      )}

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

function getBeatSnappedShotEnd(
  edit: CampaignEdit,
  shotIndex: number,
  musicAnalysis: CampaignMusicAnalysis | null,
  sourceDuration: number | undefined,
): number | null {
  const shot = edit.shots[shotIndex]
  const markers = musicAnalysis?.beat_markers ?? []
  if (!shot || !sourceDuration || markers.length === 0) return null
  const elapsed = edit.shots.slice(0, shotIndex).reduce(
    (sum, previous) => sum + Math.max(0, previous.end_seconds - previous.start_seconds),
    0,
  )
  const desired = shot.end_seconds - shot.start_seconds
  const available = sourceDuration - shot.start_seconds
  const candidates = markers
    .map((marker) => ({
      duration: marker.time_seconds - elapsed,
      score: Math.abs(marker.time_seconds - elapsed - desired) - 0.55 * marker.energy - 0.35 * marker.strength,
    }))
    .filter((candidate) => candidate.duration >= 1.5 && candidate.duration <= 5.0 && candidate.duration <= available)
    .sort((left, right) => left.score - right.score)
  if (candidates.length === 0) return null
  return Math.round((shot.start_seconds + candidates[0].duration) * 1000) / 1000
}

function CampaignStoryboardEditor({
  runId,
  edits,
  savedEdits,
  originalEdits,
  sources,
  musicAnalysis,
  musicStartSeconds,
  onMusicStartChange,
  hasMusic,
  lyricsBehindSubject,
  lyrics,
  onUpdateLyric,
  lyricWords,
  wordsOnScreen,
  lyricsColor,
  lyricsHighlightColor,
  textOverlays,
  onUpdateTextOverlay,
  transitionStyle,
  saving,
  onChange,
  onSave,
  onReset,
  hookText,
  includeHook,
  generatedHook,
  onHookTextChange,
  onIncludeHookChange,
  musicFile,
  onMusicFileChange,
  onAttachMusic,
  attachingMusic,
  musicTrackDescription,
  musicVolume,
  onMusicVolumeChange,
  musicFadeIn,
  onMusicFadeInChange,
  musicFadeOut,
  onMusicFadeOutChange,
  musicDucking,
  onMusicDuckingChange,
  sourceAudioVolume,
  onSourceAudioVolumeChange,
  musicSettingsChanged,
  sourceAudioSettingsChanged,
  savingAudio,
  savingLyrics,
  savingText,
  onSaveAudio,
  onSaveLyrics,
  onSaveText,
}: {
  runId: string
  edits: CampaignEdit[]
  savedEdits: CampaignEdit[]
  originalEdits: CampaignEdit[]
  sources: CampaignSource[]
  musicAnalysis: CampaignMusicAnalysis | null
  musicStartSeconds: number
  onMusicStartChange: (seconds: number) => void
  hasMusic: boolean
  lyricsBehindSubject: boolean
  lyrics: CampaignPreviewLyric[]
  onUpdateLyric: (phraseIndex: number, patch: Partial<CampaignLyricPhraseEdit>) => void
  lyricWords: CampaignPreviewWord[]
  wordsOnScreen: 1 | 2 | 3
  lyricsColor: string
  lyricsHighlightColor: string
  textOverlays: CampaignTextOverlay[]
  onUpdateTextOverlay: (overlayIndex: number, patch: Partial<CampaignTextOverlay>) => void
  transitionStyle: 'auto' | 'cut' | 'cinematic' | 'dynamic'
  saving: boolean
  onChange: (edits: CampaignEdit[]) => void
  onSave: () => void
  onReset: () => void
  hookText: string
  includeHook: boolean
  generatedHook: string | null
  onHookTextChange: (value: string) => void
  onIncludeHookChange: (value: boolean) => void
  musicFile: File | null
  onMusicFileChange: (file: File | null) => void
  onAttachMusic: () => void
  attachingMusic: boolean
  musicTrackDescription: string
  musicVolume: number
  onMusicVolumeChange: (value: number) => void
  musicFadeIn: number
  onMusicFadeInChange: (value: number) => void
  musicFadeOut: number
  onMusicFadeOutChange: (value: number) => void
  musicDucking: boolean
  onMusicDuckingChange: (value: boolean) => void
  sourceAudioVolume: number
  onSourceAudioVolumeChange: (value: number) => void
  musicSettingsChanged: boolean
  sourceAudioSettingsChanged: boolean
  savingAudio: boolean
  savingLyrics: boolean
  savingText: boolean
  onSaveAudio: () => void
  onSaveLyrics: () => void
  onSaveText: () => void
}) {
  const [selectedEditRank, setSelectedEditRank] = useState(edits[0]?.rank ?? 1)
  const [selectedShotIndex, setSelectedShotIndex] = useState(0)
  const [activeTool, setActiveTool] = useState<'shots' | 'hook' | 'audio' | 'lyrics' | 'titles' | 'animations'>('shots')
  const [selectedPhraseIndex, setSelectedPhraseIndex] = useState(0)
  const selectedTextOverlays = textOverlays
    .map((overlay, index) => ({ overlay, index }))
    .filter(({ overlay }) => overlay.rank === selectedEditRank)
  useEffect(() => {
    if (!edits.some((edit) => edit.rank === selectedEditRank) && edits[0]) {
      setSelectedEditRank(edits[0].rank)
      setSelectedShotIndex(0)
    }
  }, [edits, selectedEditRank])
  useEffect(() => {
    const selectedEdit = edits.find((edit) => edit.rank === selectedEditRank)
    if (!selectedEdit || selectedShotIndex >= selectedEdit.shots.length) {
      setSelectedShotIndex(Math.max(0, (selectedEdit?.shots.length ?? 1) - 1))
    }
  }, [edits, selectedEditRank, selectedShotIndex])
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
    const targetIndex = shotIndex + direction
    moveShotTo(editIndex, shotIndex, targetIndex)
    if (targetIndex >= 0 && targetIndex < edits[editIndex]?.shots.length) setSelectedShotIndex(targetIndex)
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
          <h2 id="campaign-storyboard" className="display mt-1 scroll-mt-5 text-2xl">Clip editing workspace</h2>
          <p className="mt-1 text-[13px] text-muted">
            Select a shot on the left to edit its source range. The preview and timeline stay in place while you work.
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
      <div className="flex flex-col gap-2 rounded-lg border border-line bg-panel p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="label text-muted">SELECT A CLIP TO EDIT</span>
          <span className="text-xs text-faint">{edits.length} generated clips · {shotCount} shots total</span>
        </div>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Select generated clip to edit">
          {edits.map((edit) => (
            <button
              key={edit.rank}
              type="button"
              aria-pressed={selectedEditRank === edit.rank}
              onClick={() => setSelectedEditRank(edit.rank)}
              className={cn(
                'flex min-w-[120px] flex-col items-start rounded-md border px-3 py-2 text-left transition-colors',
                selectedEditRank === edit.rank ? 'border-ink bg-sunk text-ink' : 'border-line bg-surface text-muted hover:border-line-strong hover:text-ink',
              )}
            >
              <span className="text-xs font-semibold">Clip {edit.rank}</span>
              <span className="mt-0.5 max-w-full truncate text-[11px]">{edit.title}</span>
              <span className="mt-1 text-[10px] text-faint">{edit.shots.length} shots</span>
            </button>
          ))}
        </div>
      </div>
      {edits.filter((edit) => edit.rank === selectedEditRank).map((edit) => {
        const editIndex = edits.findIndex((item) => item.rank === edit.rank)
        return (
        <section key={edit.rank} className="flex flex-col gap-3 border-t border-line pt-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-semibold">#{edit.rank} · {edit.title}</h3>
            <span className="label text-muted">{edit.shots.length} shots</span>
          </div>
          <div className="grid min-w-0 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
          <div className="min-w-0 lg:col-start-2 lg:row-start-1">
          <CampaignTimeline
            edit={edit}
            runId={runId}
            sources={sources}
            musicAnalysis={musicAnalysis}
            musicStartSeconds={musicStartSeconds}
            onMusicStartChange={onMusicStartChange}
            hasMusic={hasMusic}
            lyricsBehindSubject={lyricsBehindSubject}
            lyrics={lyrics}
            onUpdateLyric={onUpdateLyric}
            lyricWords={lyricWords}
            wordsOnScreen={wordsOnScreen}
            lyricsColor={lyricsColor}
            lyricsHighlightColor={lyricsHighlightColor}
            textOverlays={textOverlays}
            onUpdateTextOverlay={onUpdateTextOverlay}
            transitionStyle={transitionStyle}
            selectedShotIndex={selectedShotIndex}
            onSelectShot={setSelectedShotIndex}
            onMoveShot={(fromIndex, toIndex) => moveShotTo(editIndex, fromIndex, toIndex)}
            onUpdateShot={(shotIndex, patch) => updateShot(editIndex, shotIndex, patch)}
          />
          </div>
          <aside className="flex min-w-0 flex-col gap-3 rounded-lg border border-line bg-surface p-3 lg:col-start-1 lg:row-start-1">
            <div className="grid grid-cols-2 gap-1" role="group" aria-label="Clip editing tools">
              {([
                ['shots', 'Shot editing'],
                ['hook', 'Opening Hook'],
                ['audio', 'Music & audio'],
                ['lyrics', 'Lyrics sync'],
                ['titles', 'Text & titles'],
                ['animations', 'Animations'],
              ] as const).map(([tool, label]) => (
                <button key={tool} type="button" onClick={() => setActiveTool(tool)} aria-pressed={activeTool === tool}
                  className={cn('rounded-md border px-2 py-2 text-left text-[11px] font-semibold transition-colors',
                    activeTool === tool ? 'border-ink bg-sunk text-ink' : 'border-line text-muted hover:border-line-strong hover:text-ink')}>
                  {label}
                </button>
              ))}
            </div>
            {activeTool === 'shots' && (
              <>
                <div className="flex items-center justify-between gap-2">
                  <span className="label text-muted">SHOT EDITING</span>
                  <span className="text-[10px] text-faint">{edit.shots.length} clips</span>
                </div>
                <ol className="flex max-h-[min(70vh,760px)] flex-col gap-2 overflow-y-auto pr-1">
            {edit.shots.map((shot, shotIndex) => {
              const source = sourceByIndex.get(shot.source_index)
              return (
                <li id={`campaign-shot-${edit.rank}-${shotIndex}`} key={`${edit.rank}-${shotIndex}-${shot.source_index}`} className={cn('flex flex-col gap-2 rounded-lg border bg-panel p-2 transition-colors', selectedShotIndex === shotIndex ? 'border-ink ring-1 ring-ink/20' : 'border-line')}>
                  <button type="button" onClick={() => setSelectedShotIndex(shotIndex)} aria-pressed={selectedShotIndex === shotIndex} className="flex items-start gap-2 text-left">
                  <img
                    src={`/api/runs/${runId}/campaign-frame?source_index=${shot.source_index}&timestamp=${shot.start_seconds.toFixed(1)}`}
                    alt={`Preview of shot ${shotIndex + 1}`}
                    loading="lazy"
                    className="h-16 w-20 shrink-0 rounded-md border border-line bg-surface object-cover"
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
                  </button>
                  <div className="grid grid-cols-2 gap-2">
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Start (seconds)
                    <input type="number" min={0} max={source?.duration_seconds} step={0.1} value={shot.start_seconds}
                      onChange={(event) => updateShot(editIndex, shotIndex, { start_seconds: Number(event.target.value) })} disabled={saving}
                      className="w-full rounded-md border border-line bg-surface px-2 py-2 font-mono text-sm text-ink" />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    <span className="flex items-center justify-between gap-1">
                      End (seconds)
                      {(() => {
                        const snappedEnd = getBeatSnappedShotEnd(edit, shotIndex, musicAnalysis, source?.duration_seconds)
                        return (
                          <button type="button" disabled={saving || snappedEnd === null}
                            onClick={() => snappedEnd !== null && updateShot(editIndex, shotIndex, { end_seconds: snappedEnd })}
                            className="rounded border border-line px-1.5 py-0.5 text-[10px] text-ink hover:bg-surface disabled:opacity-30"
                            title="Align this shot's end with the nearest suitable music beat">
                            Snap to beat
                          </button>
                        )
                      })()}
                    </span>
                    <input type="number" min={0} max={source?.duration_seconds} step={0.1} value={shot.end_seconds}
                      onChange={(event) => updateShot(editIndex, shotIndex, { end_seconds: Number(event.target.value) })} disabled={saving}
                      className="w-full rounded-md border border-line bg-surface px-2 py-2 font-mono text-sm text-ink" />
                  </label>
                  </div>
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
              </>
            )}
            {activeTool === 'hook' && (
              <div className="flex flex-col gap-3 text-xs">
                <div>
                  <p className="font-semibold text-ink">Opening text hook</p>
                  <p className="mt-1 text-muted">Add a short opening line to catch attention at the start of this campaign video.</p>
                </div>
                <label className="flex items-center justify-between gap-3 rounded-md border border-line bg-panel p-2 text-ink">
                  <span className="font-medium">Include hook in video</span>
                  <input type="checkbox" checked={includeHook} onChange={(event) => onIncludeHookChange(event.target.checked)} />
                </label>
                {generatedHook && (
                  <div className="rounded-md border border-line bg-panel p-2">
                    <p className="font-semibold text-ink">AI suggestion</p>
                    <p className="mt-1 text-muted">{generatedHook}</p>
                    <button type="button" onClick={() => onHookTextChange(generatedHook)}
                      className="mt-2 rounded border border-line px-2 py-1.5 font-semibold text-ink">Use suggestion</button>
                  </div>
                )}
                <label className="flex flex-col gap-1 text-muted">Opening text · {hookText.length}/160
                  <textarea value={hookText} onChange={(event) => onHookTextChange(event.target.value)} rows={3} maxLength={160}
                    placeholder="Write your opening hook…" className="resize-y rounded-md border border-line bg-panel p-2 text-ink" />
                </label>
                <p className="text-muted">Leave it disabled if you want the video to open directly on the footage.</p>
                <button type="button" onClick={onSaveLyrics} disabled={savingLyrics}
                  className="rounded-md bg-ink px-3 py-2 font-semibold text-white disabled:opacity-40">{savingLyrics ? 'Applying…' : 'Apply opening hook'}</button>
              </div>
            )}
            {activeTool === 'audio' && (
              <div className="flex flex-col gap-3 text-xs">
                <div>
                  <p className="font-semibold text-ink">Music alignment</p>
                  <p className="mt-1 text-muted">Move the attached soundtrack start. The preview and timeline follow this offset.</p>
                </div>
                <label className="flex flex-col gap-2">
                  <span className="flex justify-between gap-2 text-muted"><span>Track start</span><span className="font-mono">{formatDuration(musicStartSeconds)}</span></span>
                  <input type="range" min={0} max={Math.max(1, musicAnalysis?.duration_seconds ?? musicStartSeconds + 30)} step={0.1}
                    value={musicStartSeconds} onChange={(event) => onMusicStartChange(Number(event.target.value))} disabled={!hasMusic}
                    className="w-full accent-current" />
                </label>
                {musicAnalysis && (
                  <div className="rounded-md border border-line bg-panel p-2 text-muted">
                    <p>Track length: {formatDuration(musicAnalysis.duration_seconds)}</p>
                    <p>Detected beats: {musicAnalysis.detected_beats}{musicAnalysis.estimated_bpm ? ` · ${Math.round(musicAnalysis.estimated_bpm)} BPM` : ''}</p>
                    <p className="mt-1">Suggested start: {formatDuration(musicAnalysis.selected_start_seconds)}</p>
                    <button type="button" onClick={() => onMusicStartChange(musicAnalysis.selected_start_seconds)} disabled={!hasMusic}
                      className="mt-2 rounded border border-line px-2 py-1.5 font-semibold text-ink disabled:opacity-40">Use suggested start</button>
                  </div>
                )}
                {!hasMusic && <p className="rounded-md border border-dashed border-line p-2 text-muted">Attach a music track in the Music & Audio section below to enable soundtrack alignment.</p>}
                <div className="mt-2 flex flex-col gap-3 rounded-md border border-line bg-panel p-3">
                  <div><p className="font-semibold text-ink">Soundtrack</p><p className="mt-1 text-muted">{musicTrackDescription}</p></div>
                  <label className="flex flex-col gap-1 text-muted">Choose audio file
                    <input type="file" accept="audio/*" onChange={(event) => onMusicFileChange(event.target.files?.[0] ?? null)}
                      className="block w-full text-xs text-muted file:mr-2 file:rounded file:border file:border-line file:bg-surface file:px-2 file:py-2 file:text-ink" />
                  </label>
                  <button type="button" onClick={onAttachMusic} disabled={!musicFile || attachingMusic}
                    className="rounded-md border border-line px-3 py-2 font-semibold text-ink disabled:opacity-40">
                    {attachingMusic ? 'Attaching track…' : hasMusic ? 'Replace soundtrack' : 'Attach soundtrack'}
                  </button>
                  {hasMusic && <>
                    <label className="flex flex-col gap-1 text-muted">Music volume · {musicVolume}%
                      <input type="range" min={0} max={200} step={5} value={musicVolume} onChange={(event) => onMusicVolumeChange(Number(event.target.value))} />
                    </label>
                    <label className="flex flex-col gap-1 text-muted">Fade in · {musicFadeIn.toFixed(1)}s
                      <input type="range" min={0} max={5} step={0.1} value={musicFadeIn} onChange={(event) => onMusicFadeInChange(Number(event.target.value))} />
                    </label>
                    <label className="flex flex-col gap-1 text-muted">Fade out · {musicFadeOut.toFixed(1)}s
                      <input type="range" min={0} max={5} step={0.1} value={musicFadeOut} onChange={(event) => onMusicFadeOutChange(Number(event.target.value))} />
                    </label>
                    <label className="flex items-start gap-2 rounded border border-line bg-surface p-2 text-muted">
                      <input type="checkbox" checked={musicDucking} onChange={(event) => onMusicDuckingChange(event.target.checked)} />
                      <span>Auto-duck music under original speech and source audio</span>
                    </label>
                  </>}
                  <label className="flex flex-col gap-1 text-muted">Original video audio · {sourceAudioVolume}%
                    <input type="range" min={0} max={200} step={5} value={sourceAudioVolume} onChange={(event) => onSourceAudioVolumeChange(Number(event.target.value))} />
                  </label>
                  <button type="button" onClick={onSaveAudio} disabled={savingAudio || (!musicSettingsChanged && !sourceAudioSettingsChanged)}
                    className="rounded-md bg-ink px-3 py-2 font-semibold text-white disabled:opacity-40">
                    {savingAudio ? 'Applying audio mix…' : 'Apply audio mix & re-render'}
                  </button>
                </div>
              </div>
            )}
            {activeTool === 'lyrics' && (
              <div className="flex flex-col gap-3 text-xs">
                <div>
                  <p className="font-semibold text-ink">Phrase placement</p>
                  <p className="mt-1 text-muted">Choose a lyric phrase and adjust its position on the video.</p>
                </div>
                {lyrics.length === 0 ? <p className="rounded-md border border-dashed border-line p-2 text-muted">Add timed lyrics in the Lyrics Sync section to edit phrase placement here.</p> : (
                  <>
                    <label className="flex flex-col gap-1 text-muted">Lyric phrase
                      <select value={selectedPhraseIndex} onChange={(event) => setSelectedPhraseIndex(Number(event.target.value))}
                        className="rounded-md border border-line bg-panel px-2 py-2 text-ink">
                        {lyrics.map((phrase) => <option key={phrase.phrase_index} value={phrase.phrase_index}>{phrase.text.slice(0, 42) || `Phrase ${phrase.phrase_index + 1}`}</option>)}
                      </select>
                    </label>
                    {(() => {
                      const phrase = lyrics.find((item) => item.phrase_index === selectedPhraseIndex) ?? lyrics[0]
                      return (
                        <div className="flex flex-col gap-3">
                          <p className="rounded-md bg-panel p-2 text-muted">{phrase.text}</p>
                          <label className="flex flex-col gap-1 text-muted">Horizontal · {phrase.position_x}%
                            <input type="range" min={5} max={95} value={phrase.position_x}
                              onChange={(event) => onUpdateLyric(phrase.phrase_index, { position_x: Number(event.target.value) })} />
                          </label>
                          <label className="flex flex-col gap-1 text-muted">Vertical · {phrase.position_y}%
                            <input type="range" min={5} max={95} value={phrase.position_y}
                              onChange={(event) => onUpdateLyric(phrase.phrase_index, { position_y: Number(event.target.value) })} />
                          </label>
                          <label className="flex flex-col gap-1 text-muted">Scale · {phrase.scale_percent}%
                            <input type="range" min={50} max={180} step={5} value={phrase.scale_percent}
                              onChange={(event) => onUpdateLyric(phrase.phrase_index, { scale_percent: Number(event.target.value) })} />
                          </label>
                        </div>
                      )
                    })()}
                  </>
                )}
                <button type="button" onClick={onSaveLyrics} disabled={savingLyrics || lyrics.length === 0}
                  className="rounded-md bg-ink px-3 py-2 font-semibold text-white disabled:opacity-40">{savingLyrics ? 'Applying…' : 'Apply lyric changes'}</button>
              </div>
            )}
            {(activeTool === 'titles' || activeTool === 'animations') && (
              <div className="flex flex-col gap-3 text-xs">
                <div>
                  <p className="font-semibold text-ink">{activeTool === 'titles' ? 'Text layers' : 'Text animations'}</p>
                  <p className="mt-1 text-muted">{activeTool === 'titles' ? 'Edit the title layers attached to this clip.' : 'Choose an entrance animation for each title layer.'}</p>
                </div>
                {selectedTextOverlays.length === 0 ? <p className="rounded-md border border-dashed border-line p-2 text-muted">No text layers are assigned to this clip yet. Add one in Text & Titles below.</p> : selectedTextOverlays.map(({ overlay, index }) => (
                  <div key={index} className="flex flex-col gap-2 rounded-md border border-line bg-panel p-2">
                    {activeTool === 'titles' ? (
                      <>
                        <label className="flex flex-col gap-1 text-muted">Title text
                          <input value={overlay.text} maxLength={160} onChange={(event) => onUpdateTextOverlay(index, { text: event.target.value })}
                            className="rounded border border-line bg-surface px-2 py-2 text-ink" />
                        </label>
                        <label className="flex flex-col gap-1 text-muted">Starts · {formatDuration(overlay.start_seconds)}
                          <input type="range" min={0} max={Math.max(0.1, overlay.end_seconds - 0.1)} step={0.1} value={overlay.start_seconds}
                            onChange={(event) => onUpdateTextOverlay(index, { start_seconds: Number(event.target.value) })} />
                        </label>
                      </>
                    ) : (
                      <label className="flex flex-col gap-1 text-muted">Entrance animation
                        <select value={overlay.animation} onChange={(event) => onUpdateTextOverlay(index, { animation: event.target.value as CampaignTextOverlay['animation'] })}
                          className="rounded border border-line bg-surface px-2 py-2 text-ink">
                          <option value="none">None</option><option value="fade">Fade</option><option value="pop">Pop</option><option value="slide">Slide up</option>
                        </select>
                      </label>
                    )}
                  </div>
                ))}
                <button type="button" onClick={onSaveText} disabled={savingText}
                  className="rounded-md bg-ink px-3 py-2 font-semibold text-white disabled:opacity-40">{savingText ? 'Applying…' : 'Apply text changes'}</button>
              </div>
            )}
          </aside>
          </div>
          {edit.shots.length < 3 && <p className="text-xs text-bad">Restore the AI plan or keep at least 3 shots in this output.</p>}
        </section>
        )
      })}
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
  const [selectedIndex, setSelectedIndex] = useState(0)
  useEffect(() => {
    if (selectedIndex >= overlays.length) setSelectedIndex(Math.max(0, overlays.length - 1))
  }, [overlays.length, selectedIndex])
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
        font_family: 'Arial',
        font_weight: 'bold',
        text_effect: 'shadow',
        color: '#FFFFFF',
        animation: 'fade',
        background: true,
      },
    ])
  }
  const update = (index: number, patch: Partial<CampaignTextOverlay>) => {
    onChange(overlays.map((overlay, position) => position === index ? { ...overlay, ...patch } : overlay))
  }
  const duplicate = (index: number) => {
    if (overlays.length >= 30) return
    const source = overlays[index]
    if (!source) return
    const sameRank = overlays.filter((overlay) => overlay.rank === source.rank)
    const nextLayer = Math.max(-1, ...sameRank.map((overlay, position) => overlay.z_index ?? position)) + 1
    const copy = {
      ...source,
      text: source.text ? `${source.text} copy`.slice(0, 160) : 'YOUR MESSAGE',
      position_x: Math.min(95, source.position_x + 3),
      position_y: Math.min(95, source.position_y + 3),
      z_index: nextLayer,
    }
    const next = [...overlays]
    next.splice(index + 1, 0, copy)
    onChange(next)
    setSelectedIndex(index + 1)
  }
  const moveLayer = (index: number, direction: -1 | 1) => {
    const selected = overlays[index]
    if (!selected) return
    const sameRank = overlays
      .map((overlay, position) => ({ overlay, position }))
      .filter(({ overlay }) => overlay.rank === selected.rank)
      .sort((a, b) => (a.overlay.z_index ?? a.position) - (b.overlay.z_index ?? b.position))
    const order = sameRank.findIndex(({ position }) => position === index)
    const target = order + direction
    if (order < 0 || target < 0 || target >= sameRank.length) return
    const reordered = [...sameRank]
    ;[reordered[order], reordered[target]] = [reordered[target], reordered[order]]
    const layers = new Map(reordered.map(({ position }, layer) => [position, layer]))
    onChange(overlays.map((overlay, position) => overlay.rank === selected.rank
      ? { ...overlay, z_index: layers.get(position) ?? overlay.z_index ?? 0 }
      : overlay))
  }
  const alignX = (index: number, position_x: number) => update(index, { position_x })
  const alignY = (index: number, position_y: number) => update(index, { position_y })

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
              <section
                key={index}
                onClick={() => setSelectedIndex(index)}
                className={cn('flex flex-col gap-3 rounded-lg border p-3 transition-colors', selectedIndex === index ? 'border-ink bg-sunk/40' : 'border-line bg-panel')}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <button type="button" onClick={() => setSelectedIndex(index)} aria-pressed={selectedIndex === index}
                    className="label text-left text-muted hover:text-ink">
                    {selectedIndex === index ? 'SELECTED · ' : ''}TEXT LAYER {String(index + 1).padStart(2, '0')}
                  </button>
                  <div className="flex flex-wrap gap-1.5">
                    <button type="button" disabled={saving || overlays.length >= 30} onClick={(event) => { event.stopPropagation(); duplicate(index) }}
                      className="rounded-md border border-line px-2.5 py-1.5 text-xs text-muted hover:text-ink disabled:opacity-40">Duplicate</button>
                    <button type="button" disabled={saving || !overlays.some((item, position) => item.rank === overlay.rank && (item.z_index ?? position) < (overlay.z_index ?? index))} onClick={(event) => { event.stopPropagation(); moveLayer(index, -1) }}
                      className="rounded-md border border-line px-2.5 py-1.5 text-xs text-muted hover:text-ink disabled:opacity-40">Send backward</button>
                    <button type="button" disabled={saving || !overlays.some((item, position) => item.rank === overlay.rank && (item.z_index ?? position) > (overlay.z_index ?? index))} onClick={(event) => { event.stopPropagation(); moveLayer(index, 1) }}
                      className="rounded-md border border-line px-2.5 py-1.5 text-xs text-muted hover:text-ink disabled:opacity-40">Bring forward</button>
                    <button type="button" disabled={saving} onClick={(event) => { event.stopPropagation(); onChange(overlays.filter((_, position) => position !== index)); setSelectedIndex(Math.max(0, Math.min(index, overlays.length - 2))) }}
                      className="rounded-md border border-line px-2.5 py-1.5 text-xs text-muted hover:text-bad disabled:opacity-40">Remove</button>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface p-2">
                  <span className="label mr-1 text-faint">ALIGN POSITION</span>
                  {([['Left', 10], ['Center', 50], ['Right', 90]] as const).map(([label, value]) => (
                    <button key={label} type="button" disabled={saving} onClick={() => alignX(index, value)}
                      aria-pressed={overlay.position_x === value}
                      className={cn('rounded border px-2.5 py-1.5 text-xs', overlay.position_x === value ? 'border-ink bg-sunk text-ink' : 'border-line text-muted hover:text-ink')}>{label}</button>
                  ))}
                  <span className="mx-1 h-5 border-l border-line" />
                  {([['Top', 10], ['Middle', 50], ['Bottom', 90]] as const).map(([label, value]) => (
                    <button key={label} type="button" disabled={saving} onClick={() => alignY(index, value)}
                      aria-pressed={overlay.position_y === value}
                      className={cn('rounded border px-2.5 py-1.5 text-xs', overlay.position_y === value ? 'border-ink bg-sunk text-ink' : 'border-line text-muted hover:text-ink')}>{label}</button>
                  ))}
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
                  <div className="flex flex-col gap-2 text-xs text-muted sm:col-span-2">
                    <span>Entrance animation · live previews</span>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {([
                        ['none', 'None', 'text-animation-none'],
                        ['fade', 'Fade', 'text-animation-fade'],
                        ['pop', 'Pop', 'text-animation-pop'],
                        ['slide', 'Slide up', 'text-animation-slide'],
                      ] as const).map(([value, title, previewClass]) => (
                        <button key={value} type="button" onClick={() => update(index, { animation: value })}
                          aria-pressed={overlay.animation === value}
                          className={cn('flex flex-col items-center gap-2 rounded-md border p-2 transition-colors',
                            overlay.animation === value ? 'border-ink bg-sunk' : 'border-line bg-surface hover:border-line-strong')}>
                          <span className={cn('text-animation-preview', previewClass)}>{overlay.text.trim().slice(0, 12) || 'TITLE'}</span>
                          <span className="font-medium text-ink">{title}</span>
                          {overlay.animation === value && <span className="text-[9px] font-semibold uppercase tracking-wider text-ok">Selected</span>}
                        </button>
                      ))}
                    </div>
                  </div>
                  <label className="flex items-center gap-2 text-xs text-muted">
                    <input type="checkbox" checked={overlay.background}
                      onChange={(event) => update(index, { background: event.target.checked })} />
                    Background panel
                  </label>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Font family
                    <select value={overlay.font_family ?? 'Arial'} onChange={(event) => update(index, { font_family: event.target.value as CampaignTextOverlay['font_family'] })}
                      className="rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
                      <option value="Arial">Arial · clean</option>
                      <option value="Georgia">Georgia · editorial</option>
                      <option value="Impact">Impact · bold display</option>
                      <option value="Trebuchet MS">Trebuchet MS · modern</option>
                      <option value="Verdana">Verdana · readable</option>
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Font weight
                    <select value={overlay.font_weight ?? 'bold'} onChange={(event) => update(index, { font_weight: event.target.value as CampaignTextOverlay['font_weight'] })}
                      className="rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
                      <option value="regular">Regular</option>
                      <option value="bold">Bold</option>
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-muted">
                    Text effect
                    <select value={overlay.text_effect ?? 'shadow'} onChange={(event) => update(index, { text_effect: event.target.value as CampaignTextOverlay['text_effect'] })}
                      className="rounded-md border border-line bg-surface px-2 py-2 text-sm text-ink">
                      <option value="none">None</option>
                      <option value="shadow">Soft shadow</option>
                      <option value="outline">Outline</option>
                    </select>
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
  musicStartSeconds,
  onMusicStartChange,
  hasMusic,
  lyricsBehindSubject,
  lyrics,
  onUpdateLyric,
  lyricWords,
  wordsOnScreen,
  lyricsColor,
  lyricsHighlightColor,
  textOverlays,
  onUpdateTextOverlay,
  transitionStyle,
  selectedShotIndex,
  onSelectShot,
  onMoveShot,
  onUpdateShot,
}: {
  edit: CampaignEdit
  runId: string
  sources: CampaignSource[]
  musicAnalysis: CampaignMusicAnalysis | null
  musicStartSeconds: number
  onMusicStartChange: (seconds: number) => void
  hasMusic: boolean
  lyricsBehindSubject: boolean
  lyrics: CampaignPreviewLyric[]
  onUpdateLyric: (phraseIndex: number, patch: Partial<CampaignLyricPhraseEdit>) => void
  lyricWords: CampaignPreviewWord[]
  wordsOnScreen: 1 | 2 | 3
  lyricsColor: string
  lyricsHighlightColor: string
  textOverlays: CampaignTextOverlay[]
  onUpdateTextOverlay: (overlayIndex: number, patch: Partial<CampaignTextOverlay>) => void
  transitionStyle: 'auto' | 'cut' | 'cinematic' | 'dynamic'
  selectedShotIndex: number
  onSelectShot: (index: number) => void
  onMoveShot: (fromIndex: number, toIndex: number) => void
  onUpdateShot: (shotIndex: number, patch: Partial<CampaignShot>) => void
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const pendingSeekRef = useRef<number | null>(null)
  const seekToTimelineRef = useRef<(seconds: number) => void>(() => undefined)
  const advancingShotRef = useRef(false)
  const transitionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [transitionPhase, setTransitionPhase] = useState<'idle' | 'out' | 'in'>('idle')
  const [previewTransitionStyle, setPreviewTransitionStyle] = useState(transitionStyle)
  const [previewLyricAnimation, setPreviewLyricAnimation] = useState<CampaignLyricPhraseEdit['animation_style']>('dynamic')
  const [previewTextAnimation, setPreviewTextAnimation] = useState<CampaignTextOverlay['animation']>('pop')
  const [positioningTarget, setPositioningTarget] = useState<'none' | 'lyric' | 'text'>('none')
  const [snapTextToGuides, setSnapTextToGuides] = useState(true)
  const [alignmentGuides, setAlignmentGuides] = useState<{ vertical: number | null; horizontal: number | null }>({
    vertical: null,
    horizontal: null,
  })
  const positionDragRef = useRef<{ pointerId: number; target: 'lyric' | 'text' } | null>(null)
  const transformDragRef = useRef<{ pointerId: number; target: 'lyric' | 'text'; action: 'resize' | 'rotate'; startX: number; initialValue: number } | null>(null)
  useEffect(() => setPreviewTransitionStyle(transitionStyle), [transitionStyle])
  const transitionDurationMs = previewTransitionStyle === 'cut' || (previewTransitionStyle === 'auto' && (musicAnalysis?.detected_beats ?? 0) > 0) ? 0 : 240
  useEffect(() => () => {
    if (transitionTimerRef.current) clearTimeout(transitionTimerRef.current)
  }, [])
  const [isPlaying, setIsPlaying] = useState(false)
  const [playheadSeconds, setPlayheadSeconds] = useState(0)
  const [maskTimestamp, setMaskTimestamp] = useState(0)
  const updateLiveTextPosition = (event: ReactPointerEvent<HTMLDivElement>, target: 'lyric' | 'text') => {
    const stage = event.currentTarget.closest('[data-campaign-preview-stage]') as HTMLDivElement | null
    const bounds = stage?.getBoundingClientRect()
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) return
    const rawX = Math.max(5, Math.min(95, ((event.clientX - bounds.left) / bounds.width) * 100))
    const rawY = Math.max(5, Math.min(95, ((event.clientY - bounds.top) / bounds.height) * 100))
    const snapAxis = (value: number) => {
      if (!snapTextToGuides) return { value: Math.round(value), guide: null as number | null }
      const nearest = [25, 50, 75].reduce((best, candidate) =>
        Math.abs(candidate - value) < Math.abs(best - value) ? candidate : best
      )
      return Math.abs(nearest - value) <= 2.5
        ? { value: nearest, guide: nearest }
        : { value: Math.round(value), guide: null as number | null }
    }
    const snappedX = snapAxis(rawX)
    const snappedY = snapAxis(rawY)
    const x = snappedX.value
    const y = snappedY.value
    setAlignmentGuides({ vertical: snappedX.guide, horizontal: snappedY.guide })
    if (target === 'lyric') {
      const lyric = lyrics.find((item) => playheadSeconds >= item.start_seconds && playheadSeconds <= item.end_seconds)
      if (lyric) onUpdateLyric(lyric.phrase_index, { position_x: x, position_y: y })
    } else {
      const overlayIndex = textOverlays.findIndex((item) =>
        item.rank === edit.rank && playheadSeconds >= item.start_seconds && playheadSeconds <= item.end_seconds
      )
      if (overlayIndex >= 0) onUpdateTextOverlay(overlayIndex, { position_x: x, position_y: y })
    }
  }
  const beginLiveTextDrag = (event: ReactPointerEvent<HTMLDivElement>, target: 'lyric' | 'text') => {
    if (positioningTarget !== target) return
    event.preventDefault()
    event.stopPropagation()
    positionDragRef.current = { pointerId: event.pointerId, target }
    event.currentTarget.setPointerCapture(event.pointerId)
    updateLiveTextPosition(event, target)
  }
  const beginTransformDrag = (
    event: ReactPointerEvent<HTMLButtonElement>,
    target: 'lyric' | 'text',
    action: 'resize' | 'rotate',
    initialValue: number,
  ) => {
    event.preventDefault()
    event.stopPropagation()
    transformDragRef.current = { pointerId: event.pointerId, target, action, startX: event.clientX, initialValue }
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const moveLiveTextDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const transformDrag = transformDragRef.current
    if (transformDrag?.pointerId === event.pointerId) {
      const stage = event.currentTarget.closest('[data-campaign-preview-stage]') as HTMLDivElement | null
      const width = stage?.getBoundingClientRect().width ?? 0
      if (width <= 0) return
      const delta = event.clientX - transformDrag.startX
      if (transformDrag.target === 'lyric') {
        const phrase = lyrics.find((item) => playheadSeconds >= item.start_seconds && playheadSeconds <= item.end_seconds)
        if (!phrase) return
        const value = transformDrag.action === 'resize'
          ? Math.max(50, Math.min(200, Math.round(transformDrag.initialValue + delta / width * 180)))
          : Math.max(-30, Math.min(30, Math.round(transformDrag.initialValue + delta / width * 90)))
        onUpdateLyric(phrase.phrase_index, transformDrag.action === 'resize' ? { scale_percent: value } : { rotation_degrees: value })
      } else {
        const overlayIndex = textOverlays.findIndex((item) =>
          item.rank === edit.rank && playheadSeconds >= item.start_seconds && playheadSeconds <= item.end_seconds
        )
        if (overlayIndex < 0) return
        const value = transformDrag.action === 'resize'
          ? Math.max(60, Math.min(200, Math.round(transformDrag.initialValue + delta / width * 180)))
          : Math.max(-30, Math.min(30, Math.round(transformDrag.initialValue + delta / width * 90)))
        onUpdateTextOverlay(overlayIndex, transformDrag.action === 'resize' ? { font_size_percent: value } : { rotation_degrees: value })
      }
      return
    }
    const drag = positionDragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    updateLiveTextPosition(event, drag.target)
  }
  const endLiveTextDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (positionDragRef.current?.pointerId === event.pointerId) positionDragRef.current = null
    if (transformDragRef.current?.pointerId === event.pointerId) transformDragRef.current = null
    setAlignmentGuides({ vertical: null, horizontal: null })
  }
  const waveformQuery = useQuery({
    queryKey: ['campaign-waveform', runId],
    queryFn: () => api.campaignWaveform(runId),
    enabled: hasMusic,
    staleTime: Infinity,
  })
  const [activeLyricTrim, setActiveLyricTrim] = useState<{
    pointerId: number
    phraseIndex: number
    side: 'move' | 'start' | 'end'
    startX: number
    initialStart: number
    initialEnd: number
    trackWidth: number
    initialTotal: number
  } | null>(null)
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
    // Timeline duration is the selected source range; export may overlap shots for transitions.
    duration: Math.max(0.1, shot.end_seconds - shot.start_seconds),
  }))
  const total = Math.max(0.1, shots.reduce((sum, item) => sum + item.duration, 0))
  const musicStart = Math.max(0, musicStartSeconds)
  useEffect(() => {
    const selected = edit.shots[selectedShotIndex]
    if (!selected) return
    const timelineStart = edit.shots.slice(0, selectedShotIndex).reduce(
      (sum, shot) => sum + Math.max(0.1, shot.end_seconds - shot.start_seconds),
      0,
    )
    videoRef.current?.pause()
    audioRef.current?.pause()
    setIsPlaying(false)
    pendingSeekRef.current = selected.start_seconds
    if (videoRef.current && videoRef.current.readyState >= 1) {
      videoRef.current.currentTime = selected.start_seconds
      pendingSeekRef.current = null
    }
    if (audioRef.current) audioRef.current.currentTime = musicStart + timelineStart
    setPlayheadSeconds(timelineStart)
  }, [selectedShotIndex, edit.shots, musicStart])
  const waveform = waveformQuery.data
  const waveformPeaks = waveform && waveform.duration_seconds > 0
    ? waveform.peaks.slice(
      Math.max(0, Math.floor((musicStart / waveform.duration_seconds) * waveform.peaks.length)),
      Math.min(waveform.peaks.length, Math.ceil(((musicStart + total) / waveform.duration_seconds) * waveform.peaks.length)),
    )
    : []

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-line bg-panel p-3">
      <div className="flex items-center justify-between gap-3">
        <span className="label text-muted">Video timeline · drag shots to reorder</span>
        <span className="font-mono text-[11px] text-faint">{formatDuration(total)} estimated</span>
      </div>
      {shots.length > 0 && (() => {
        const preview = shots[selectedShotIndex] ?? shots[0]
        const dynamicTransitionNames = ['fade', 'smoothleft', 'smoothright', 'wipeleft', 'wiperight', 'slideleft', 'slideright']
        const activeTransition = previewTransitionStyle === 'dynamic' ? dynamicTransitionNames[Math.max(0, preview.index - 1) % dynamicTransitionNames.length] : 'fade'
        const source = sourceByIndex.get(preview.shot.source_index)
        const shotTimelineStart = shots.slice(0, preview.index).reduce((sum, item) => sum + item.duration, 0)
        const activeOverlayIndex = textOverlays.findIndex((overlay) =>
          overlay.rank === edit.rank && playheadSeconds >= overlay.start_seconds && playheadSeconds <= overlay.end_seconds
        )
        const activeOverlay = activeOverlayIndex >= 0 ? textOverlays[activeOverlayIndex] : undefined
        const activeLyric = lyrics.find((lyric) =>
          playheadSeconds >= lyric.start_seconds && playheadSeconds <= lyric.end_seconds
        )
        const activeWordIndex = lyricWords.findIndex((word) =>
          playheadSeconds >= word.start_seconds && playheadSeconds < word.end_seconds
        )
        const wordWindowStart = activeWordIndex < 0 ? 0 : Math.max(0, activeWordIndex - Math.floor((wordsOnScreen - 1) / 2))
        const activeWordWindow = activeWordIndex < 0 ? [] : lyricWords.slice(wordWindowStart, wordWindowStart + wordsOnScreen)
        const subjectMaskUrl = lyricsBehindSubject
          ? "/api/runs/" + runId + "/campaign-mask?source_index=" + preview.shot.source_index + "&timestamp=" + maskTimestamp.toFixed(2)
          : null
        const seekToTimeline = (targetSeconds: number) => {
          if (transitionTimerRef.current) clearTimeout(transitionTimerRef.current)
          transitionTimerRef.current = null
          advancingShotRef.current = false
          setTransitionPhase('idle')
          const boundedTime = Math.max(0, Math.min(total, targetSeconds))
          let elapsed = 0
          let targetIndex = Math.max(0, shots.length - 1)
          let localOffset = 0
          for (const item of shots) {
            if (boundedTime <= elapsed + item.duration || item.index === shots.length - 1) {
              targetIndex = item.index
              localOffset = Math.max(0, Math.min(item.duration, boundedTime - elapsed))
              break
            }
            elapsed += item.duration
          }
          const targetShot = shots[targetIndex]
          const sourceTime = targetShot.shot.start_seconds + localOffset
          pendingSeekRef.current = sourceTime
          setPlayheadSeconds(boundedTime)
          if (targetIndex !== preview.index) {
            onSelectShot(targetIndex)
          } else if (videoRef.current) {
            videoRef.current.currentTime = sourceTime
            pendingSeekRef.current = null
          }
          if (audioRef.current) audioRef.current.currentTime = musicStart + boundedTime
        }
        seekToTimelineRef.current = seekToTimeline
        const selectShot = (index: number) => {
          if (transitionTimerRef.current) clearTimeout(transitionTimerRef.current)
          transitionTimerRef.current = null
          advancingShotRef.current = false
          setTransitionPhase('idle')
          const bounded = Math.max(0, Math.min(shots.length - 1, index))
          const start = shots.slice(0, bounded).reduce((sum, item) => sum + item.duration, 0)
          videoRef.current?.pause()
          audioRef.current?.pause()
          setIsPlaying(false)
          seekToTimeline(start)
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
          <div className="flex flex-col gap-3 rounded-md border border-line bg-surface p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <span className="label text-muted">Try transitions on your footage</span>
                <p className="mt-1 text-[11px] text-muted">Preview-only · does not change your saved edit or final export</p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {([
                  ['auto', 'Auto'],
                  ['cut', 'Clean cut'],
                  ['cinematic', 'Cinematic'],
                  ['dynamic', 'Dynamic'],
                ] as const).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={previewTransitionStyle === value}
                    onClick={() => {
                      videoRef.current?.pause()
                      audioRef.current?.pause()
                      setIsPlaying(false)
                      if (transitionTimerRef.current) clearTimeout(transitionTimerRef.current)
                      transitionTimerRef.current = null
                      advancingShotRef.current = false
                      setTransitionPhase('idle')
                      setPreviewTransitionStyle(value)
                    }}
                    className={cn(
                      'rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors',
                      previewTransitionStyle === value ? 'border-ink bg-ink text-white' : 'border-line bg-panel text-muted hover:border-ink hover:text-ink',
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <style>{`
              @keyframes clipyyy-lyric-pop { 0% { opacity: 0; transform: scale(.55); } 68% { opacity: 1; transform: scale(1.12); } 100% { opacity: 1; transform: scale(1); } }
              @keyframes clipyyy-lyric-fade { from { opacity: 0; transform: translateY(9px); } to { opacity: 1; transform: translateY(0); } }
              @keyframes clipyyy-lyric-karaoke { from { opacity: .25; clip-path: inset(0 100% 0 0); } to { opacity: 1; clip-path: inset(0 0 0 0); } }
              @keyframes clipyyy-text-pop { 0% { opacity: 0; transform: scale(.65); } 70% { opacity: 1; transform: scale(1.08); } 100% { opacity: 1; transform: scale(1); } }
              @keyframes clipyyy-text-fade { from { opacity: 0; } to { opacity: 1; } }
              @keyframes clipyyy-text-slide { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: translateY(0); } }
            `}</style>
            <div className="grid gap-3 rounded-md border border-line bg-panel p-3 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <div>
                  <span className="text-xs font-semibold text-ink">Try lyric animations on your footage</span>
                  <p className="text-[11px] text-muted">Preview-only · apply to the current phrase when it looks right</p>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {([
                    ['dynamic', 'Pop punch'],
                    ['cinematic', 'Cinematic fade'],
                    ['minimal', 'Minimal'],
                    ['karaoke', 'Karaoke'],
                  ] as const).map(([value, label]) => (
                    <button key={value} type="button" aria-pressed={previewLyricAnimation === value}
                      onClick={() => setPreviewLyricAnimation(value)}
                      className={cn('rounded-md border px-2.5 py-1.5 text-xs font-medium',
                        previewLyricAnimation === value ? 'border-ink bg-ink text-white' : 'border-line bg-surface text-muted hover:border-ink')}>
                      {label}
                    </button>
                  ))}
                </div>
                <button type="button" disabled={!activeLyric}
                  onClick={() => activeLyric && onUpdateLyric(activeLyric.phrase_index, { animation_style: previewLyricAnimation })}
                  className="self-start rounded-md border border-line px-3 py-1.5 text-xs font-semibold text-ink disabled:cursor-not-allowed disabled:opacity-40">
                  Apply to current lyric phrase
                </button>
              </div>
              <div className="flex flex-col gap-2">
                <div>
                  <span className="text-xs font-semibold text-ink">Try title animations on your footage</span>
                  <p className="text-[11px] text-muted">Preview-only · apply to the active text layer separately</p>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {([
                    ['none', 'None'],
                    ['fade', 'Fade'],
                    ['pop', 'Pop'],
                    ['slide', 'Slide up'],
                  ] as const).map(([value, label]) => (
                    <button key={value} type="button" aria-pressed={previewTextAnimation === value}
                      onClick={() => setPreviewTextAnimation(value)}
                      className={cn('rounded-md border px-2.5 py-1.5 text-xs font-medium',
                        previewTextAnimation === value ? 'border-ink bg-ink text-white' : 'border-line bg-surface text-muted hover:border-ink')}>
                      {label}
                    </button>
                  ))}
                </div>
                <button type="button" disabled={activeOverlayIndex < 0}
                  onClick={() => activeOverlayIndex >= 0 && onUpdateTextOverlay(activeOverlayIndex, { animation: previewTextAnimation })}
                  className="self-start rounded-md border border-line px-3 py-1.5 text-xs font-semibold text-ink disabled:cursor-not-allowed disabled:opacity-40">
                  Apply to active text layer
                </button>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-panel p-3">
              <span className="mr-1 text-xs font-semibold text-ink">Position text on the video</span>
              <button type="button" disabled={!activeLyric}
                aria-pressed={positioningTarget === 'lyric'}
                onClick={() => { positionDragRef.current = null; setPositioningTarget(positioningTarget === 'lyric' ? 'none' : 'lyric') }}
                className={cn('rounded-md border px-2.5 py-1.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40',
                  positioningTarget === 'lyric' ? 'border-ink bg-ink text-white' : 'border-line bg-surface text-muted hover:border-ink')}>
                Drag active lyric
              </button>
              <button type="button" disabled={!activeOverlay}
                aria-pressed={positioningTarget === 'text'}
                onClick={() => { positionDragRef.current = null; setPositioningTarget(positioningTarget === 'text' ? 'none' : 'text') }}
                className={cn('rounded-md border px-2.5 py-1.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40',
                  positioningTarget === 'text' ? 'border-ink bg-ink text-white' : 'border-line bg-surface text-muted hover:border-ink')}>
                Drag active title
              </button>
              <button type="button"
                title="Snap text to the 25%, 50%, and 75% alignment guides while dragging"
                aria-pressed={snapTextToGuides}
                onClick={() => {
                  setSnapTextToGuides((current) => !current)
                  setAlignmentGuides({ vertical: null, horizontal: null })
                }}
                className={cn('rounded-md border px-2.5 py-1.5 text-xs font-medium',
                  snapTextToGuides ? 'border-sky-500 bg-sky-500/10 text-ink' : 'border-line bg-surface text-muted hover:border-ink')}>
                Snap to guides {snapTextToGuides ? 'On' : 'Off'}
              </button>
              {positioningTarget !== 'none' && (
                <button type="button" onClick={() => { positionDragRef.current = null; setPositioningTarget('none') }}
                  className="rounded-md px-2 py-1.5 text-xs text-muted underline">Done</button>
              )}
              <span className="text-[11px] text-muted">
                {positioningTarget === 'lyric' ? 'Drag the lyric directly in the footage preview.' :
                  positioningTarget === 'text' ? 'Drag the title directly in the footage preview.' :
                    'Choose a layer to move it directly on the footage.'}
                {' '}Positions update in the edit draft; use the existing Apply controls to save and render.
              </span>
            </div>
            <div className="grid gap-3 sm:grid-cols-[minmax(0,1.4fr)_minmax(180px,1fr)] sm:items-center">
            <div data-campaign-preview-stage className="relative overflow-hidden rounded-md bg-black">
              <video
                ref={videoRef}
                key={String(preview.index) + "-" + String(preview.shot.source_index) + "-" + String(preview.shot.start_seconds)}
                playsInline
                preload="metadata"
                src={"/api/runs/" + runId + "/campaign-source?source_index=" + preview.shot.source_index}
                onLoadedMetadata={(event) => {
                  advancingShotRef.current = false
                  if (transitionTimerRef.current) clearTimeout(transitionTimerRef.current)
                  setTransitionPhase(transitionDurationMs > 0 ? 'in' : 'idle')
                  if (transitionDurationMs > 0) {
                    transitionTimerRef.current = setTimeout(() => setTransitionPhase('idle'), transitionDurationMs)
                  }
                  const targetSourceTime = pendingSeekRef.current ?? preview.shot.start_seconds
                  setMaskTimestamp(Math.round(targetSourceTime * 4) / 4)
                  event.currentTarget.currentTime = targetSourceTime
                  pendingSeekRef.current = null
                  if (isPlaying) {
                    const audio = audioRef.current
                    if (audio) {
                      audio.currentTime = musicStart + shotTimelineStart + Math.max(0, targetSourceTime - preview.shot.start_seconds)
                      void audio.play().catch(() => undefined)
                    }
                    void event.currentTarget.play().catch(() => setIsPlaying(false))
                  }
                }}
                onTimeUpdate={(event) => {
                  const localElapsed = Math.max(0, event.currentTarget.currentTime - preview.shot.start_seconds)
                  setMaskTimestamp(Math.round(event.currentTarget.currentTime * 4) / 4)
                  const nextPlayhead = shotTimelineStart + localElapsed
                  setPlayheadSeconds(nextPlayhead)
                  const audio = audioRef.current
                  if (audio && isPlaying) {
                    const target = musicStart + nextPlayhead
                    if (Math.abs(audio.currentTime - target) > 0.45) audio.currentTime = target
                  }
                  const transitionLeadSeconds = transitionDurationMs / 1000
                  const boundaryThreshold = transitionDurationMs > 0
                    ? Math.max(0.04, transitionLeadSeconds)
                    : 0.04
                  if (event.currentTarget.currentTime >= preview.shot.end_seconds - boundaryThreshold && !advancingShotRef.current) {
                    advancingShotRef.current = true
                    if (transitionDurationMs > 0) {
                      setTransitionPhase('out')
                      event.currentTarget.pause()
                    }
                    transitionTimerRef.current = setTimeout(() => {
                      if (preview.index < shots.length - 1) {
                        setTransitionPhase('in')
                        onSelectShot(preview.index + 1)
                      } else {
                        videoRef.current?.pause()
                        audio?.pause()
                        setIsPlaying(false)
                        setTransitionPhase('idle')
                      }
                    }, transitionDurationMs)
                  }
                }}
                style={{
                  opacity: activeTransition === 'fade' && (transitionPhase === 'out' || transitionPhase === 'in') ? 0 : 1,
                  transform: transitionPhase === 'idle' ? 'translateX(0) scale(1)' : (
                    activeTransition === 'smoothleft' ? (transitionPhase === 'out' ? 'translateX(-14%)' : 'translateX(14%)') :
                    activeTransition === 'smoothright' ? (transitionPhase === 'out' ? 'translateX(14%)' : 'translateX(-14%)') :
                    activeTransition === 'slideleft' ? (transitionPhase === 'out' ? 'translateX(-100%)' : 'translateX(100%)') :
                    activeTransition === 'slideright' ? (transitionPhase === 'out' ? 'translateX(100%)' : 'translateX(-100%)') :
                    transitionPhase === 'out' && previewTransitionStyle === 'dynamic' ? 'scale(1.035)' : 'scale(1)'
                  ),
                  clipPath: activeTransition === 'wipeleft' && transitionPhase !== 'idle'
                    ? (transitionPhase === 'out' ? 'inset(0 100% 0 0)' : 'inset(0 0 0 100%)')
                    : activeTransition === 'wiperight' && transitionPhase !== 'idle'
                      ? (transitionPhase === 'out' ? 'inset(0 0 0 100%)' : 'inset(0 100% 0 0)')
                      : 'inset(0 0 0 0)',
                  transition: transitionDurationMs > 0
                    ? 'opacity ' + transitionDurationMs + 'ms ease, transform ' + transitionDurationMs + 'ms ease, clip-path ' + transitionDurationMs + 'ms ease'
                    : 'none',
                }}
                className="max-h-64 w-full bg-black object-contain"
              />
              {alignmentGuides.vertical !== null && (
                <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 z-30 border-l border-dashed border-sky-300 shadow-[0_0_5px_rgba(125,211,252,0.8)]"
                  style={{ left: alignmentGuides.vertical + '%' }} />
              )}
              {alignmentGuides.horizontal !== null && (
                <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 z-30 border-t border-dashed border-sky-300 shadow-[0_0_5px_rgba(125,211,252,0.8)]"
                  style={{ top: alignmentGuides.horizontal + '%' }} />
              )}
              {activeLyric && (
                <div
                  className="pointer-events-none absolute inset-0"
                  style={subjectMaskUrl ? {
                    maskImage: 'url("' + subjectMaskUrl + '")',
                    WebkitMaskImage: 'url("' + subjectMaskUrl + '")',
                    maskSize: '100% 100%',
                    WebkitMaskSize: '100% 100%',
                  } : undefined}
                >
                  <div
                    className={cn('absolute flex w-[90%] justify-center px-3',
                      positioningTarget === 'lyric' ? 'pointer-events-auto cursor-move touch-none relative rounded-sm outline outline-1 outline-dashed outline-sky-300 outline-offset-4' : 'pointer-events-none')}
                    onPointerDown={(event) => beginLiveTextDrag(event, 'lyric')}
                    onPointerMove={moveLiveTextDrag}
                    onPointerUp={endLiveTextDrag}
                    onPointerCancel={endLiveTextDrag}
                    style={{
                      left: activeLyric.position_x + '%',
                      top: activeLyric.position_y + '%',
                      transform: 'translate(-50%, -50%) rotate(' + activeLyric.rotation_degrees + 'deg)',
                    }}
                  >
                  <span
                    key={activeLyric.phrase_index + '-' + previewLyricAnimation}
                    className="inline-block text-center font-extrabold leading-tight"
                    style={{
                      animation: previewLyricAnimation === 'dynamic' ? 'clipyyy-lyric-pop 520ms cubic-bezier(.2,.8,.2,1) both' : previewLyricAnimation === 'cinematic' || previewLyricAnimation === 'minimal' ? 'clipyyy-lyric-fade 420ms ease-out both' : 'clipyyy-lyric-karaoke 650ms ease-out both',
                      color: lyricsColor,
                      fontSize: 'clamp(14px, ' + (22 * activeLyric.scale_percent / 100) + 'px, 42px)',
                      textShadow: '0 2px 8px #000, 0 0 12px ' + lyricsHighlightColor,
                    }}
                  >
                    {activeWordWindow.length > 0
                      ? activeWordWindow.map((item, index) => (
                        <span key={item.start_seconds + '-' + index}
                          style={{ color: activeWordIndex >= 0 && item.start_seconds === lyricWords[activeWordIndex]?.start_seconds ? lyricsHighlightColor : lyricsColor }}>
                          {item.word}{index < activeWordWindow.length - 1 ? ' ' : ''}
                        </span>
                      ))
                      : activeLyric.text}
                  </span>
                    {positioningTarget === 'lyric' && (
                      <>
                        <button type="button" aria-label="Resize lyric" title="Drag to resize"
                          onPointerDown={(event) => beginTransformDrag(event, 'lyric', 'resize', activeLyric.scale_percent)}
                          className="absolute -bottom-3 -right-3 z-10 h-5 w-5 rounded-full border-2 border-white bg-sky-500 shadow-lg cursor-nwse-resize touch-none" />
                        <button type="button" aria-label="Rotate lyric" title="Drag horizontally to rotate"
                          onPointerDown={(event) => beginTransformDrag(event, 'lyric', 'rotate', activeLyric.rotation_degrees)}
                          className="absolute -top-7 left-1/2 z-10 h-5 w-5 -translate-x-1/2 rounded-full border-2 border-white bg-violet-500 shadow-lg cursor-ew-resize touch-none">
                          <span className="sr-only">Rotate</span>
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}
              {activeOverlay && (
                <div
                  className={cn('absolute flex items-center justify-center px-4',
                    positioningTarget === 'text' ? 'pointer-events-auto cursor-move touch-none relative rounded-sm outline outline-1 outline-dashed outline-sky-300 outline-offset-4' : 'pointer-events-none')}
                  onPointerDown={(event) => beginLiveTextDrag(event, 'text')}
                  onPointerMove={moveLiveTextDrag}
                  onPointerUp={endLiveTextDrag}
                  onPointerCancel={endLiveTextDrag}
                  style={{ left: activeOverlay.position_x + '%', top: activeOverlay.position_y + '%', transform: 'translate(-50%, -50%) rotate(' + (activeOverlay.rotation_degrees ?? 0) + 'deg)', width: '90%' }}>
                  <span key={activeOverlay.rank + '-' + activeOverlayIndex + '-' + previewTextAnimation}
                    className="inline-block text-center font-extrabold leading-tight"
                    style={{
                      animation: previewTextAnimation === 'none' ? 'none' : previewTextAnimation === 'pop' ? 'clipyyy-text-pop 520ms cubic-bezier(.2,.8,.2,1) both' : previewTextAnimation === 'fade' ? 'clipyyy-text-fade 420ms ease-out both' : 'clipyyy-text-slide 460ms ease-out both',
                      color: activeOverlay.color,
                      fontSize: 'clamp(14px, ' + (activeOverlay.font_size_percent * 0.22) + 'vw, 44px)',
                      textShadow: activeOverlay.background ? 'none' : '0 2px 8px #000',
                      background: activeOverlay.background ? 'rgba(0,0,0,.62)' : 'transparent',
                      padding: activeOverlay.background ? '0.25em 0.5em' : 0,
                      borderRadius: '0.3em',
                    }}>{activeOverlay.text}</span>
                  {positioningTarget === 'text' && (
                    <>
                      <button type="button" aria-label="Resize title" title="Drag to resize"
                        onPointerDown={(event) => beginTransformDrag(event, 'text', 'resize', activeOverlay.font_size_percent)}
                        className="absolute -bottom-3 -right-3 z-10 h-5 w-5 rounded-full border-2 border-white bg-sky-500 shadow-lg cursor-nwse-resize touch-none" />
                      <button type="button" aria-label="Rotate title" title="Drag horizontally to rotate"
                        onPointerDown={(event) => beginTransformDrag(event, 'text', 'rotate', activeOverlay.rotation_degrees ?? 0)}
                        className="absolute -top-7 left-1/2 z-10 h-5 w-5 -translate-x-1/2 rounded-full border-2 border-white bg-violet-500 shadow-lg cursor-ew-resize touch-none">
                        <span className="sr-only">Rotate</span>
                      </button>
                    </>
                  )}
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
              <label className="mt-2 flex flex-col gap-1 text-xs text-muted">
                <span className="flex justify-between">
                  <span>Scrub timeline</span>
                  <span className="font-mono">{formatDuration(playheadSeconds)} / {formatDuration(total)}</span>
                </span>
                <input
                  type="range"
                  min={0}
                  max={total}
                  step={0.01}
                  value={Math.min(playheadSeconds, total)}
                  onChange={(event) => seekToTimeline(Number(event.target.value))}
                  aria-label="Seek campaign preview timeline"
                  className="w-full accent-current"
                />
              </label>
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
              <p className="mt-1 text-xs text-muted">One controller keeps footage, soundtrack and timed text together. Preview transitions follow the selected style; final export remains the exact render reference.</p>
              {lyricsBehindSubject && <p className="text-xs text-muted">Subject-aware lyric masking is on · cached masks refresh while you scrub and play.</p>}
            </div>
            </div>
          </div>
        )
      })()}
      {hasMusic && (
        <audio
          ref={audioRef}
          preload="metadata"
          src={"/api/runs/" + runId + "/campaign-music"}
          onTimeUpdate={(event) => {
            if (isPlaying && advancingShotRef.current) {
              setPlayheadSeconds(Math.max(0, event.currentTarget.currentTime - musicStart))
            }
          }}
          className="hidden"
        />
      )}
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
                aria-pressed={selectedShotIndex === index}
                onClick={() => {
                  videoRef.current?.pause()
                  audioRef.current?.pause()
                  setIsPlaying(false)
                  const timelineStart = shots.slice(0, index).reduce((sum, item) => sum + item.duration, 0)
                  pendingSeekRef.current = shot.start_seconds
                  onSelectShot(index)
                  setPlayheadSeconds(timelineStart)
                  if (index === selectedShotIndex && videoRef.current) {
                    videoRef.current.currentTime = shot.start_seconds
                    pendingSeekRef.current = null
                  }
                  if (audioRef.current) audioRef.current.currentTime = musicStart + timelineStart
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
                  if (Number.isInteger(fromIndex)) { onMoveShot(fromIndex, index); onSelectShot(index) }
                }}
                className={cn('group relative min-w-[104px] flex-1 cursor-grab overflow-hidden rounded-md border bg-paper text-left transition-colors hover:border-ink active:cursor-grabbing', selectedShotIndex === index ? 'border-ink ring-2 ring-ink/30' : 'border-line')}
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
      {(lyrics.length > 0 || lyricWords.length > 0) && (
        <div className="flex flex-col gap-2" aria-label="Campaign editing tracks">
          <div className="overflow-x-auto">
            <div className="grid min-w-[780px] grid-cols-[76px_minmax(680px,1fr)] items-center gap-2">
              <span className="label text-muted" title="Drag a lyric block to move it; drag either edge to adjust its timing.">LYRICS</span>
              <div
                data-campaign-lyrics-track
                className="relative h-10 overflow-hidden rounded-md border border-line bg-surface"
                onPointerMove={(event) => {
                  if (!activeLyricTrim || event.pointerId !== activeLyricTrim.pointerId) return
                  const delta = ((event.clientX - activeLyricTrim.startX) / activeLyricTrim.trackWidth) * activeLyricTrim.initialTotal
                  const length = activeLyricTrim.initialEnd - activeLyricTrim.initialStart
                  let start = activeLyricTrim.initialStart
                  let end = activeLyricTrim.initialEnd
                  if (activeLyricTrim.side === 'move') {
                    start = Math.max(0, Math.min(activeLyricTrim.initialTotal - length, start + delta))
                    end = start + length
                  } else if (activeLyricTrim.side === 'start') {
                    start = Math.max(0, Math.min(end - 0.1, start + delta))
                  } else {
                    end = Math.max(start + 0.1, Math.min(activeLyricTrim.initialTotal, end + delta))
                  }
                  onUpdateLyric(activeLyricTrim.phraseIndex, {
                    start_seconds: Math.round((start + musicStart) * 100) / 100,
                    end_seconds: Math.round((end + musicStart) * 100) / 100,
                  })
                }}
                onPointerUp={(event) => {
                  if (activeLyricTrim?.pointerId === event.pointerId) setActiveLyricTrim(null)
                }}
                onPointerCancel={() => setActiveLyricTrim(null)}
              >
                {lyrics.length > 0 ? lyrics.map((lyric) => {
                  const left = Math.max(0, Math.min(100, (lyric.start_seconds / total) * 100))
                  const width = Math.max(1.2, Math.min(100 - left, ((lyric.end_seconds - lyric.start_seconds) / total) * 100))
                  const beginDrag = (event: ReactPointerEvent<HTMLElement>, side: 'move' | 'start' | 'end') => {
                    event.preventDefault()
                    event.stopPropagation()
                    const track = event.currentTarget.closest('[data-campaign-lyrics-track]') as HTMLDivElement | null
                    if (!track) return
                    const trackWidth = track.getBoundingClientRect().width
                    if (trackWidth <= 0) return
                    track.setPointerCapture(event.pointerId)
                    setActiveLyricTrim({
                      pointerId: event.pointerId,
                      phraseIndex: lyric.phrase_index,
                      side,
                      startX: event.clientX,
                      initialStart: lyric.start_seconds,
                      initialEnd: lyric.end_seconds,
                      trackWidth,
                      initialTotal: total,
                    })
                  }
                  return (
                    <div key={`lyric-track-${lyric.phrase_index}`} role="group" tabIndex={0}
                      title={`${lyric.text} · ${formatDuration(lyric.start_seconds)}–${formatDuration(lyric.end_seconds)}`}
                      aria-label={`Move or trim lyric: ${lyric.text}`}
                      onClick={() => seekToTimelineRef.current(lyric.start_seconds)}
                      onPointerDown={(event) => beginDrag(event, 'move')}
                      className="group absolute inset-y-1 flex min-w-0 cursor-grab touch-none items-center overflow-hidden rounded border border-acid/70 bg-acid/20 px-1 text-[10px] font-medium text-ink active:cursor-grabbing"
                      style={{ left: `${left}%`, width: `${width}%` }}>
                      <span className="pointer-events-none truncate">{lyric.text}</span>
                      <span role="slider" tabIndex={0} aria-label={`Trim start of lyric: ${lyric.text}`}
                        aria-valuemin={0} aria-valuemax={Math.max(0, lyric.end_seconds - 0.1)} aria-valuenow={lyric.start_seconds}
                        onPointerDown={(event) => beginDrag(event, 'start')}
                        onKeyDown={(event) => {
                          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
                          event.preventDefault()
                          const delta = event.key === 'ArrowRight' ? 0.05 : -0.05
                          const nextStart = Math.max(0, Math.min(lyric.end_seconds - 0.1, lyric.start_seconds + delta))
                          onUpdateLyric(lyric.phrase_index, { start_seconds: Math.round((nextStart + musicStart) * 100) / 100 })
                        }}
                        className="absolute inset-y-0 left-0 z-10 w-2 cursor-ew-resize bg-white/40 opacity-0 transition-opacity group-hover:opacity-100" />
                      <span role="slider" tabIndex={0} aria-label={`Trim end of lyric: ${lyric.text}`}
                        aria-valuemin={lyric.start_seconds + 0.1} aria-valuemax={total} aria-valuenow={lyric.end_seconds}
                        onPointerDown={(event) => beginDrag(event, 'end')}
                        onKeyDown={(event) => {
                          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
                          event.preventDefault()
                          const delta = event.key === 'ArrowRight' ? 0.05 : -0.05
                          const nextEnd = Math.max(lyric.start_seconds + 0.1, Math.min(total, lyric.end_seconds + delta))
                          onUpdateLyric(lyric.phrase_index, { end_seconds: Math.round((nextEnd + musicStart) * 100) / 100 })
                        }}
                        className="absolute inset-y-0 right-0 z-10 w-2 cursor-ew-resize bg-white/40 opacity-0 transition-opacity group-hover:opacity-100" />
                    </div>
                  )
                }) : lyricWords.map((word, index) => {
                  const left = Math.max(0, Math.min(100, (word.start_seconds / total) * 100))
                  const width = Math.max(0.55, Math.min(100 - left, ((word.end_seconds - word.start_seconds) / total) * 100))
                  return (
                    <button key={`lyric-word-track-${index}`} type="button"
                      title={`${word.word} · ${formatDuration(word.start_seconds)}–${formatDuration(word.end_seconds)}`}
                      aria-label={`Seek to lyric word: ${word.word}`}
                      onClick={() => seekToTimelineRef.current(word.start_seconds)}
                      className="absolute inset-y-1 overflow-hidden rounded-sm border border-acid/50 bg-acid/20 text-[9px] text-ink hover:bg-acid/40"
                      style={{ left: `${left}%`, width: `${width}%` }} />
                  )
                })}
                <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 z-10 w-0.5 bg-red-500"
                  style={{ left: `${Math.max(0, Math.min(100, (playheadSeconds / total) * 100))}%` }} />
              </div>
            </div>
          </div>
        </div>
      )}
      {hasMusic && (
        <div className="flex flex-col gap-2 border-t border-line pt-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="label text-muted">Soundtrack waveform · beat markers</span>
            <span className="font-mono text-[11px] text-faint">
              {waveformQuery.isLoading ? 'Analyzing audio…' : waveformQuery.isError ? 'Waveform unavailable' : waveform ? formatDuration(waveform.duration_seconds) : 'Waiting for audio'}
            </span>
          </div>
          {waveformPeaks.length > 0 ? (
            <div
              className="relative flex h-14 min-w-[680px] touch-none cursor-crosshair items-center gap-px overflow-hidden rounded-md bg-surface px-2 outline-none focus-visible:ring-2 focus-visible:ring-ink"
              role="slider"
              tabIndex={0}
              aria-label="Soundtrack waveform timeline scrubber"
              aria-valuemin={0}
              aria-valuemax={total}
              aria-valuenow={playheadSeconds}
              aria-valuetext={formatDuration(playheadSeconds)}
              onPointerDown={(event) => {
                event.currentTarget.setPointerCapture(event.pointerId)
                const bounds = event.currentTarget.getBoundingClientRect()
                seekToTimelineRef.current(((event.clientX - bounds.left) / bounds.width) * total)
              }}
              onPointerMove={(event) => {
                if (event.buttons !== 1) return
                const bounds = event.currentTarget.getBoundingClientRect()
                seekToTimelineRef.current(((event.clientX - bounds.left) / bounds.width) * total)
              }}
              onKeyDown={(event) => {
                if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                  event.preventDefault()
                  seekToTimelineRef.current(playheadSeconds + (event.key === 'ArrowRight' ? 0.5 : -0.5))
                } else if (event.key === 'Home' || event.key === 'End') {
                  event.preventDefault()
                  seekToTimelineRef.current(event.key === 'Home' ? 0 : total)
                }
              }}
            >
              {waveformPeaks.map((peak, index) => (
                <span
                  key={index}
                  title={`Audio peak ${Math.round(peak * 100)}%`}
                  className="min-w-0 flex-1 rounded-sm bg-acid/80"
                  style={{ height: `${Math.max(3, peak * 100)}%` }}
                />
              ))}
              {(musicAnalysis?.beat_markers ?? []).map((marker, index) => (
                <span
                  key={`beat-${index}`}
                  title={`Beat · ${formatDuration(marker.time_seconds)} · strength ${Math.round(marker.strength * 100)}%`}
                  className={cn(
                    'pointer-events-none absolute inset-y-1 z-[5]',
                    marker.strength >= 0.65 ? 'w-0.5 bg-white shadow-[0_0_4px_rgba(255,255,255,0.8)]' : 'w-px bg-sunk/90',
                  )}
                  style={{ left: `${(marker.time_seconds / total) * 100}%` }}
                />
              ))}
              <span
                aria-hidden="true"
                className="pointer-events-none absolute inset-y-0 z-10 w-0.5 bg-red-500 shadow-[0_0_5px_rgba(239,68,68,0.9)]"
                style={{ left: 'calc(' + Math.max(0, Math.min(100, (playheadSeconds / total) * 100)) + '%)' }}
              />
            </div>
          ) : (
            <p className="text-xs text-faint">
              {waveformQuery.isError ? 'Could not analyze this soundtrack. Playback is still available.' : 'Waveform will appear after the soundtrack is analyzed.'}
            </p>
          )}
        </div>
      )}
      {waveform && (
        <label className="flex flex-col gap-2 border-t border-line pt-3 text-sm">
          <span className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">Soundtrack start / alignment</span>
            <span className="font-mono text-muted">{formatDuration(musicStart)}</span>
          </span>
          <input type="range" min={0} max={Math.max(0, waveform.duration_seconds - total)} step={0.05}
            value={Math.min(musicStart, Math.max(0, waveform.duration_seconds - total))}
            onChange={(event) => {
              const nextStart = Number(event.target.value)
              onMusicStartChange(nextStart)
              if (audioRef.current) audioRef.current.currentTime = nextStart + playheadSeconds
            }}
            className="w-full accent-current" aria-label="Choose soundtrack start position" />
          <span className="text-xs text-muted">Shift the waveform window to line up the music with your first shot. Fine adjustment: 0.05 seconds.</span>
        </label>
      )}
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
                    onClick={() => seekToTimelineRef.current(overlay.start_seconds)}
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
