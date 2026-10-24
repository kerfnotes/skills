---
name: kerf-wordprint
description: "Wordprint: transcribe recordings from supplied choices or a prefilled kerf form using local Qwen, Gemini 3.5 Transcribe or Qwen on Google Colab, label speakers, then deliver a reading page, an optional summary report, and an optional Mail draft. Also merges recordings or relabels an existing transcript. Use for 音檔轉錄、逐字稿、語音備忘錄、說話者標記、會議錄音整理. Not for summarizing text that is not a recording, voice cloning, or downloading online videos."
compatibility: "Python 3.10+ (standard library only for the bundled scripts except torch_worker.py, which runs from the uv environment doctor.py --fix builds), ffmpeg, ffprobe, OpenCC, and locally cached Qwen ASR/ForcedAligner plus Community-1 (Apple Silicon) or Nemotron-3-Diarization (other machines). The form, Voice Memos reader and worker are verified only on Apple Silicon macOS. Mail draft creation was verified once on macOS with three synthetic text/PDF attachments, blank recipients and no send (2026-10-24); another host may require the user to grant Automation permission. Other machines use scripts/torch_worker.py (tested on macOS CPU; untested on Windows and Linux) or colab/wordprint.ipynb, which embeds the same worker. gemini_transcribe.py (standard library + ffmpeg, needs a Gemini API key) is verified by one real call on a 6-second two-speaker synthetic clip (2026-10-21). The Colab notebook ran end to end on a Colab T4 GPU runtime (2026-10-22, 1.7B, Nemotron found 2 speakers on a 6-second synthetic clip, validate passed); long recordings are untested."
---

# Wordprint

Produce a source-preserving transcript with timestamps and anonymous or user-supplied speaker labels, then the reading page, summary and Mail draft the user chose. Processing stays local by default: only an explicit Gemini pick uploads to Google, and only an explicit Colab pick runs on Google's machines.

`SCRIPTS` below means this skill's installed absolute `scripts/` path. Create a fresh task directory outside the skill and repository for every run.

## 1. Reuse choices, ask only for what is missing

For relabeling or renaming an existing transcript, go to step 4 with its run JSON. For missing alignment or diarization, use stage resume in step 3; name changes alone never rerun ASR.

Create `TASK/request.json` from the current request using the [workflow contract](references/workflow.md). Preserve explicit choices, including `summary: "none"`, `mail: false`, `merge: false`, and an explicit `qwen-1.7b`. Defaults for an unspecified choice are local Qwen 0.6B, separate runs, meeting summary, and no Mail draft. A request for the large model or higher accuracy selects 1.7B for all files in this request; do not inherit prior tasks' selections.

- Resolved sources and a nonempty custom brief (only for `summary: "custom"`) are enough to proceed. Missing optional names or recipients do not block. An ambiguous recording reference must be resolved first; never guess a file.
- When sources or the custom brief are missing, the entrypoint opens the form with known choices prefilled. Read Voice Memos only through the form's explicit read/refresh action. Users can also select/drop files into local task storage; see [workflow.md](references/workflow.md#adding-recordings) for import limits and recovery. Run in the background with `--no-open`, then open its private loopback URL in the agent's built-in browser. A timeout preserves known choices and completed uploads; ask only for the reported missing fields. Never expose the private URL in a shared artifact.
- Only an explicit Gemini choice permits upload and billing. An explicit Colab choice permits the notebook handoff. Credentials or missing local dependencies never authorize a cloud fallback.
- Keep timestamps and speaker labels enabled unless explicitly disabled. For disabled stages, follow the backend-specific path in [workflow.md](references/workflow.md); do not invent fields to satisfy full-workflow validation.

## 2. Check the chosen runtime

Use `python3 SCRIPTS/doctor.py --model 0.6B` for a missing or unfamiliar local runtime (use `--model 1.7B` for an explicit 1.7B choice); its `agent`/`you` labels identify routine setup and human-only steps. Read [install.md](docs/install.md) for the chosen route's missing dependencies. Do not silently change engines or models. Never accept model terms or share credentials on the user's behalf.

## 3. Run, or resume a saved stage

```text
python3 SCRIPTS/run.py --request TASK/request.json --task-directory TASK/job-1 --no-open
```

The job directory must not exist. The entrypoint expands folders in filename order, keeps separate runs unless merging was requested, selects the platform worker, checks the normalized result, and renders complete transcripts. It writes `answers.json` and `delivery.json`; worker progress is in each `run-N/state.json`. Run long work in the background. Poll state, not just process exit status.

For a failed alignment or speaker stage, pass `--resume-from TASK/old-job/run-1` with a **new** job directory and the same source order and model. Resume handles one old run at a time. The worker verifies source identity and checkpoint compatibility before reuse; the old directory stays unchanged. An interrupted ASR without a completed checkpoint starts ASR again. If the user changes from 0.6B to 1.7B, start a fresh run without `--resume-from`; preserve completed earlier work and never mix models.

Read `delivery.json` before replying. `complete` covers transcription and rendering only; finish every `pending_agent_steps` item in steps 5–6. `partial` means deliver the preserved `raw-transcript.txt` with the named missing stage, not a complete reading page. `waiting` for Colab is a handoff, not completed processing. Check cloud resource warnings even when transcription succeeds. For commands, resume boundaries, direct worker use and Colab import, read [workflow.md](references/workflow.md).

Long local Qwen recordings retain independent `window-N-speaker-M` IDs. Before joining windows, compare multiple non-overlapping samples with the same embedding model (`speech embed-speaker … --engine coreml --json`); keep uncertain matches separate. Similarity does not establish identity. Preserve raw turns, match evidence and mapping decisions per [run-format.md](references/run-format.md).

## 4. Apply optional names

- A roster is only `participant_candidates`. It does not identify which voice belongs to whom.
- An anchored hint (first question, quoted utterance, or timestamp) can support **「說話者 2｜可能是陳先生」**. Keep the evidence and `possible` status.
- Explicit user confirmation supports a `confirmed` name. Preserve the stable speaker ID beneath the display name. Do not infer names, jobs, gender, or identity from the sound of a voice.
- Name corrections update the mapping and render to a new output directory; do not rerun ASR or rewrite its text. Do not build a persistent cross-meeting voice database.

## 5. Validate, render, and summarize

The entrypoint already validates and renders new complete runs. Reuse those outputs; after importing or changing a speaker mapping, run `python3 SCRIPTS/transcript.py validate RUN_JSON`, then `python3 SCRIPTS/transcript.py render RUN_JSON --output NEW_DIRECTORY --title "<recording title>"`. The output holds `transcript.md`/`.txt`, `transcript.html`, `transcript.srt` and `playback.wav`. `transcript.html` uses continuous reading within the original ASR chunks and source boundaries, with keyboard-accessible text-to-audio seeking. Per-row times and speaker labels remain in Markdown, text, subtitles and run data. It is a single-file text page; playback and click-to-seek work only while `playback.wav` sits in the same folder, and a run without `pcm` gets no player. `transcript.srt` requires positive whole-millisecond cue intervals. Collapsed rows may share an adjacent same-source cue while retaining each row’s text and speaker label; original word times stay unchanged. `validation.json` records `srt_written`, `srt_grouped_rows` (all rows participating in grouped cues), `srt_grouping_note`, or `srt_reason` when omitted. Keep grouping recorded as a display accommodation, not repaired alignment. If the user explicitly disables timestamps or diarization, deliver the backend's requested output and provenance instead; do not invent fields to force it through this full-workflow validator. OpenCC produces a Traditional Chinese reading copy; preserve the original ASR text separately. If OpenCC is unavailable, disclose this and use `--original-script` only for an explicitly requested original-script output.

Check source identity/order, duration coverage, truncation, alignment/text preservation, and speaker uncertainty separately. Structural checks do not establish transcription accuracy or true identity. Retain raw outputs and evidence needed to reproduce/relabel; remove only disposable audio copies created by this run.

Use the shared Clayprint light design for the input form, transcript reader, summary HTML and PDF; follow [design.md](references/design.md). Do not add routine proofreading disclaimers or a separate warning panel to these deliverables. Preserve source-specific uncertainty and actionable processing errors.

Summary, unless `summary` is `none`:

If `validation.json` reports `empty_transcript: true`, explain that there is no recognized text to summarize and offer source/model retry. Keep the requested summary choice for recovery; do not dispatch a writer or fill template sections with inferred content.

1. Dispatch one subagent with only `transcript.md`, [summary-templates.md](references/summary-templates.md), the chosen template (plus `summary_custom`) and the recording title. It writes `notes.md` beside the transcript.
2. Find Clayprint: `kerf-clayprint` beside this skill, else in the project's `.claude/skills/` or `.agents/skills/`. Build `notes.html` from `notes.md` following Clayprint's `references/report.md`, sync its CSS with `node scripts/theme-css.js notes.html`, and run `node evals/check-report.mjs notes.html notes.md` until it passes. The report carries only what notes.md says: the checker rejects any number absent from notes.md, so keep run metadata such as the model ID or duration off the report. With Chrome installed, print `notes.pdf` per the same reference.
3. Before delivery, compare every summary claim with its cited transcript, especially negations, proposals versus decisions, owners, deadlines and uncertain speakers. Then compare HTML/PDF with notes.md. Correct unsupported claims or mark them unconfirmed; the numeric/structure checker alone cannot establish semantic fidelity. This review establishes fidelity to the transcript, not accuracy against the recording.
4. Without Clayprint, deliver `notes.md` alone and say Clayprint is not installed; perform the same source review.

## 6. Mail draft and reply

When `mail` is true:

```text
python3 SCRIPTS/mail_draft.py --title "<recording title>" --summary "<notes.md 一句話結論>" [--to ADDRESS …] --attach transcript.html [--attach notes.html] [--attach notes.pdf]
```

Attach only these text files; the recipient's `transcript.html` reads without playback. It only opens a draft in Mail.app; the user sends it. Use `--dry-run` to show the AppleScript first when the user asks. A synthetic draft with three attachments and blank recipients has been verified on macOS. If Automation permission is requested, only the user can grant it; on timeout, report that draft creation is unconfirmed and inspect existing drafts before retrying.

Reply with links to `transcript.html`, `notes.html`/`notes.md` and any merged audio, the model actually used, and duration. Avoid routine proofreading disclaimers; state specific missing outputs or processing failures when they affect the requested delivery. Keep the reply short. Summaries and drafts follow `answers.json` choices only; the transcript itself stays unpolished and unpublished, and local unless the user picked Gemini or Colab.
