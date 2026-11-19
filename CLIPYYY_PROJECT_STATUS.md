# CLIPYYY Project Status & Coordination

> Shared coordination document for all ChatGPT conversations working on CLIPYYY.
> Update this file whenever a task is started, completed, paused, or handed off.
> This document is a coordination aid; Git history and reviewed code remain the source of truth.

## Project

- **Repository:** https://github.com/Parth33831/clipyyy
- **Local path (user's Windows machine):** `B:\\CLIPSTUDIO\\clipyyy`
- **Default branch:** `main`
- **Product goal:** A stable, professional AI video creation and repurposing application with capabilities approaching OpusClip.
- **Data directory:** `B:\\CLIPSTUDIO\\clipyyy-data` (keep user data separate from source code).

## Team / conversation responsibilities

| Workspace | Responsibility | Rules |
|---|---|---|
| Architecture & Master Plan | Product vision, roadmap, OpusClip capability research, cross-feature decisions and coordination | Do not independently implement overlapping features without checking current ownership first. |
| Feature Development | Implement the feature(s) explicitly assigned to that conversation | Work on a dedicated branch; preserve unrelated work; provide a complete handoff. |
| Testing & Integration | Review branches/PRs, inspect diffs, run tests and coordinate safe integration | Never merge unreviewed or conflicting changes. |

A conversation should stay within its assigned scope. If a task crosses scopes, agree on ownership here before editing.

## Repository baseline (last inspected: 2026-11-19)

- **Default branch:** `main`
- **Latest main commit observed:** `e32b05896f161fc1a50f95547a69711d4f8c2d50`
- **Commit message:** Add 1–3 word lyric caption layout (#22)
- **Other recent main commits observed:**
  - `bbc4f16e2e78d229c059e8759055de0afd4b497b` — animated lyric style previews and multi-color word captions (#21)
  - `ab61bb8c7d20a928306f9a0bf75810a549e49dec` — customizable lyric text and highlight colors (#20)
  - `9e540b18d2b45629d8adc771d8ac9ca824185c97` — instant lyric style and animation editor (#19)
- **Coordination branch:** `docs/project-coordination` (this file only; created from `main`).
- **Note:** The branches listed below were visible during inspection. Their current heads and whether they contain unmerged work must be checked before use.

### Branches observed

- `automatic-word-timed-lyrics`
- `campaign-dialogue-transcription`
- `creative-anime-editing`
- `fix/campaign-export-audio-duration`
- `fix/campaign-scene-selection-ci-final`
- `fix/campaign-scene-selection-final-ci`
- `fix/campaign-scene-selection-pacing`
- `fix/campaign-scene-selection-pacing-ci`
- `fix/campaign-scene-selection-release-check`
- `fix/campaign-scene-selection-tested`
- `fix/campaign-scene-selection-validated`
- `improve-multi-clip-selection`
- `instant-lyrics-style-editor`
- `instant-lyrics-style-editor-ci`
- `instant-lyrics-style-editor-verified`
- `lyric-style-previews-multicolor`
- `lyric-words-on-screen`
- `lyrics-captions-animation`
- `lyrics-color-controls`
- `main`
- `music-intelligence-hooks`
- `refresh-legacy-lyric-timings`
- `reuse-campaign-transcript-on-dialogue-rebuild`

## Feature status

Only mark a feature **completed** after its code is present in the target branch and tests have been reported. Do not infer completion from chat discussion alone.

| Area | Status | Owner / branch | Notes |
|---|---|---|---|
| Core video clipping pipeline | Existing implementation | TBD after code review | Verify current behavior before changing. |
| Local transcription | Existing implementation | TBD after code review | Preserve current word-level timing behavior. |
| Face-based vertical reframing | Existing implementation | TBD after code review | Future improvements must not regress current framing. |
| Animated captions | Existing implementation | Feature Development | Recent lyric animation, color and word-window work is present in recent main commits. |
| Campaign montage / music / lyrics | Existing implementation | Feature Development | Review current UI and pipeline before adding overlapping campaign features. |
| Virality scoring improvements | Not yet assessed | Unassigned | Requires architecture and product definition. |
| Advanced subject tracking | Not yet assessed | Unassigned | Avoid duplicating existing face tracking. |
| Text-based editing / filler removal | Not yet assessed | Unassigned | Requires architecture and feasibility review. |
| Advanced timeline editor | Not yet assessed | Unassigned | Requires UX and data-model planning. |
| Audio enhancement / voiceover | Not yet assessed | Unassigned | Assess local/offline options and dependencies. |
| AI B-roll improvements | Existing optional B-roll; enhancements not assessed | Unassigned | Inspect current Pexels workflow before implementing alternatives. |

## Current work

No active task ownership has been confirmed in this file yet. Each conversation must add its task here before making substantial overlapping changes.

| Task | Owner chat | Branch / PR | Status | Last update |
|---|---|---|---|---|
| _Add current tasks here_ | | | | |

## Safe development protocol

1. Before coding, inspect `git status`, current branch, `git log -5 --oneline`, and the latest remote refs.
2. Never assume the local working tree is clean. Never discard, reset, or overwrite uncommitted user work.
3. Use a dedicated feature branch from the latest appropriate base. Do not develop directly on `main`.
4. Before starting, add the task, owner chat, branch and scope to **Current work**.
5. Avoid editing files owned by another active task. If overlap is unavoidable, coordinate first.
6. Keep commits focused. Do not force-push shared branches.
7. Before integration, compare the feature branch with the intended base, inspect changed files and run relevant tests.
8. Merge only after review and successful tests. Do not merge unrelated work as part of a feature.
9. After merge, update this document with the merge commit and test results.
10. GitHub is the shared source of code truth. This Markdown file is the shared coordination log, not a live sync of chat histories or local files.

## Required handoff (copy and complete)

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
- 2026-11-19: Created this coordination document on `docs/project-coordination`; it is intentionally separate from `main` and does not change application code.
