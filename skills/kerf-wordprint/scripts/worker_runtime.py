"""Small, offline checkpoint contract shared by Wordprint workers."""
import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path
import shutil
import wave


def bound_alignment_terminal_bin(words, *, sample_count, sample_rate, quantum_seconds):
    """Intersect only an exact terminal model bin with PCM; never repair invalid ordering.

    Words use local seconds (start/end). Unknown quantum leaves them unchanged.
    Equality is exact: there is no millisecond tolerance or nearest-bin rounding.
    """
    result = [dict(word) for word in words]
    if (type(sample_count) is not int or sample_count <= 0
            or type(sample_rate) is not int or sample_rate <= 0
            or type(quantum_seconds) not in (int, float)
            or not math.isfinite(quantum_seconds) or quantum_seconds <= 0):
        return result, []
    # PCM and decimal model milliseconds define exact rational clocks. Float
    # ceil(.56 / .08) is 8, incorrectly admitting the following .64-second bin.
    quantum = Fraction(str(quantum_seconds))
    duration_exact = Fraction(sample_count, sample_rate)
    duration = float(duration_exact)
    # Convert only once, matching the provider's decimal millisecond timestamps
    # (e.g. 29.76), not repeated binary float multiplication (e.g. 29.040000000000003).
    terminal_end = float(math.ceil(duration_exact / quantum) * quantum)
    previous_start = previous_end = 0
    for word in words:
        start, end = word.get('start'), word.get('end')
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or not 0 <= start <= end or start > duration
                or start < previous_start or end < previous_end):
            return result, []
        previous_start, previous_end = start, end
    adjustments = []
    for index, word in enumerate(result):
        if word['start'] < duration < word['end'] == terminal_end:
            adjustments.append({'word_index': index, 'start': word['start'],
                                'original_end': word['end'], 'bounded_end': duration})
            word['end'] = duration
    # Intersecting a later word must not move its end before an earlier,
    # non-terminal prediction. Roll back the whole adaptation in that case;
    # canonical validation must see the original invalid boundary, not hide it
    # inside its existing rounding tolerance.
    if any(right['end'] < left['end'] for left, right in zip(result, result[1:])):
        return [dict(word) for word in words], []
    return result, adjustments


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def state(directory, value):
    value.setdefault('warnings', [])
    value.setdefault('status', 'running')
    value.setdefault('retry_stage', None)
    value['available_outputs'] = sorted(p.name for p in Path(directory).iterdir()
                                        if p.is_file() and p.suffix in ('.json', '.txt', '.wav', '.log')
                                        and p.name != 'state.json')
    save(Path(directory) / 'state.json', value)


def raw_text(directory, texts):
    text = '\n'.join(text for text in texts if text)
    if text:
        path = Path(directory) / 'raw-transcript.txt'
        temporary = path.with_suffix('.txt.tmp')
        temporary.write_text(text + '\n', encoding='utf-8')
        temporary.replace(path)


def finish_error(directory, value, error):
    cancelled = isinstance(error, KeyboardInterrupt)
    stage = value.get('stage', 'start')
    value.update(stage='cancelled' if cancelled else 'failed',
                 status='cancelled' if cancelled else ('partial' if (Path(directory) / 'raw-transcript.txt').exists() else 'failed'),
                 retry_stage=stage, error='使用者已取消；已完成的輸出仍保留。' if cancelled else str(error))
    state(directory, value)


def check_location(old, new):
    if old:
        old, new = Path(old).resolve(), Path(new).resolve()
        if old == new or old in new.parents:
            raise ValueError('續跑必須使用舊 run 以外的新目錄；既有目錄未改動。')


def checkpoint(directory, config, sources, stage, files):
    path = Path(directory) / 'checkpoint.json'
    record = json.loads(path.read_text()) if path.exists() else {
        'version': 1, 'config': config, 'sources': [s['sha256'] for s in sources], 'stages': [], 'artifacts': {}}
    for name in files:
        record['artifacts'][name] = digest(Path(directory) / name)
    if stage not in record['stages']:
        record['stages'].append(stage)
    save(path, record)
    return record


def resume(old, new, sources, config):
    """Validate everything before copying; never alter the previous run or silently fall back to ASR."""
    old, new = Path(old).resolve(), Path(new).resolve()
    check_location(old, new)
    record = json.loads((old / 'checkpoint.json').read_text(encoding='utf-8'))
    if record.get('version') != 1 or record.get('config') != config:
        raise ValueError('續跑模型或設定不符，不能重用 checkpoint。')
    if record.get('sources') != [digest(source) for source in sources]:
        raise ValueError('續跑來源雜湊或順序不符。')
    artifacts = record.get('artifacts', {})
    if not artifacts or not {'canonical.wav', 'sources.json'} <= artifacts.keys():
        raise ValueError('checkpoint 缺少 canonical audio 或來源記錄。')
    for name, expected in artifacts.items():
        path = old / name
        if Path(name).name != name or path.is_symlink() or not path.is_file() or digest(path) != expected:
            raise ValueError(f'checkpoint 檔案完整性不符：{name}')
    records = json.loads((old / 'sources.json').read_text(encoding='utf-8'))
    if [s['sha256'] for s in records] != record['sources']:
        raise ValueError('checkpoint 來源記錄不符。')
    pcm = read_pcm(old / 'canonical.wav')
    if sum(s['sample_count'] for s in records) * 2 != len(pcm):
        raise ValueError('checkpoint PCM 樣本數不符。')
    # Read the request journal before publishing any resumable checkpoint. A new
    # run interrupted during the copy must never look like no request was sent.
    prior_state = json.loads((old / 'state.json').read_text(encoding='utf-8'))
    if config.get('backend') == 'Gemini Interactions API v1beta' and (
            not isinstance(prior_state.get('part_requests'), dict) or
            not isinstance(prior_state.get('google_resources'), list)):
        raise ValueError('Gemini 續跑缺少請求或資源紀錄；停止自動重送。')
    for name in artifacts:
        shutil.copyfile(old / name, new / name)
    # Paths may move; ordered source bytes, rather than a previous machine's paths, define identity.
    for item, source in zip(records, sources):
        item['path'] = str(Path(source).resolve())
    save(new / 'sources.json', records)
    record['artifacts']['sources.json'] = digest(new / 'sources.json')
    save(new / 'resume-state.json', prior_state)
    state(new, {**prior_state, 'stage': 'resume', 'status': 'running', 'resumed_from': str(old)})
    # Publish last. If interrupted before this point, the new run is not resumable;
    # afterwards its durable state already includes every prior request/resource.
    save(new / 'checkpoint.json', record)
    return records, pcm, record, prior_state


def read_pcm(path):
    with wave.open(str(path), 'rb') as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError('checkpoint PCM 格式不符。')
        frames = audio.getnframes()
        pcm = audio.readframes(frames)
    if frames <= 0 or len(pcm) != frames * 2:
        raise ValueError('checkpoint PCM 不完整。')
    return pcm


def write_pcm(path, pcm):
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1), audio.setsampwidth(2), audio.setframerate(16000)
        audio.writeframes(pcm)
