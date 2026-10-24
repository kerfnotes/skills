# Entrypoint, choices and stage recovery

Use this reference for preparing known choices, recovering a run, direct worker diagnostics, or importing Colab output. `SCRIPTS` is the installed skill's absolute scripts directory. All task data belongs outside the skill/repository.

## Known choices

Write only choices established in the current request. This example skips the form:

```json
{
  "sources": [{"kind": "path", "path": "/absolute/recording.m4a", "title": "Recording"}],
  "engine": "qwen-0.6b",
  "summary": "none",
  "mail": false
}
```

The request uses the existing `answers.json` shape. Optional fields are `merge` (boolean), `roster` (string array), `summary_custom` (string), `recipients` (string array), and `mail` (boolean). `summary` is `meeting`, `interview`, `lecture`, `none`, or `custom`. `engine` is `qwen-0.6b`, `qwen-1.7b`, `gemini-3.5-transcribe`, or `colab`. Unspecified choices use local Qwen 0.6B, separate recordings, meeting summary and no Mail draft. A folder expands to its directly contained audio files in filename order; an explicit merge preserves that order without adding real-world gaps.

Missing sources or an empty custom-summary brief triggers the form. Existing sources are prefilled. Voice Memos are enumerated only after the user presses the form's read/refresh control; opening a form does not read another app's data. For a user who explicitly wants a form even with complete choices:

```text
python3 SCRIPTS/form.py --prefill TASK/request.json --out TASK/answers.json --no-open
```

Then run the entrypoint using that `answers.json` as `--request`. Open the private loopback URL with the built-in browser; the server waits in the background. Never save a real private URL in screenshots meant for sharing. Form timeouts preserve known choices; ask only the remaining questions.

## Adding recordings

The source area follows Kerfwave's utility layout. Choose local files or drop files exported to Finder into the form; read or refresh Voice Memos to select from the latest 20 entries. Every selected source shares one ordered list. The list's order is the merge order, and removing a row removes that selection. Native file/folder pickers and typed paths remain under the additional import methods. Folder expansion uses direct audio children in filename order, including `.qta`. Before accepting the form, the server checks that each local file or folder is readable and usable as a source. A missing path or empty audio folder stays in the form for correction, preserving choices and completed uploads. This metadata check does not decode audio or guarantee that the source will remain unchanged; worker validation still applies.

Browser file selection and dropping use the same local upload endpoint. Each file is streamed into `TASK/inputs` with a generated filename, a 1 GiB limit and a SHA-256 receipt; larger recordings can use the native picker. A browser `File.name` is a display name, never a filesystem path. Only fully received uploads become selectable canonical `kind: path` sources. Incomplete `.part` files are removed on failure; completed local copies survive form timeout, row removal and transcription failure. Each successful upload has a sibling JSON receipt preserving its display name, size and hash. On timeout, read these receipts to recover the existing files into a new request instead of requesting another upload. Their presence does not authorize starting a worker or choosing a cloud engine. Keep the task directory for recovery.

Refreshing the same browser tab while the form server is still running restores source order, completed upload IDs and choices from token-scoped `sessionStorage`. Audio contents are never stored there. Incomplete uploads retain their position but require selecting the file again; they block submission until replaced or removed. Successful submission clears the draft. A new tab, expired server or unavailable browser storage still uses the on-disk receipts for recovery; a browser draft is not a submitted request.

Voice Memos lists this Mac's local index. It labels missing and unreadable audio separately and disables unavailable selections. An iPhone recording must first be available on the Mac through Voice Memos sync or a manual export. Do not claim missing files are necessarily in iCloud or that direct app-to-browser file-promise dragging works. Read errors stay visible in the source area; export to Finder and select/drop the file when access or the private database format is unsupported. Full Disk Access, if needed, belongs to the actual host running Python, not automatically the browser.

The index reader queries a checked private DB/WAL snapshot and never connects SQLite to the live store. Before dispatch, the entrypoint copies selected memo audio into the new task's `inputs`, checks its content and rejects a source that changes during copying. `selected-sources.json` records the selection before copying; `answers.json` references the preserved files. Use that saved `answers.json` for retries, including after the original memo is removed. Existing saved jobs remain unchanged.

The import UI uses the existing loopback server and needs no new account or package. Secure uploads pin directory file descriptors and require the supported POSIX operations; on unsupported platforms the upload endpoint reports that limitation and users can supply local paths. Voice Memos and the native picker are macOS features. Cloud upload/billing remains tied to the explicitly selected transcription engine. Files and folders already supplied in a complete request still skip the form.

## Execute and deliver

```text
python3 SCRIPTS/run.py --request TASK/request.json --task-directory TASK/job-1 --no-open
```

Each invocation claims a new job directory. It contains the resolved `answers.json`, `delivery.json`, one `run-N` per independent recording (one total for a merge), and `output-N` for each complete rendered result. `delivery.json` lists output paths, warnings, missing/retry stages, and requested summary/Mail handoffs. Its complete status describes transcription/rendering; summary reports and Mail drafts still need the skill's agent steps. A partial result exposes raw text without manufacturing timestamps or speaker labels. Source/hash/coverage validation is structural evidence, not an accuracy score. A structurally complete run with no recognized text has `empty_transcript: true` and a visible recovery message; report the requested summary as unavailable instead of inventing template content. Preserve the source and summary choice for retry.

For a Qwen merge, MLX and PyTorch transcribe each source separately, then shift its chunks and words onto the combined PCM timeline. Repeated text in different recordings is retained; silence does not require invented words. Playback and speaker analysis still use the continuous combined audio. This preserves source boundaries but cannot guarantee recognition accuracy within an individual recording; listen back when exact wording matters.

Exit 0 means complete transcription/rendering; exit 1 means failure or partial completion; exit 2 means Colab handoff; exit 130 means cancellation. Always read the manifest and worker states. The command never installs dependencies, sends mail, chooses a cloud route because a key exists, or creates an LLM summary itself.

## Stage resume

```text
python3 SCRIPTS/run.py --request TASK/request.json --task-directory TASK/job-2 --resume-from TASK/job-1/run-1 --no-open
```

Supply the same source order and engine/model. One invocation resumes one old run; for a batch, create a request containing only that run's source(s). A new model requires a new run without resume. Workers validate source identity and saved checkpoints before reuse and leave the original run unchanged. Existing completed ASR can feed missing alignment or speaker labeling. A failure before a usable checkpoint requires rerunning that earlier stage; the progress counter alone is not a text checkpoint.

Automatic resume requires the new `checkpoint.json`; legacy runs without it are not automatically reusable. Local MLX can resume alignment or diarization; PyTorch/Colab couples ASR and alignment for each source, so it resumes only after both finish for all sources. Diarization restarts that whole stage. Gemini reuses verified completed parts and sends only previously unattempted parts. A dispatched request without a reusable complete response stops automatic resend; reconcile its old state and remote resources first.

Multi-source Qwen checkpoints must have `asr_partition: source-v1`. Earlier merged checkpoints are rejected because their ASR may have collapsed repeated speech across source boundaries; start a fresh run with the saved sources instead. Single-source checkpoints remain compatible. If a later source fails, already transcribed text is retained, but an unfinished combined ASR is not a reusable ASR checkpoint.

MLX retains raw per-chunk alignment predictions and a boundary report when a known model timestamp bin crosses the true PCM endpoint; see [run-format.md](run-format.md). These files are bound into new alignment checkpoints and their warning survives stage resume. Earlier valid alignment checkpoints remain reusable; an earlier failed alignment resumes from the completed ASR. Do not rewrite old predictions, loosen validation or apply this local-bin rule to Torch's merged internal-chunk times.

If only rendering failed, fix the reported environment issue and use `transcript.py render` with a new output directory; no transcription rerun is needed. After name corrections, retain stable speaker IDs and use the same render path. A roster remains candidates, never an automatic identity map.

## Direct worker paths

The entrypoint selects the following commands. Keep direct use for diagnostics and an explicitly requested backend output that disables timestamps or diarization; first inspect the backend's actual supported options. These bundled full-workflow workers do not expose stage-disable flags. If the requested reduced output cannot be produced with an installed backend's supported options, report that limitation rather than silently performing unwanted stages or fabricating fields.

- Apple Silicon: Python from the `mlx-qwen3-asr` shebang runs `qwen_worker.py --audio FILE --run-directory NEW --model 0.6B`. Models must already be cached; inference stays offline. The Community-1 bridge under `scripts/community1-bridge/build/` labels speakers in 20-minute windows.
- Other platforms: Python in the environment prepared by `doctor.py` runs `torch_worker.py --audio FILE --out NEW/normalized-run.json --pcm NEW/canonical.wav --model 0.6B`. The runtime may download missing models on first use; it uses Nemotron for whole-recording speaker labeling. Windows/Linux device validation remains separate from the macOS CPU checks.
- Gemini: `python3 SCRIPTS/gemini_transcribe.py --audio FILE --run-directory NEW`. Before starting, disclose upload and billing. The adapter splits into at most 25-minute parts and keeps cross-part IDs separate. Inspect `google_resources` after errors/cancellation and report any resources still pending deletion. Key setup remains in [engines.md](engines.md).

Repeat `--audio` only to merge in the supplied order. Direct worker resume also takes `--resume-from OLD_RUN_DIRECTORY`, always with new outputs.

## Colab handoff and import

The entrypoint records a waiting handoff for an explicit Colab selection. Give the user the [notebook link](https://colab.research.google.com/github/kerfnotes/skills/blob/main/skills/kerf-wordprint/colab/wordprint.ipynb); for unpublished local notebook changes, upload this skill's local notebook through Colab's File menu. The user signs in, runs all cells and supplies audio. Remote notebook execution is not performed by the local entrypoint.

For each downloaded `normalized-run-*.json`, work on a copy in a new local run directory. Match its ordered source list to the local originals and confirm every SHA-256 before changing `sources[].path`. Keep actual model/platform metadata. Do not select a download by filename alone or treat an old result as the current one.

For playback, decode the matching original(s) to mono 16 kHz signed 16-bit PCM, concatenate in source order for a merge, and set `pcm` to that local WAV. If sample count validation fails, omit `pcm` and disclose no playback; do not alter durations to force a pass. Then validate/render per SKILL.md. Missing speaker output remains partial. The Colab notebook embeds the worker and runtime helper; edits must synchronize embedded source and pass `tests/test_notebook.py`.
