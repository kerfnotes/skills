#!/usr/bin/env python3
"""Validate normalized ASR/alignment/diarization results and render losslessly.

This is a postprocessor, not an inference engine. All times are global seconds.
Use --help for the CLI. Input and output JSON preserve original model text.
"""
import argparse
import hashlib
import html
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.parse
import wave
from pathlib import Path

EPS = 0.02  # Accommodate rounding to centiseconds, never invent missing audio.


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def number(value, where):
    require(type(value) in (int, float) and math.isfinite(value), f'{where}: finite number required')
    return value


def string(value, where, nonempty=True):
    require(isinstance(value, str), f'{where}: string required')
    require(not nonempty or bool(value.strip()), f'{where}: empty string')
    return value


def normalized(text):
    """Ignore only whitespace, Unicode punctuation and case, not symbols/digits."""
    return ''.join(c.casefold() for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result


def interval(item, where, limit):
    require(isinstance(item, dict), f'{where}: object required')
    start, end = number(item.get('start'), f'{where}.start'), number(item.get('end'), f'{where}.end')
    require(0 <= start <= end <= limit + EPS, f'{where}: invalid time interval')
    return start, end


def validate(path):
    path = Path(path).resolve()
    run = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=object_pairs)
    require(isinstance(run, dict) and type(run.get('schema_version')) is int and run['schema_version'] == 1,
            'schema_version must be 1')
    model = run.get('model')
    require(isinstance(model, dict), 'model: object required')
    string(model.get('id'), 'model.id')
    require(model.get('size') in ('0.6B', '1.7B'), 'model.size must be 0.6B or 1.7B')
    named_sizes = {size for size in ('0.6B', '1.7B') if size.casefold() in model['id'].casefold()}
    require(not named_sizes or named_sizes == {model['size']}, 'model.id and model.size disagree')
    require(run.get('diarization_complete') is True, 'diarization_complete must be true; partial runs cannot render as complete')
    sources = run.get('sources')
    require(isinstance(sources, list) and sources, 'sources: nonempty array required')
    duration = 0.0
    for i, source in enumerate(sources):
        where = f'sources[{i}]'
        require(isinstance(source, dict), f'{where}: object required')
        source_path = Path(string(source.get('path'), f'{where}.path'))
        source_path = (path.parent / source_path).resolve() if not source_path.is_absolute() else source_path.resolve()
        require(source_path.is_file(), f'{where}: audio file not found: {source_path}')
        fingerprint = string(source.get('sha256'), f'{where}.sha256')
        require(re.fullmatch('[0-9a-f]{64}', fingerprint) is not None, f'{where}: invalid SHA256')
        hasher = hashlib.sha256()
        with source_path.open('rb') as audio:
            for block in iter(lambda: audio.read(1024 * 1024), b''):
                hasher.update(block)
        require(hasher.hexdigest() == fingerprint, f'{where}: audio SHA256 mismatch')
        offset = number(source.get('offset'), f'{where}.offset')
        length = number(source.get('duration'), f'{where}.duration')
        require(length > 0 and offset >= 0 and abs(offset - duration) <= EPS, f'{where}: source offsets must be continuous')
        if 'sample_count' in source or 'sample_rate' in source:
            count, rate = source.get('sample_count'), source.get('sample_rate')
            require(type(count) is int and count > 0 and type(rate) is int and rate > 0,
                    f'{where}: sample_count and sample_rate must both be positive integers')
            require(abs(length - count / rate) <= EPS, f'{where}: duration differs from PCM sample count')
        duration += length
        source['path'] = str(source_path)  # Saved manifest stays resolvable in its new directory.
    if 'pcm' in run:
        pcm = Path(string(run['pcm'], 'pcm'))
        pcm = (path.parent / pcm).resolve() if not pcm.is_absolute() else pcm.resolve()
        require(pcm.is_file(), f'pcm: canonical PCM not found: {pcm}')
        try:
            with wave.open(str(pcm), 'rb') as audio:
                shape, frames = (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), audio.getnframes()
                present = 0  # The header's frame count is a claim; count the bytes actually on disk.
                while block := audio.readframes(1 << 20):
                    present += len(block)
        except (wave.Error, EOFError) as error:
            raise Invalid(f'pcm: unreadable WAV: {error}')
        require(shape == (1, 2, 16000), 'pcm: canonical PCM must be mono 16-bit 16 kHz WAV')
        require(present == frames * 2, f'pcm: header declares {frames} frames but data holds {present // 2}')
        require(abs(frames / 16000 - duration) <= EPS, 'pcm: sample count differs from source durations')
        run['pcm'] = str(pcm)
    speakers = run.get('speakers')
    require(isinstance(speakers, dict), 'speakers: object required (anonymous IDs map to {})')
    for key, speaker in speakers.items():
        string(key, 'speaker ID')
        require(isinstance(speaker, dict), f'speakers.{key}: object required')
        if speaker:
            string(speaker.get('name'), f'speakers.{key}.name')
            require(speaker.get('status') in ('confirmed', 'possible'), f'speakers.{key}.status: confirmed or possible required')
            string(speaker.get('evidence'), f'speakers.{key}.evidence')
    candidates = run.get('participant_candidates', [])
    require(isinstance(candidates, list), 'participant_candidates: array required')
    for candidate in candidates:
        string(candidate, 'participant candidate')
    turns = run.get('turns')
    require(isinstance(turns, list), 'turns: array required')
    previous = -1
    for i, turn in enumerate(turns):
        start, end = interval(turn, f'turns[{i}]', duration)
        require(start >= previous and end > start, f'turns[{i}]: nonempty turns must be sorted by start')
        require(isinstance(turn.get('speaker'), str) and turn['speaker'] in speakers, f'turns[{i}]: unknown speaker ID')
        previous = start
    chunks = run.get('chunks')
    require(isinstance(chunks, list) and chunks, 'chunks: nonempty array required')
    cursor, word_count = 0, 0
    for i, chunk in enumerate(chunks):
        where = f'chunks[{i}]'
        start, end = interval(chunk, where, duration)
        require(end > start and abs(start - cursor) <= EPS, f'{where}: chunks must continuously cover the full recording')
        require(chunk.get('complete') is True and chunk.get('truncated') is False,
                f'{where}: require complete=true and truncated=false from inference completion evidence')
        text = string(chunk.get('text'), f'{where}.text', nonempty=False)
        words = chunk.get('words')
        require(isinstance(words, list), f'{where}: missing word alignment')
        character_ends, characters = set(), 0
        for char in text:
            characters += len(normalized(char))
            character_ends.add(characters)
        previous_start, previous_end, word_text, aligned_characters = start, start, '', 0
        for j, word in enumerate(words):
            wstart, wend = interval(word, f'{where}.words[{j}]', duration)
            require(start - EPS <= wstart <= wend <= end + EPS
                    and wstart >= previous_start - EPS and wend >= previous_end - EPS,
                    f'{where}.words[{j}]: alignment outside chunk or out of order')
            token = string(word.get('text'), f'{where}.words[{j}].text')
            token_text = normalized(token)
            require(bool(token_text), f'{where}.words[{j}]: attach standalone punctuation to an adjacent word')
            aligned_characters += len(token_text)
            require(aligned_characters in character_ends,
                    f'{where}.words[{j}]: alignment splits or exceeds a source character; regroup or realign')
            word_text += token
            previous_start, previous_end = wstart, wend
        require(normalized(word_text) == normalized(text), f'{where}: missing alignment or word text differs from original')
        word_count += len(words)
        cursor = end
    require(abs(cursor - duration) <= EPS, 'chunks do not cover the recording end')
    report = {'ok': True, 'duration': duration, 'sources': len(sources), 'chunks': len(chunks), 'words': word_count,
              'source_sha256_verified': True, 'pcm_verified': 'pcm' in run,
              'text_match': 'ignore Unicode punctuation, whitespace and case only',
              'limits': 'Structural validation and recorded completion flags cannot prove ASR accuracy or unheard speech.'}
    return run, report


def classify(word, turns):
    """Conservative word attribution: never let a sentence majority erase an interjection."""
    # ponytail: O(words * turns); use an interval sweep if long-run postprocessing dominates.
    start, end = word['start'], word['end']
    intersections = [(max(start, t['start']), min(end, t['end']), t['speaker'])
                     for t in turns if t['start'] < end and t['end'] > start]
    ids = tuple(sorted({speaker for _, _, speaker in intersections}))
    if not ids:
        return 'unknown', ()
    # Different voices active at the same instant, not merely a turn boundary.
    for i, (a, b, speaker) in enumerate(intersections):
        if any(other != speaker and min(b, d) > max(a, c) for c, d, other in intersections[i + 1:]):
            return 'overlap', ids
    if len(ids) > 1:
        return 'uncertain', ids
    # Union intervals so duplicated turns never inflate confidence.
    covered, cursor = 0.0, start
    for a, b, _ in sorted(intersections):
        covered += max(0.0, b - max(cursor, a))
        cursor = max(cursor, b)
    return ('speaker' if covered > 0 and covered >= (end - start) * 0.5 else 'uncertain'), ids


def pieces(chunk):
    """Map aligned tokens back onto exact original characters, retaining punctuation."""
    text = chunk['text']
    positions = [i for i, c in enumerate(text) if not c.isspace() and not unicodedata.category(c).startswith('P')
                 for _ in c.casefold()]
    consumed, cursor = 0, 0
    for word in chunk['words']:
        consumed += len(normalized(word['text']))
        boundary = positions[consumed] if consumed < len(positions) else len(text)
        if consumed < len(positions):
            for i in range(positions[consumed - 1] + 1, boundary):
                if unicodedata.category(text[i]) in ('Ps', 'Pi'):
                    boundary = i  # Opening quotes/brackets belong with the following word.
                    break
        yield word, text[cursor:boundary]
        cursor = boundary


def rows(run):
    for chunk in run['chunks']:
        current = None
        if not chunk['words'] and chunk['text']:
            yield {'start': chunk['start'], 'end': chunk['end'], 'kind': 'unknown', 'speakers': (), 'text': chunk['text']}
        for word, text in pieces(chunk):
            kind, speakers = classify(word, run['turns'])
            if current is not None and (current['kind'], current['speakers']) == (kind, speakers):
                current['text'] += text
                current['end'] = max(current['end'], word['end'])
            else:
                if current is not None:
                    yield current
                current = {'start': word['start'], 'end': word['end'], 'kind': kind, 'speakers': speakers, 'text': text}
        if current is not None:
            yield current


def millis(seconds):
    return round(seconds * 1000)


def stamp(seconds):
    ms = millis(seconds)
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02}.{ms:03}'


def label(row, speakers):
    names = []
    for key in row['speakers']:
        info = speakers[key]
        names.append(f'{key}｜可能是 {info["name"]}' if info.get('status') == 'possible'
                     else f'{key}｜{info["name"]}' if info else key)
    joined = '、'.join(names)
    return {'unknown': '未辨識說話者', 'uncertain': f'說話者不確定：{joined}',
            'overlap': f'重疊發言：{joined}', 'speaker': joined}[row['kind']]


def markdown(text):
    return re.sub(r'([\\`*_{}\[\]<>()#+.!|~-])', r'\\\1', text)


FALLBACK_CSS = """:root { --cp-paper: #FAF9F5; --cp-ink: #141413; --cp-muted: #5E5D59; --cp-title: #141413; --cp-line: #E8E6DC;
  --cp-accent: #C2553A; --cp-tint: #F5E6DE; --cp-small: 12px; --cp-sub: 18px; --cp-title-size: 28px;
  --cp-font: "Helvetica Neue", "Segoe UI", "Arial", "PingFang TC", "Microsoft JhengHei", sans-serif; }
* { box-sizing: border-box; }
html { color: var(--cp-ink); background: var(--cp-paper); font-family: var(--cp-font); font-size: 16px; line-height: 1.65; }
body { margin: 0 auto; padding: 0 24px 72px; max-width: 940px; overflow-wrap: anywhere; }
h1, h2, h3 { color: var(--cp-title); line-height: 1.25; }
a { color: var(--cp-accent); }
.report-cover { padding: 48px 0 32px; border-bottom: 3px solid var(--cp-accent); }
.eyebrow { color: var(--cp-accent); font-size: var(--cp-small); font-weight: 700; letter-spacing: .08em; }
.cover-meta { display: flex; flex-wrap: wrap; gap: 10px 28px; color: var(--cp-muted); font-size: var(--cp-small); }
.cover-meta dt { font-weight: 700; } .cover-meta dd { margin: 0; }
section { margin-top: 40px; }"""


def clayprint_dir():
    """Sibling install first, then the current project's Claude/Codex skill folders."""
    for root in (Path(__file__).resolve().parents[2], Path.cwd() / '.claude/skills', Path.cwd() / '.agents/skills'):
        if (root / 'kerf-clayprint/scripts/theme-css.js').is_file():
            return root / 'kerf-clayprint'
    return None


def clayprint_css():
    """Active Clayprint design-layer CSS, or the bundled clay fallback when Clayprint/node is absent."""
    found, node = clayprint_dir(), shutil.which('node')
    if found and node:
        result = subprocess.run([node, str(found / 'scripts/theme-css.js')], capture_output=True, text=True,
                                encoding='utf-8', check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    return FALLBACK_CSS


def srt_stamp(seconds):
    return stamp(seconds).replace('.', ',')


def page(title, rows_html, markdown_text, meta, playback):
    """Single-file reading page: click a row to seek; copy Markdown; mail with subject."""
    payload = json.dumps(markdown_text, ensure_ascii=False).replace('<', '\\u003c')
    subject = urllib.parse.quote(f'逐字稿：{title}')
    audio = '<audio controls preload="metadata" src="playback.wav"></audio>' if playback else ''
    hint = '點任一段可跳到該處播放（需與 playback.wav 同資料夾）。' if playback else '此份沒有音訊，無法跳播。'
    meta_html = ''.join(f'<div><dt>{html.escape(k)}</dt><dd>{html.escape(v)}</dd></div>' for k, v in meta)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>逐字稿：{html.escape(title)}</title>
<style id="clayprint-theme">
{clayprint_css()}
</style>
<style>
.player {{ position: sticky; top: 0; z-index: 1; display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
  padding: 12px 0; background: var(--cp-paper); border-bottom: 1px solid var(--cp-line); }}
.player audio {{ flex: 1 1 320px; }}
.player button, .player a {{ font: inherit; font-size: var(--cp-small); padding: 6px 12px; border: 1px solid var(--cp-accent);
  border-radius: 4px; background: none; color: var(--cp-accent); cursor: pointer; text-decoration: none; }}
.seg {{ max-width: none; margin: 0; padding: 10px 8px; border-bottom: 1px solid var(--cp-line); cursor: pointer; }}
.seg:hover, .seg:focus, .seg.now {{ background: var(--cp-tint); outline: none; }}
.who {{ display: block; color: var(--cp-muted); font-size: var(--cp-small); }}
</style>
</head>
<body>
<main>
<header class="report-cover">
<p class="eyebrow">Wordprint 逐字稿</p>
<h1>{html.escape(title)}</h1>
<p>模型推定說話者；可能身分與不確定／重疊發言均保留標記。{hint}</p>
<dl class="cover-meta">{meta_html}</dl>
</header>
<div class="player">{audio}<button type="button" id="copy">複製 Markdown</button><a href="mailto:?subject={subject}">寄信</a></div>
<section aria-label="逐字稿">
{rows_html}
</section>
</main>
<script type="application/json" id="markdown">{payload}</script>
<script>
const audio = document.querySelector('audio');
const segs = [...document.querySelectorAll('[data-start]')];
const seek = (el) => {{ if (audio) {{ audio.currentTime = Number(el.dataset.start); audio.play(); }} }};
segs.forEach((el) => {{
  el.addEventListener('click', () => seek(el));
  el.addEventListener('keydown', (e) => {{ if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); seek(el); }} }});
}});
if (audio) audio.addEventListener('timeupdate', () => {{
  segs.forEach((el) => el.classList.toggle('now', audio.currentTime >= Number(el.dataset.start) && audio.currentTime < Number(el.dataset.end)));
}});
document.getElementById('copy').addEventListener('click', async (e) => {{
  try {{ await navigator.clipboard.writeText(JSON.parse(document.getElementById('markdown').textContent)); e.target.textContent = '已複製'; }}
  catch {{ e.target.textContent = '瀏覽器不允許複製'; }}
}});
</script>
</body>
</html>
"""


def render(run, report, output, original_script=False, opencc='opencc', title=None):
    output = Path(output).resolve()
    require(not output.exists(), f'output already exists; choose a new directory: {output}')
    require(output.parent.is_dir(), 'output parent directory does not exist')
    rendered = list(rows(run))
    texts = [row['text'] for row in rendered]
    if not original_script:
        binary = shutil.which(opencc)
        require(binary is not None, 'OpenCC not found; install it or explicitly pass --original-script')
        # Convert only transcript text; identity labels and source evidence remain untouched.
        # ponytail: one OpenCC process per row; batch conversion if measured startup cost dominates.
        for i, text in enumerate(texts):
            result = subprocess.run([binary, '-c', 's2twp.json'], input=text, text=True, encoding='utf-8',
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            require(result.returncode == 0 and (not text or bool(result.stdout)), f'OpenCC failed: {result.stderr.strip()}')
            texts[i] = result.stdout
    raw = '\n'.join(chunk['text'] for chunk in run['chunks']) + '\n'
    transcript, md = [], ['# 含時間與說話者逐字稿', '', '模型推定說話者；可能身分與不確定／重疊發言均保留標記。', '']
    segments, cues = [], []
    # SRT carries whole milliseconds, so check the cue times it would actually write; never nudge a time.
    srt_reason = 'no rows' if not rendered else next(
        (f'row {i}: end does not exceed start after millisecond rounding' for i, r in enumerate(rendered, 1)
         if not (math.isfinite(r['start']) and math.isfinite(r['end']) and millis(r['end']) > millis(r['start']))), None)
    srt_ok = srt_reason is None
    for i, (row, text) in enumerate(zip(rendered, texts), 1):
        who = label(row, run['speakers'])
        header = f'[{stamp(row["start"])}–{stamp(row["end"])}] {who}'
        transcript.append(f'{header}\n{text}\n')
        md.extend([f'**{markdown(header)}**', '', markdown(text), ''])
        segments.append(f'<p class="seg" tabindex="0" data-start="{row["start"]:.3f}" data-end="{row["end"]:.3f}">'
                        f'<span class="who">{html.escape(header)}</span>{html.escape(text.strip())}</p>')
        cues.append(f'{i}\n{srt_stamp(row["start"])} --> {srt_stamp(row["end"])}\n[{who}] {text.strip()}\n')
    title = title or '＋'.join(Path(s['path']).stem for s in run['sources'])
    playback = run.get('pcm')
    saved = dict(run, pcm=str(output / 'playback.wav')) if playback else run
    meta = [('模型', run['model']['id']), ('長度', stamp(report['duration'])), ('來源', f'{len(run["sources"])} 個檔案')]
    files = {'raw.txt': raw, 'raw.md': '# 模型原始逐字稿\n\n' + markdown(raw),
             'transcript.txt': '\n'.join(transcript), 'transcript.md': '\n'.join(md),
             'transcript.html': page(title, '\n'.join(segments), '\n'.join(md), meta, playback),
             'run.json': json.dumps(saved, ensure_ascii=False, indent=2) + '\n'}
    if srt_ok:
        files['transcript.srt'] = '\n'.join(cues)
    final_report = dict(report, reading_script='original' if original_script else 'OpenCC s2twp.json',
                        srt_written=srt_ok, **({} if srt_ok else {'srt_reason': srt_reason}),
                        playback_written=bool(playback),
                        unknown_rows=sum(r['kind'] == 'unknown' for r in rendered),
                        uncertain_rows=sum(r['kind'] == 'uncertain' for r in rendered),
                        overlap_rows=sum(r['kind'] == 'overlap' for r in rendered))
    temp = Path(tempfile.mkdtemp(prefix='.transcript-', dir=output.parent))
    try:
        files['validation.json'] = json.dumps(final_report, ensure_ascii=False, indent=2) + '\n'
        for name, content in files.items():
            (temp / name).write_text(content, encoding='utf-8')
        if playback:
            shutil.copyfile(playback, temp / 'playback.wav')
        # mkdir claims the destination without overwriting a concurrently created directory.
        output.mkdir()
        try:
            for item in temp.iterdir():
                item.replace(output / item.name)
        except Exception:
            shutil.rmtree(output)
            raise
    finally:
        shutil.rmtree(temp)
    return final_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('validate', 'render'):
        command = sub.add_parser(name)
        command.add_argument('run', type=Path, help='normalized schema_version=1 run.json; source hashes rechecked')
        if name == 'render':
            command.add_argument('--output', type=Path, required=True, help='new output directory (parent must exist)')
            command.add_argument('--original-script', action='store_true', help='explicitly skip Traditional Chinese conversion')
            command.add_argument('--opencc', default='opencc', help='OpenCC command/path; defaults to opencc on PATH, s2twp.json')
            command.add_argument('--title', help='reading-page title; defaults to source file names')
    args = parser.parse_args(argv)
    try:
        run, report = validate(args.run)
        if args.command == 'render':
            report = render(run, report, args.output, args.original_script, args.opencc, args.title)
        print(json.dumps(report))  # ASCII-safe CLI JSON also works with legacy Windows stdout encodings.
        return 0
    except (Invalid, OSError, ValueError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
