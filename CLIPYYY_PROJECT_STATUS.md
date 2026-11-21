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

## Repository baseline (inspected 2026-11-21)

- **Default branch:** `main`
- **Latest main commit:** `942a2dbbd5ebf00fe89de9174fd3cf3c494db928` — Add subtle cinematic camera movement to campaign edits (#27).
- Recent completed main work includes lyric animation previews, multi-colour lyric captions, configurable lyric colours, word-accurate song transcription, campaign dialogue/montage editing, stock-footage discovery, editable storyboards and optional cinematic camera movement.
- **Open PR search:** PR #27 was merged on 2026-11-21; no other open PRs were present at the latest inspection.
- **Branches observed:** `automatic-word-timed-lyrics`, `campaign-dialogue-transcription`, `campaign-footage-discovery`, `campaign-shot-editor`, `campaign-shot-editor-integration`, `creative-anime-editing`, `fix/campaign-export-audio-duration`, `fix/campaign-scene-selection-ci-final`, `fix/campaign-scene-selection-final-ci`, `fix/campaign-scene-selection-pacing`, `fix/campaign-scene-selection-pacing-ci`, `fix/campaign-scene-selection-release-check`, `fix/campaign-scene-selection-tested`, `fix/campaign-scene-selection-validated`, `improve-multi-clip-selection`, `instant-lyrics-style-editor`, `instant-lyrics-style-editor-ci`, `instant-lyrics-style-editor-verified`, `lyric-style-previews-multicolor`, `lyric-words-on-screen`, `lyrics-captions-animation`, `lyrics-color-controls`, `main`, `music-intelligence-hooks`, `refresh-legacy-lyric-timings`, `reuse-campaign-transcript-on-dialogue-rebuild`.
- Branch names alone do not prove whether work is merged or active; check branch heads and diffs before reusing them.
- **Coordination document branch:** `docs/project-coordination` (this document is maintained separately from application code).

## Feature status

| Area | Status | Owner / branch | Notes |
|---|---|---|---|
| Core video clipping pipeline | Existing implementation | Existing code | Verify current behavior before changing. |
| Local transcription | Existing implementation | Existing code | faster-whisper already provides word-level timestamps. |
| Face-based vertical reframing | Existing implementation | Existing code | Future improvements must not regress current framing. |
| Animated captions | Existing implementation | Feature Development | Recent lyric animation, colour and word-window work is on main. |
| Campaign montage / music / lyrics | Existing implementation | `main` | Music analysis, beat alignment, hooks, lyrics, storyboard controls, Pexels discovery and cinematic camera movement are integrated; improve only after auditing existing behavior. |
| Cinematic campaign camera movement | V1 implemented | PR #27 / `main` | Optional subtle Ken Burns-style per-shot movement with a static-crop toggle; merged as `942a2db`. |
| Virality scoring improvements | Not yet assessed | Unassigned | Existing selection already has hook, value, clarity and overall scores; assess before expanding. |
| Advanced subject tracking | Not yet assessed | Unassigned | Avoid duplicating existing MediaPipe face tracking. |
| Text-based editing / filler removal | V1 implemented | PR #23 / `main` | Conservative English filler-word removal is merged; full transcript editing remains a later feature. |
| Campaign shot-level editor | V1 implemented | PR #26 / `main` | Reorder, trim and remove AI-selected campaign shots, reset to the AI plan, and rerender from cached creator/Pexels sources without rerunning analysis. |
| Advanced timeline editor | Not yet assessed | Unassigned | A full multitrack/waveform timeline remains separate from this focused campaign storyboard editor. |
| Audio enhancement / voiceover | Not yet assessed | Unassigned | Assess local/offline options and dependencies. |
| Automatic campaign stock-footage discovery | V1 implemented | PR #24 / `main` | Opt-in Pexels discovery is merged; creator footage stays first and attribution is surfaced. |
| AI B-roll improvements | Existing optional B-roll; future enhancements not assessed | Unassigned | Inspect current Pexels workflow before implementing alternatives. |

## Current work

| Task | Owner chat | Branch / PR | Status | Last update |
|---|---|---|---|---|
| Conservative filler-word removal for spoken clips | Feature Development + Architecture review | `feature/transcript-filler-removal` / [PR #23](https://github.com/Parth33831/clipyyy/pull/23) | Merged into `main` as `f6004eecccf5a676e34b2c8fa6fa35c9d2732000`; post-merge CI passed | 2026-11-19 |
| Campaign footage discovery from the existing Pexels integration | Feature Development + Architecture review | `feature/campaign-footage-discovery` / [PR #24](https://github.com/Parth33831/clipyyy/pull/24) | Merged into `main` as `45cf0a0653d11eceb56d8b104786f1821da9801c`; fast-backend and frontend CI passed | 2026-11-19 |
| Campaign shot-level editor | Architecture & Master Plan | `feature/campaign-shot-editor-integration` / [PR #26](https://github.com/Parth33831/clipyyy/pull/26) | Merged into `main` as `67f8ec1e00c6b622a56750df035c61df3629a8ec`; CI passed: 95 passed, 15 skipped, frontend build passed | 2026-11-19 |
| Cinematic campaign camera movement | Feature Development + Architecture review | `feature/campaign-kinetic-visuals` / [PR #27](https://github.com/Parth33831/clipyyy/pull/27) | Merged into `main` as `942a2dbbd5ebf00fe89de9174fd3cf3c494db928`; PR CI passed: 96 passed, 17 skipped, Ruff and frontend build passed; post-merge CI queued at last check | 2026-11-21 |

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


## Completed assignment: Campaign footage discovery (Pexels)

**Owner:** Feature Development  
**Branch:** `feature/campaign-footage-discovery`  
**Base:** `main` at `f6004eecccf5a676e34b2c8fa6fa35c9d2732000`  
**Status:** Merged into `main` as `45cf0a0653d11eceb56d8b104786f1821da9801c` via [PR #24](https://github.com/Parth33831/clipyyy/pull/24); CI passed

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



### Completed assignment: Campaign shot-level editor

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


**Implementation and integration result**
- **PR:** [#26](https://github.com/Parth33831/clipyyy/pull/26), squash-merged.
- **Merge commit:** `67f8ec1e00c6b622a56750df035c61df3629a8ec`.
- **Final branch:** `feature/campaign-shot-editor-integration` (rebased/reapplied on top of merged PR #24 so stock footage and storyboard editing integrate cleanly). The earlier PR #25 was closed as superseded.
- **Files changed:** `frontend/src/api.ts`, `frontend/src/pages/RunDetail.tsx`, `src/clipyyy/api.py`, `src/clipyyy/pipeline.py`, `tests/test_api.py`, `tests/test_pipeline.py`.
- **CI:** Ruff lint passed; Ruff format passed; frontend production build passed; fast backend suite passed with **95 passed, 15 skipped**. Post-merge main CI also passed. Windows, macOS and full-backend/manual jobs were skipped.
- **Known validation gap:** No real-media FFmpeg campaign render or local Windows smoke test was run in this environment. The backend rerender path is covered by mocked pipeline/API tests; manual testing with a real campaign and music track remains recommended.

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
- 2026-11-19: Inspected the latest `main` campaign pipeline and confirmed brief parsing, visual analysis, montage selection, music section/beat analysis, hooks and lyric overlays already exist. The historical music-intelligence branch maps to merged PR #10; avoid duplicating it. Assigned Campaign shot-level editor to Architecture on `feature/campaign-shot-editor`, based on `f6004eecccf5a676e34b2c8fa6fa35c9d2732000`; after PR #24 merged, reapplied the feature on `feature/campaign-shot-editor-integration` to integrate cleanly with the persisted stock-footage source list.
- 2026-11-19: PR #24 added opt-in Pexels campaign footage discovery and was squash-merged into `main` as `45cf0a0653d11eceb56d8b104786f1821da9801c`; post-merge CI passed.
- 2026-11-19: Implemented the campaign storyboard editor, integrated it on top of PR #24's persisted `campaign_sources` data, and merged PR #26 into `main` as `67f8ec1e00c6b622a56750df035c61df3629a8ec`. CI passed: 95 backend tests passed, 15 skipped; Ruff lint/format and frontend build passed. The earlier PR #25 was closed as superseded during integration. A real-media FFmpeg/Windows smoke test remains.

### Feature Development update: Cinematic campaign camera motion

**Objective:** Improve the visual energy of campaign edits with subtle per-shot camera movement while preserving fast CPU rendering and existing edit timing.

**Implementation**
- Added a deterministic Ken Burns-style crop filter with gentle alternating horizontal/vertical movement across shots.
- Added a creator-facing toggle, enabled by default, with a static-crop fallback.
- Preserved existing color treatment, beat-aligned cut selection, source order, campaign music, hook and lyric overlays.
- Added a camera-motion quality-check field.

**Files changed**
- `src/clipyyy/render.py`
- `src/clipyyy/pipeline.py`
- `frontend/src/api.ts`
- `frontend/src/pages/NewRun.tsx`
- `tests/test_render.py`
- `tests/test_pipeline.py`

**Validation**
- PR #27: [Add subtle cinematic camera movement to campaign edits](https://github.com/Parth33831/clipyyy/pull/27)
- Branch: `feature/campaign-kinetic-visuals`
- Latest commit: `841a91eb61d11a2f5a411e8a0c35db31fd5d1f4f`
- Ruff lint and format passed.
- Frontend production build passed.
- Fast backend suite passed: **96 passed, 17 skipped**, including the real FFmpeg campaign montage render test.
- Windows, macOS and full-backend/manual CI jobs were skipped; no local Windows test is claimed.
- **Status:** Merged into `main` as `942a2dbbd5ebf00fe89de9174fd3cf3c494db928` on 2026-11-21.

**Next priority after review:** Improve actual visual understanding and footage-to-brief matching. The current CPU-only local setup has a text-only Qwen model, so it cannot semantically inspect frames. Before adding a vision model, check available B: drive storage and benchmark a small local vision model; do not silently download a large model or use a paid/cloud fallback.


- 2026-11-21: Reviewed and merged PR #27, cinematic campaign camera movement, into `main` as `942a2dbbd5ebf00fe89de9174fd3cf3c494db928`. PR CI passed: 96 backend tests passed, 17 skipped; Ruff lint/format and frontend production build passed. Post-merge CI was queued; local Windows/real-media visual review remains outstanding. Next priority is an audit-led AI visual storytelling/footage-to-brief matching improvement, with no duplicate music-analysis or vision-model implementation.

### Feature Development update: Campaign black-footage quality filter

**Objective:** Prevent sustained near-black sections from being selected as campaign shots, including in the honest text-only fallback.

**Implementation**
- Added FFmpeg `blackdetect` scanning for sustained near-black intervals (0.35 seconds minimum, conservative pixel threshold).
- Filters black timestamps before local vision-model analysis and text-only scene candidate generation.
- Rejects both LLM-proposed and fallback montage shots that overlap detected black intervals.
- Merges overlapping black intervals and clamps them to source duration.
- Detection failures are non-fatal; no new dependency, model, API key, or cloud inference is introduced.

**Files changed**
- `src/clipyyy/vision.py`
- `src/clipyyy/campaign.py`
- `tests/test_vision.py`
- `tests/test_campaign.py`

**PR:** [#29 — Avoid black footage in campaign edits](https://github.com/Parth33831/clipyyy/pull/29)
- Branch: `feature/campaign-black-frame-filter-integration`
- Latest commit: `d88ab1637df8fdc92c2c7d684741588726b90b10`
- Ruff lint and format passed; frontend production build passed.
- Fast backend suite: **99 passed, 17 skipped**.
- Windows, macOS and full-backend/manual jobs were skipped; no local Windows media test is claimed.
- **Status:** Ready for Architecture review; PR #29 is open and not merged.
- PR #28 was closed as superseded after PR #27 merged while this work was underway. PR #29 is rebased on main commit `942a2db`.

**Next priority:** Improve campaign source relevance with actual local visual understanding. First benchmark an appropriate small vision model against the user's CPU/RAM constraints and available B: drive storage; do not download it or alter local machine settings without explicit approval. Until then, the application must keep reporting text-only limitations accurately.

### Feature Development update: Ready-to-post export kit

**Objective:** Make each completed run easier to publish by packaging the generated copy alongside the rendered clips.

**Implementation**
- Preserves every existing MP4 and the existing `clips.json` export.
- Adds `POSTING-COPY.txt` to the run ZIP with each clip's suggested post title, video filename, caption and hashtags.
- Handles missing captions/hashtags without failing the export.
- Entirely local/offline; does not connect accounts, upload media, or publish posts.

**Files changed**
- `src/clipyyy/api.py`
- `tests/test_api.py`

**PR:** [#31 — Include ready-to-copy posting details in clip exports](https://github.com/Parth33831/clipyyy/pull/31)
- Branch: `feature/post-ready-export-kit`
- Latest commit: `2aab80f87823a877673db58ef0b6f18099ebd2a1`
- Base: `main` at `942a2dbbd5ebf00fe89de9174fd3cf3c494db928`
- Added API test assertions for title, caption, hashtags and video filename in the posting sheet.
- CI formatting corrections: two Ruff format-only failures were fixed in follow-up commits. Latest CI rerun is pending. Windows, macOS and full-backend jobs are skipped by workflow configuration; no local test run is claimed.
- **Status:** Draft PR, awaiting CI and review. Not merged.

**Next:** After PR #31 CI/review, continue with visual footage relevance audit and a local vision-model feasibility check; do not download models or change the user's machine settings without approval.
