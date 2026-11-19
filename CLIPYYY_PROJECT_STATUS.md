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
- **Latest main commit:** `f6004eecccf5a676e34b2c8fa6fa35c9d2732000` — Add conservative filler-word removal (#23).
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
| Text-based editing / filler removal | V1 implemented | PR #23 / `main` | Conservative English filler-word removal is merged; full transcript editing remains a later feature. |
| Campaign shot-level editor | Assigned / in progress | Architecture / `feature/campaign-shot-editor` | Reorder, trim and remove AI-selected campaign shots, then rerender from saved sources without rerunning analysis. |
| Advanced timeline editor | Not yet assessed | Unassigned | A full multitrack/waveform timeline remains separate from this focused campaign storyboard editor. |
| Audio enhancement / voiceover | Not yet assessed | Unassigned | Assess local/offline options and dependencies. |
| AI B-roll improvements | Existing optional B-roll; enhancements not assessed | Unassigned | Inspect current Pexels workflow before implementing alternatives. |

## Current work

| Task | Owner chat | Branch / PR | Status | Last update |
|---|---|---|---|---|
| Conservative filler-word removal for spoken clips | Feature Development + Architecture review | `feature/transcript-filler-removal` / [PR #23](https://github.com/Parth33831/clipyyy/pull/23) | Merged into `main` as `f6004eecccf5a676e34b2c8fa6fa35c9d2732000`; post-merge CI passed | 2026-11-19 |
| Campaign shot-level editor | Architecture & Master Plan | `feature/campaign-shot-editor` | Assigned; implementation in progress | 2026-11-19 |

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


## Next assignment: Campaign footage discovery (Pexels)

**Owner:** Feature Development  
**Branch:** `feature/campaign-footage-discovery`  
**Base:** `main` at `f6004eecccf5a676e34b2c8fa6fa35c9d2732000`  
**Status:** In progress

**Objective:** Reduce manual footage gathering for campaign edits by automatically discovering relevant stock-video candidates from the already-supported Pexels integration, using the extracted campaign brief and requirements.

**V1 scope**
1. Keep creator-supplied source videos as the primary footage and preserve their existing ordering/behaviour.
2. Add an opt-in campaign control for automatic matching stock footage. If enabled and a Pexels key is configured, derive a small set of search queries from the structured campaign plan and fetch a bounded number of relevant Pexels videos.
3. Download candidates only into the run's existing work directory under `CLIPYYY_HOME`; never use OS temp or C: paths.
4. Include discovered footage in the campaign montage source pool with correct source indexes, duration checks and deduplication.
5. Preserve Pexels author/page attribution in run details/export metadata.
6. If the key is missing, search fails, or no suitable results exist, continue with creator-supplied footage and show a clear non-fatal status. Never silently switch to a paid API.
7. Be explicit that text-only Ollama models cannot visually understand footage. Search relevance comes from the query; frame-level semantic matching remains available only with a compatible vision model.
8. Do not scrape arbitrary YouTube videos or bypass access controls. Existing creator-supplied URLs remain supported subject to the creator having rights to use them.

**Out of scope:** YouTube search/download automation, paid stock APIs, automatic social publishing, a full timeline editor, new vision-model downloads, or changing campaign music/lyrics rendering.

**Likely modules:** New focused campaign asset discovery module; `pipeline.py`; `campaign.py` only if query derivation needs a helper; `frontend/src/api.ts`; `frontend/src/pages/NewRun.tsx`; `frontend/src/pages/RunDetail.tsx`; campaign/pipeline tests.

**Acceptance criteria**
- Feature is optional and disabled by default unless product review explicitly changes that decision.
- Existing campaign runs without the option behave identically.
- Creator-supplied source indexes remain stable; discovered sources are appended, not inserted before them.
- Every discovered video is duration-validated, deduplicated, stored under the run work directory, and credited.
- Missing Pexels key/network failure/no results never fail the campaign.
- Text-only fallback never claims to have visually inspected stock footage.
- Unit tests cover query generation, API response parsing, deduplication, source-index integrity, graceful fallback, and run-detail attribution.
- Run backend tests, Ruff, frontend production build and relevant CI. Do not claim local Windows verification unless run locally.

**Coordination note:** Existing stale branches `music-intelligence-hooks` and `creative-anime-editing` are divergent from current `main` and touch campaign/render modules. Do not merge or reuse them wholesale. This feature starts from current `main` and must avoid their unrelated changes.



### Assignment: Campaign shot-level editor

**Objective:** Turn the current AI-generated campaign montage into an editable storyboard. After the initial AI analysis, creators can inspect the selected shots, reorder them, trim their in/out points, remove unwanted shots, and rerender the campaign without downloading footage again or rerunning visual analysis/transcription.

**Why this is next:** Main already includes campaign brief parsing, visual scene analysis, reference-video style analysis, montage planning, local music analysis/beat-aligned cuts, opening hooks, lyrics and campaign export checks. The unmerged-looking `music-intelligence-hooks` branch is historical: its corresponding PR #10 is already merged. Do not duplicate that work. A focused shot-level editor is the missing creator-control layer, not another music-analysis implementation.

**V1 scope**
1. Expose saved campaign edits and safe source metadata (title and duration) in run details; do not expose local filesystem paths.
2. Add a storyboard editor for each generated campaign output. Show ordered shots with source, source in/out timestamps and the AI selection reason.
3. Allow moving shots up/down, editing start/end timestamps and removing shots. Keep output rank/title stable. No adding arbitrary new source ranges in V1.
4. Validate edits server-side: known edit ranks only; source indexes exist; finite timestamps within source duration; each shot is 1.5–5 seconds; at least 3 shots per edit; total selected duration at least max(5 seconds, 65% of target duration).
5. Preserve the original AI-generated shot plan so creators can reset their manual edits.
6. Save the edited plan to the existing selection artifact, then rebuild only the montage/render from already-downloaded source files. Do not rerun campaign-page import, vision analysis, reference analysis, AI selection, or lyric transcription.
7. Preserve attached music, beat alignment, hooks, lyrics and style settings. Normal lyric/style rerender must continue reusing the already-assembled montage.
8. Keep non-campaign clipping and all existing workflows unchanged.

**Likely files**
- `src/clipyyy/pipeline.py`: validate/persist edited selection and rerender with an explicit montage-rebuild option.
- `src/clipyyy/api.py`: typed update endpoint and public campaign edit/source metadata.
- `frontend/src/api.ts`, `frontend/src/pages/RunDetail.tsx`: types, save action and shot storyboard controls.
- `tests/test_pipeline.py`, `tests/test_api.py`, optionally `tests/test_campaign.py`: validation, persistence, rerender reuse/rebuild and endpoint coverage.

**Acceptance criteria**
- Creator can reorder, trim and remove shots for each campaign output; edits are reflected in final rendered output.
- Reset restores the original AI-generated shot order and timestamps.
- Invalid source indexes, out-of-range/non-finite timestamps, too-short/too-long shots, fewer than 3 shots and insufficient total duration are rejected without corrupting the saved plan.
- Rerender reuses downloaded footage and saved edit decisions; it does not invoke the LLM or vision analysis.
- Music beat alignment and existing hook/lyric overlays remain functional.
- Existing lyric-only changes continue to reuse the assembled montage (no regression).
- Existing non-campaign clip runs remain unchanged.
- Run `uv run pytest -q`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, and `npm --prefix frontend run build`; report actual results. A real FFmpeg smoke test is required where the CI environment supports it.

**Priority:** P1 — next campaign-editor capability. This delivers creator control over AI decisions before we invest in a full multitrack timeline.

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
- 2026-11-19: PR #23 was reviewed and squash-merged into `main` as `f6004eecccf5a676e34b2c8fa6fa35c9d2732000`. Post-merge CI passed: Ruff lint, Ruff format, frontend build, and fast backend tests (82 passed, 15 skipped). Windows, macOS and full-backend jobs were skipped because they are manual-only.
- 2026-11-19: Inspected the latest `main` campaign pipeline and confirmed brief parsing, visual analysis, montage selection, music section/beat analysis, hooks and lyric overlays already exist. The historical music-intelligence branch maps to merged PR #10; avoid duplicating it. Assigned Campaign shot-level editor to Architecture on `feature/campaign-shot-editor`, based on `f6004eecccf5a676e34b2c8fa6fa35c9d2732000`.
