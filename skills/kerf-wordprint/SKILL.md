---
name: kerf-wordprint
description: "Wordprint: guided local transcription — pick Voice Memos or audio files in a one-page form, transcribe with Qwen, label speakers, then deliver a reading page, an optional summary report, and an optional Mail draft. Also merges recordings or relabels an existing transcript. Use for 音檔轉錄、逐字稿、語音備忘錄、說話者標記、會議錄音整理. Not for summarizing text that is not a recording, voice cloning, or downloading online videos."
compatibility: "Python 3.10+ (standard library only for the bundled scripts), ffmpeg, ffprobe, OpenCC, and locally cached Qwen ASR/ForcedAligner plus Community-1. The form, Voice Memos reader and worker are verified only on Apple Silicon macOS. The Mail draft is verified as --dry-run only; a real draft awaits the user granting macOS Automation permission. The Windows route is documented but untested."
---

# Wordprint

Produce a source-preserving transcript with timestamps and anonymous or user-supplied speaker labels, then the reading page, summary and Mail draft the user chose. Processing stays local; only an explicit Gemini choice may upload, and Gemini is not implemented yet.

`SCRIPTS` below means this skill's installed absolute `scripts/` path. Create a fresh task directory outside the skill and repository for every run.

## 1. Collect choices

Skip this step when the request only relabels, renames, or re-times an existing transcript; go to step 4 with its run.json.

1. `python3 SCRIPTS/voice_memos.py > TASK/memos.json`. Exit 3 means no Full Disk Access: pass its message to the user and continue without `--memos`.
2. `python3 SCRIPTS/form.py --memos TASK/memos.json --out TASK/answers.json`. It opens the browser and prints `answers.json` when the user submits. Exit 2 means it timed out: ask the questions it printed, in text, and write the same answers.json shape yourself.
3. Read answers.json:
   - `sources` in order. A `path` that is a folder means its audio files sorted by name. With `merge: false`, each source is its own run.
   - `engine`: `qwen-0.6b` → `--model 0.6B`; `qwen-1.7b` → `--model 1.7B`. `gemini-3.5-transcribe`: tell the user "Gemini 尚未實作，這次改用本機 Qwen 0.6B", then run 0.6B and say so in the final reply. See [engines.md](references/engines.md).
   - `roster` → `participant_candidates` in step 4. `summary`, `summary_custom`, `recipients`, `mail` drive steps 5–6.

Model rules hold whatever the form says:

- Process sources separately unless the user requests merging; then preserve their listed order and record each source's offset. Never insert the real-world gap between recordings without a request.
- Use Qwen **0.6B** by default without asking. Use **1.7B** when the user asks for the large model or higher accuracy; one request covers all of its files. Do not inherit a previous request's choice.
- If the user asks for 1.7B after a 0.6B run has started, announce the switch, preserve completed work, and rerun into a new run directory via supported cancellation or after the current chunk. Deliver the 1.7B result and keep the earlier run as evidence. Never mix models; name hints alone do not restart ASR.
- Keep timestamps and speaker labels enabled for both sizes unless explicitly disabled. Missing names never block processing. Existing transcripts needing only labels, names, or timestamps do not rerun ASR.

## 2. Check the local runtime

Discover installed executables, model caches, platform, and accelerators; never copy paths from another user's machine. Read [setup.md](references/setup.md) only for missing dependencies, unfamiliar platforms, or model access requirements.

- Worker Python: the interpreter on the shebang of `which mlx-qwen3-asr` (`head -1 "$(which mlx-qwen3-asr)"`). The bundled scripts other than the worker run on any `python3`.
- Speaker backend: `SCRIPTS/community1-bridge/build/community1-bridge` runs offline under `sandbox-exec`. When it is missing, build it with `sh SCRIPTS/community1-bridge/build.sh` (Xcode Command Line Tools). Without it the worker falls back to `speech diarize`, which contacts the network; say so in the reply.
- A missing requested model is a setup issue, not permission to silently switch models. Never accept model terms or share credentials on the user's behalf.

## 3. Transcribe, align, and label

```text
WORKER_PYTHON SCRIPTS/qwen_worker.py --audio FILE [--audio FILE2 …] --run-directory TASK/run-N --model 0.6B
```

Repeat `--audio` only for a merge. `--run-directory` must be new or empty; the worker refuses any other directory and leaves it untouched. The worker decodes each source to canonical mono 16 kHz PCM, concatenates in order and checks the sample-count sum, then runs ASR, ForcedAligner on the unchanged ASR text, and Community-1 in 20-minute windows. It prints `progress:` lines and writes `normalized-run.json`, `state.json` (stage, warnings, network), raw outputs and logs into the run directory; it never downloads models. `state.json` stage `partial` means a stage failed: deliver the raw transcript with the missing stage named; never fabricate word times or speakers. Stage `failed` with a source-changed error means the file was modified mid-decode; `sources.json` holds `sha256_before_decode` and `sha256_after_decode`, so ask the user which version to transcribe.

After it finishes:

- One window yields speaker IDs `S1`, `S2`…. Longer audio keeps `window-N-speaker-M`. Before joining window IDs, compare multiple non-overlapping voice samples with the same embedding model (`speech embed-speaker … --engine coreml --json`). Keep uncertain matches separate; similarity is not identity proof or a calibrated probability. Never infer identity from file boundaries or force speaker count from a candidate name list.
- Preserve raw turns, embedding-match evidence, and mapping decisions in the run directory. The format is in [run-format.md](references/run-format.md).

Windows or a machine without the worker's backends: run official Qwen/PyTorch and pyannote, write the same normalized run per run-format.md, and continue at step 4.

## 4. Apply optional names

- A roster is only `participant_candidates`. It does not identify which voice belongs to whom.
- An anchored hint (first question, quoted utterance, or timestamp) can support **「說話者 2｜可能是陳先生」**. Keep the evidence and `possible` status.
- Explicit user confirmation supports a `confirmed` name. Preserve the stable speaker ID beneath the display name. Do not infer names, jobs, gender, or identity from the sound of a voice.
- Name corrections update the mapping and render to a new output directory; do not rerun ASR or rewrite its text. Do not build a persistent cross-meeting voice database.

## 5. Validate, render, and summarize

Run `python3 SCRIPTS/transcript.py validate RUN_JSON`, then `python3 SCRIPTS/transcript.py render RUN_JSON --output NEW_DIRECTORY --title "<recording title>"`. The output holds `transcript.md`/`.txt`, `transcript.html`, `transcript.srt` and `playback.wav`. `transcript.html` is a single-file text page; playback and click-to-seek work only while `playback.wav` sits in the same folder, and a run without `pcm` gets no player. `transcript.srt` is written only when every row keeps end after start at whole milliseconds (`validation.json` records `srt_written`, plus `srt_reason` when skipped). If the user explicitly disables timestamps or diarization, deliver the backend's requested output and provenance instead; do not invent fields to force it through this full-workflow validator. OpenCC produces a Traditional Chinese reading copy; preserve the original ASR text separately. If OpenCC is unavailable, disclose this and use `--original-script` only for an explicitly requested original-script output.

Check source identity/order, duration coverage, truncation, alignment/text preservation, and speaker uncertainty separately. Structural checks do not establish transcription accuracy or true identity. Retain raw outputs and evidence needed to reproduce/relabel; remove only disposable audio copies created by this run.

Summary, unless `summary` is `none`:

1. Dispatch one subagent with only `transcript.md`, [summary-templates.md](references/summary-templates.md), the chosen template (plus `summary_custom`) and the recording title. It writes `notes.md` beside the transcript.
2. Find Clayprint: `kerf-clayprint` beside this skill, else in the project's `.claude/skills/` or `.agents/skills/`. Build `notes.html` from `notes.md` following Clayprint's `references/report.md`, sync its CSS with `node scripts/theme-css.js notes.html`, and run `node evals/check-report.mjs notes.html notes.md` until it passes. The report carries only what notes.md says: the checker rejects any number absent from notes.md, so keep run metadata such as the model ID or duration off the report. With Chrome installed, print `notes.pdf` per the same reference.
3. Without Clayprint, deliver `notes.md` alone and say Clayprint is not installed.

## 6. Mail draft and reply

When `mail` is true:

```text
python3 SCRIPTS/mail_draft.py --title "<recording title>" --summary "<notes.md 一句話結論>" [--to ADDRESS …] --attach transcript.html [--attach notes.html] [--attach notes.pdf]
```

Attach only these text files; the recipient's `transcript.html` reads without playback. It only opens a draft in Mail.app; the user sends it. Use `--dry-run` to show the AppleScript first when the user asks. A real draft is still unverified: the first run waits on macOS Automation permission, which only the user can grant; on timeout, say so and hand over the `--dry-run` output.

Reply with links to `transcript.html`, `notes.html`/`notes.md` and any merged audio, the model actually used, duration, and material limitations (Gemini fallback, network-using diarization, uncertain speakers). After a 0.6B run, mention in one line that 1.7B is available if accuracy matters. Keep the reply short. Summaries and drafts follow the form's choices only; the transcript itself stays unpolished, unpublished and local.
