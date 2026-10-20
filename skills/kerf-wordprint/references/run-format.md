# Normalized run and rendering

On Apple Silicon, `qwen_worker.py` writes this format as `normalized-run.json`; on other machines the agent runs installed inference tools and converts their saved output into it. The helper does **not** run models, infer a real person's identity, or establish accuracy. Never manufacture a completion flag to satisfy validation.

Store `run.json` in the task directory, outside the installed skill. UTF-8 JSON, `schema_version: 1`:

| Field | Required meaning |
| --- | --- |
| `sources` | Ordered array of `{path, sha256, duration, offset}`; the worker also records `sha256_before_decode` and `sha256_after_decode` (equal on success). Path/hash identify each original; paths are absolute or relative to run.json. SHA-256 is lowercase hex. Duration is decoded PCM sample count / sample rate, **not container duration**; offsets start at zero and are cumulative. Keep `sample_count`, `sample_rate`, `probe_duration`, and the decode invocation as evidence. Separate recordings use separate runs unless merging was requested. |
| `model` | `{id, size}` where size is `0.6B` or `1.7B`; retain backend/version, model revision, language and invocation parameters as additional metadata. |
| `chunks` | Ordered `{start, end, text, words, complete, truncated}`. Copy exact original text; preserve every chunk including silence. `complete: true` requires successful inference evidence; `truncated: false` requires the backend's stop status or equivalent verified evidence. No gaps between chunks; final end matches total duration. |
| `chunks[].words` | Ordered `{text, start, end}` from ForcedAligner, with nondecreasing starts and ends (20 ms rounding tolerance). All times use the combined PCM clock, including chunk and source offsets exactly once. Keep punctuation in chunk text; attach punctuation-only aligner tokens to an adjacent word. Preserve symbols and numerals: a nonspoken symbol omitted by alignment may be attached verbatim to its adjacent aligned token without changing times. Do not estimate word times from text length or rewrite spoken content to pass validation. |
| `turns` | Diarization `{start, end, speaker}` sorted by start, on the same global clock. Preserve overlapping turns; use globally reconciled stable speaker IDs. |
| `diarization_complete` | `true` only after all requested audio was processed successfully. An empty turns array may represent no detected speech, not a failed stage. |
| `speakers` | Object keyed by stable speaker ID. Anonymous value: `{}`. A name requires `{name, status, evidence}`, all strings; status is `possible` or `confirmed`. Evidence states the user's anchored hint or confirmation. |
| `participant_candidates` | Optional array of names. Never automatically assigned to speaker IDs. |
| `pcm` | Optional path to the canonical mono 16-bit 16 kHz WAV (relative to run.json or absolute). Validation checks its format, that the header frame count matches the data bytes on disk, and that the sample count matches the summed source durations; render copies it to `playback.wav`. The worker always sets it. |

Preserve upstream raw JSON, the source probe result, and speaker matching evidence beside the normalized run. Record alignment and diarization model IDs/versions and parameters as additional metadata. Do not include tokens. Reuse a stage only when source hashes/order, its inputs (including transcript text for alignment), model/revision, and parameters still match; a chunk number alone proves nothing.

For MLX output, keep `chunks[].text`; assign the global aligned `segments` to their corresponding chunks without duplicating/dropping words. Prefer chunk-by-chunk alignment if global boundaries are ambiguous. Add the window offset to `speech diarize` turns, reconcile local IDs by acoustic evidence, then sort. For official PyTorch output, convert its timestamp objects to the same word format; consult the installed API rather than assuming MLX field names. The validator deliberately rejects mismatched text/times.

Use the installed absolute helper path:

```text
python transcript.py validate run.json
python transcript.py render run.json --output new-output-directory
```

The output directory must not already exist; its parent must exist. Both commands recheck source SHA-256. Default rendering uses OpenCC `s2twp.json`; `--opencc` overrides its executable path. `--original-script` explicitly skips conversion. All model text is retained in raw outputs; names and evidence are not converted. To rename, copy/update the speaker mapping in run.json and render into another directory; no model execution is needed.

Outputs: `raw.txt`, `raw.md`, `transcript.txt`, `transcript.md`, `transcript.html` (single-file text page with inline Clayprint CSS, copy-Markdown and mailto buttons; `--title` sets its heading; player and click-to-seek appear only when `pcm` is set and work only beside `playback.wav`), `run.json`, `validation.json`; `playback.wav` when `pcm` is set (the saved run.json then points `pcm` at it); `transcript.srt` only when every row keeps end after start once rounded to whole milliseconds, recorded as `srt_written` (and `srt_reason` when skipped) in validation.json. Saved source paths are resolved so a later name-only re-render works from the output directory. Keep these local paths out of public examples and review bundles.

Closing punctuation follows the preceding word; Unicode opening punctuation (`Ps/Pi`) follows the next word. Ambiguous ASCII straight quotes stay with the preceding word. Alignments splitting a single casefold-expanded source character (for example `ß` into two `s` tokens) are rejected; regroup that character's tokens or realign before rendering.

Checks cover file identity, declared source offsets, chunk coverage/completion flags, finite times and unchanged text under punctuation/whitespace/case normalization. They do not independently remeasure audio duration or verify speech accuracy. The agent must verify decoded sample counts, explain differences from container duration, and inspect upstream completion evidence first. Word attribution distinguishes a real temporal overlap from a word spanning a turn boundary; unclear/uncovered and zero-duration words remain explicitly marked. Do not label a partially completed run as complete; deliver available raw output with the missing stage stated instead.
