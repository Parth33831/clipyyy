# CLIPYYY Project Status & Coordination

> Shared coordination document for all ChatGPT conversations working on CLIPYYY.
> Update this file whenever a task is started, completed, paused, or handed off.
> Git history and reviewed code remain the source of truth.

## Project

- **Repository:** https://github.com/Parth33831/clipyyy
- **Local path:** `B:\\CLIPSTUDIO\\clipyyy`
- **Default branch:** `main`
- **Product goal:** A stable, professional AI video creation and repurposing application with capabilities approaching OpusClip.
- **Data directory:** `B:\\CLIPSTUDIO\\clipyyy-data` (keep user data separate from source code).

## Team / conversation responsibilities

| Workspace | Responsibility | Rules |
|---|---|---|
| Architecture & Master Plan | Product vision, roadmap, OpusClip capability research, cross-feature decisions and coordination | Do not independently implement overlapping features without checking current ownership first. |
| Feature Development | Implement the feature(s) explicitly assigned to that conversation | Work on a dedicated branch; preserve unrelated work; provide a complete handoff. |
| Testing & Integration | Review branches/PRs, inspect diffs, run tests and coordinate safe integration | Never merge unreviewed or conflicting changes. |

## Repository baseline (inspected 2026-11-19)

- **Default branch:** `main`
- **Latest main commit:** `e32b05896f161fc1a50f95547a69711d4f8c2d50` — Add 1–3 word lyric caption layout (#22).
- Recent completed main work includes lyric animation previews, multi-colour lyric captions, configurable lyric colours, word-accurate song transcription and campaign dialogue/montage editing.
- **Open PR search:** no open PRs were returned for this repository at inspection time.
- **Branches observed:** `automatic-word-timed-lyrics`, `campaign-dialogue-transcription`, `creative-anime-editing`, `fix/campaign-export-audio-duration`, `fix/campaign-scene-selection-ci-final`, `fix/campaign-scene-selection-final-ci`, `fix/campaign-scene-selection-pacing`, `fix/campaign-scene-selection-pacing-ci`, `fix/campaign-scene-selection-release-check`, `fix/campaign-scene-selection-tested`, `fix/campaign-scene-selection-validated`, `improve-multi-clip-selection`, `instant-lyrics-style-editor`, `instant-lyrics-style-editor-ci`, `instant-lyrics-style-editor-verified`, `lyric-style-previews-multicolor`, `lyric-words-on-screen`, `lyrics-captions-animation`, `lyrics-color-controls`, `main`, `music-intelligence-hooks`, `refresh-legacy-lyric-timings`, `reuse-campaign-transcript-on-dialogue-rebuild`.
- Branch names alone do not prove whether work is merged or active; check branch heads and diffs before reusing them.
- **Coordination document branch:** `docs/project-coordination` (this document is maintained separately from application code).

## Feature status

| Area | Status | Owner / branch | Notes |
|---|---|---|---|
| Core video clipping pipeline | Existing implementation | Existing code | Verify current behavior before changing. |
| Local transcription | Existing implementation | Existing code | faster-whisper already provides word-level timestamps. |
| Face-based vertical reframing | Existing implementation | Existing code | Future improvements must not regress current framing. |
| Animated captions | Existing implementation | Feature Development | Recent lyric animation, colour and word-window work is on main. |
| Campaign montage / music / lyrics | Existing implementation | Feature Development | Recent campaign and lyric work is on main; avoid overlapping changes. |
| Virality scoring improvements | Not yet assessed | Unassigned | Existing selection already has hook, value, clarity and overall scores; assess before expanding. |
| Advanced subject tracking | Not yet assessed | Unassigned | Avoid duplicating existing MediaPipe face tracking. |
| Text-based editing / filler removal | Planned | Feature Development / `feature/transcript-filler-removal` | Assigned below; v1 is conservative English filler-word removal, not a full transcript editor. |
| Advanced timeline editor | Not yet assessed | Unassigned | Requires separate UX and data-model planning. |
| Audio enhancement / voiceover | Not yet assessed | Unassigned | Assess local/offline options and dependencies. |
| AI B-roll improvements | Existing optional B-roll; enhancements not assessed | Unassigned | Inspect current Pexels workflow before implementing alternatives. |

## Current work

| Task | Owner chat | Branch / PR | Status | Last update |
|---|---|---|---|---|
| Conservative filler-word removal for spoken clips | Feature Development | `feature/transcript-filler-removal` / [PR #23](https://github.com/Parth33831/clipyyy/pull/23) | Implementation in progress; awaiting CI and review | 2026-11-19 |

### Assignment: Conservative filler-word removal

**Objective:** Let creators produce tighter spoken-word clips by optionally removing clearly non-semantic verbal fillers using the existing word-level Whisper timestamps, while keeping picture and audio synchronized.

**V1 scope**
1. Add an opt-in **Remove filler words** control to the normal spoken-video clipping workflow. Default OFF so existing exports remain unchanged.
2. Start with a conservative English-only vocabulary: standalone `um`, `uh`, `erm`, and `er` (case/punctuation insensitive). Do not automatically remove ambiguous words such as `like`, `well`, `so`, or phrases such as `you know`.
3. Use the existing word timestamps to identify candidate intervals. Apply small configurable safety padding, merge overlapping/nearby intervals, and avoid cuts that would create invalid or excessively short segments.
4. Apply the same edit decision list to video and audio so sync is preserved. Keep captions/transcript timing aligned with the edited output.
5. Make the behaviour visible in run/clip details (e.g. number of filler cuts) and ensure the option is persisted with the run so retries are consistent.
6. Do not change campaign music/lyrics workflows in this task. Do not build a full transcript editor, waveform editor, speaker diarization, multilingual filler detection, or aggressive silence removal.

**Likely modules to inspect/change (confirm exact paths before editing):**
- `src/clipyyy/transcribe.py` — word text/timestamps already produced here; likely add a pure filler-candidate helper in a focused module instead of coupling detection to Whisper.
- `src/clipyyy/pipeline.py` and `src/clipyyy/timeline.py` — carry the optional edit decisions through the spoken-clip workflow and construct synchronized retained segments.
- `src/clipyyy/render.py` / `src/clipyyy/media.py` — render synchronized audio/video cuts using the existing FFmpeg abstraction.
- `src/clipyyy/api.py` and the relevant frontend run-options/results components — validate/persist the opt-in setting and expose it in the UI.
- `tests/` — unit tests for detection/interval math and integration tests for audio/video sync, default-off compatibility and retries.

**Acceptance criteria**
- Default OFF produces the same timing/render path as before.
- With the option ON, only the conservative configured filler tokens are removed; ordinary occurrences of ambiguous words are untouched.
- Audio and video use identical cut boundaries and remain synchronized.
- Word/caption timing after cuts is valid, monotonic and aligned to the resulting media.
- Very short clips, adjacent fillers, punctuation/case variants, beginning/end-of-clip fillers and overlapping padding are handled safely.
- Run settings survive reload/retry; no campaign music/lyrics regression.
- Add tests for detector precision, interval merging, timestamp remapping, default-off behaviour, persistence/retry and a representative FFmpeg render.
- Run `uv run pytest -q`, `uv run ruff check src tests`, and `npm --prefix frontend run build` (where frontend files change). Report actual results; do not claim tests that were not run.

**Priority:** P1 — next after the current lyric/campaign UI testing is complete. It builds on existing word-level transcription and adds a clear creator-facing editing capability. Keep the full transcript editor, advanced timeline and subject-tracking upgrades for later separate assignments.

## Safe development protocol

1. Before coding, inspect `git status`, current branch, `git log -5 --oneline`, and latest remote refs in the local working tree.
2. Never assume the local working tree is clean. Never discard, reset, or overwrite uncommitted user work.
3. Use the assigned dedicated feature branch from the latest appropriate base. Do not develop directly on `main`.
4. Before starting, confirm this task is still the active assignment and update this file if scope/ownership changes.
5. Avoid editing files owned by another active task. If overlap is unavoidable, coordinate first.
6. Keep commits focused. Do not force-push shared branches.
7. Before integration, compare the feature branch with the intended base, inspect changed files and run relevant tests.
8. Merge only after review and successful tests. Do not merge unrelated work as part of a feature.
9. After merge, update this document with the merge commit and test results.
10. GitHub is the shared source of code truth. This Markdown file is the shared coordination log, not a live sync of chat histories or local files.

## Required handoff

```text
TASK:
OWNER CHAT:
FEATURE BRANCH:
BASE BRANCH:
LATEST COMMIT:
PR (if any):

IMPLEMENTED:
- 

FILES CHANGED:
- 

TESTS RUN:
- 
TEST RESULTS:
- 

KNOWN BUGS / RISKS:
- 

REMAINING WORK:
- 

INTEGRATION NOTES / CONFLICTS:
- 

STATUS: In progress / Ready for review / Merged
```

## Decision log

- 2026-11-19: Established separate architecture, feature-development and testing/integration responsibilities across ChatGPT conversations.
- 2026-11-19: Created the coordination document on `docs/project-coordination`; application code was not changed.
- 2026-11-19: Assigned conservative English filler-word removal to Feature Development on `feature/transcript-filler-removal`, based on existing word-level transcription. Full transcript/timeline editing remains a later, separate feature.
- 2026-11-19: Feature Development opened PR #23 for the opt-in filler-removal v1. The branch is awaiting CI and Architecture review; it has not been merged.
