<div align="center">
  <img src="docs/images/logo.svg" width="112" alt="Wordprint" />
  <h1>Wordprint</h1>
  <p><b>Put a recording in, get back who said what, and when.</b></p>
  <p><a href="README.md">繁體中文</a> · English</p>
  <a href="https://github.com/kerfnotes/skills/stargazers"><img src="https://img.shields.io/github/stars/kerfnotes/skills?style=flat-square" alt="Stars"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-555?style=flat-square" alt="Platform">
  <a href="https://www.youtube.com/@kerfnotes"><img src="https://img.shields.io/badge/YouTube-Kerf-red?style=flat-square&logo=youtube" alt="YouTube"></a>
</div>

<br/>

<div align="center">
  <img src="docs/images/overview.svg" width="960" alt="Wordprint pipeline: recording, form, transcribe, align, speakers, validate, reader, Mail draft" />
</div>

## Why

Typing out a meeting recording is not the hard part. The hard part comes after: who said it, at which second, whether you can click back to hear it, and whether the summary invents decisions nobody made. Wordprint turns that whole stretch into one pipeline that Codex or Claude Code runs for you. When sources and choices are already supplied, it starts directly. Otherwise a kerf-branded form fills in known choices and asks for the missing information. It then delivers a reading page where each line can play from its spot.

The input form, transcript reader, summary HTML and PDF share Clayprint's light design; the recording-list interactions follow Kerfwave. Read Voice Memos on this Mac, select files, or drop audio from Finder into one ordered list with remove and merge controls. Browser-selected files are saved in the local task directory, with a 1 GiB limit per file; larger files can use the native picker. Missing and unreadable memos are labeled separately. See [import and preservation](references/workflow.md#adding-recordings).

Everything runs on your machine by default. Audio goes to Google only if you explicitly pick Gemini (billed; you are told before upload, and Google's copies are deleted afterwards). Picking Colab means you open the notebook with your own Google account and run on Google's GPU, with no local models and no Hugging Face account.

## What it does

| Step | What happens | Handled by |
| :--- | :--- | :--- |
| Start | Run directly from supplied choices, or fill missing information in a prefilled kerf form | `run.py`, `form.py` |
| Check-up | Checks tools and models; `--fix` runs the routine installs and leaves only passwords, accounts and permissions to you, one at a time | `doctor.py` |
| Transcribe and align | Qwen3-ASR (0.6B by default locally, 1.7B optional) plus Qwen ForcedAligner for per-word timing | `qwen_worker.py`, `torch_worker.py` |
| Speakers | Community-1 on Apple Silicon; NVIDIA Nemotron on other machines and Colab (up to 8 speakers, no token). Speakers start as Speaker 1, 2 | same |
| Validate | Checks file hashes, unchanged text and completion flags; a run missing speakers cannot pass as complete | `transcript.py validate` |
| Reader | Traditional Chinese `transcript.html` (via OpenCC), with continuous reading; click text to seek, plus `transcript.srt` when timing is complete | `transcript.py render` |
| Summary | `notes.md` from meeting, interview or talk templates; decisions only when explicitly agreed. With [Clayprint](../kerf-clayprint/) installed, also `notes.html` and PDF | agent |
| Mail draft | Opens a draft for you to review, never sends; attaches the reader and summary, not the audio | `mail_draft.py` |

It can also merge recordings, add speakers to an existing transcript, or rename speakers once you confirm names, without transcribing again.

## Four engines

| Engine | Runs on | Speed and quality | Cost |
| :--- | :--- | :--- | :--- |
| `qwen-0.6b` | Your machine | Default, speed first | Selected model must be cached |
| `qwen-1.7b` | Your machine | Optional, accuracy first | Selected model must be cached |
| `gemini-3.5-transcribe` | Google cloud | Fastest, most accurate | Audio uploaded and billed, deleted afterwards |
| `colab` | Google Colab GPU | Same as Qwen (1.7B by default) | Google sign-in and a browser |

Speed and quality are relative, not measured promises. Details in [engines.md](references/engines.md).

## Design principles

- **No guessing identities.** Speakers stay Speaker 1, 2. With hints it goes as far as "possibly X" until you confirm; a similar voice is not the same person.
- **Partial runs never pass.** A missing stage is marked partial and delivered as plain text with the gap named, never with a manufactured completion flag.
- **Keys stay out of chat.** The Gemini key is read only from an environment variable or Wordprint's own Keychain item; checks test that it exists, never read it.
- **One format.** Every engine writes the same `normalized-run.json` ([run-format.md](references/run-format.md)), so validation, rendering and summaries are written once.
- **Ready after install.** The agent does the routine installs; accounts, terms and permissions stay with you, and the agent never accepts them for you.

## Install with your agent

Give this to Codex or Claude Code:

```text
Install Wordprint (skills/kerf-wordprint) from https://github.com/kerfnotes/skills into this project.
Read skills/kerf-wordprint/docs/install.md first, pick the install path for the agent in use,
run the environment check, model setup and short-audio verification yourself,
then report the install path, version and verification results.
```

The project path is `.agents/skills/kerf-wordprint/` for Codex and `.claude/skills/kerf-wordprint/` for Claude Code. Installing the skill downloads no models; the [install guide](docs/install.md) (Traditional Chinese) covers `doctor.py --fix`, models and verification. On Windows without Python, run `winget install -e --id astral-sh.uv`, then `uv run --python 3.12 scripts/doctor.py --fix`.

With the [`skills`](https://www.npmjs.com/package/skills) CLI you can also pick from the whole repo:

```sh
npx skills add kerfnotes/skills --list
```

## Use it

After installing, just ask:

```text
Transcribe this recording
Merge this morning's two voice memos, label the speakers, and write meeting notes
```

Or invoke `$kerf-wordprint` in Codex and `/kerf-wordprint` in Claude Code.

## Entrypoint and recovery

`scripts/run.py --request /absolute/task/request.json --task-directory /absolute/task/job-1 --no-open` dispatches the selected worker, validates outputs and renders complete transcripts. `delivery.json` lists artifacts, warnings and pending summary/Mail draft handoffs. Add `--resume-from /absolute/task/job-1/run-1` with a new job directory to reuse compatible stage checkpoints without modifying the previous run. Resume checks source identity, order and model; incomplete stages without a usable checkpoint must run again. Raw text remains available when speaker labeling fails. See [workflow.md](references/workflow.md) for choices and Colab import.

## Verification status

| Item | Status |
| :--- | :--- |
| Apple Silicon Mac: form, Voice Memos, MLX transcription, speakers | Verified |
| Gemini real API call (6-second two-speaker synthetic clip) | Verified once |
| Colab T4 GPU: 1.7B, Nemotron with two speakers | Verified once (short synthetic clip) |
| PyTorch route (for Windows, Linux, Intel Mac) | Same code verified on macOS; untested on real Windows and Linux |
| Speed and accuracy on long, multi-speaker recordings | Untested |
| Creating a real Mail draft | Verified once: three synthetic text/PDF attachments, blank recipients, not sent |

## Known limits

- Reading Voice Memos needs Full Disk Access for your terminal; otherwise drag the memos into a folder and pick that path.
- If macOS asks whether to allow control of Mail, you grant permission yourself; another host may need its own authorization.
- Store the Gemini key yourself with `security add-generic-password -s kerf-wordprint-gemini -a wordprint -w` (on Windows, set the `GEMINI_API_KEY` environment variable).
- Without a GPU, the PyTorch route is slow on long recordings.
- Validation confirms timing coverage, unchanged text and consistent labels, not recognition accuracy; listen again for anything important. Speaker clusters are model guesses, not proof of identity.

License: [MIT](LICENSE). Models carry their own licenses; see the [install guide](docs/install.md).
