"""Model-aware setup checks using synthetic /tmp caches and mocked processes only."""
import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / 'scripts' / 'doctor.py'
spec = importlib.util.spec_from_file_location('wordprint_doctor', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.temp = tempfile.TemporaryDirectory(prefix='wordprint-doctor-test-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in [('HUB', self.root / 'hub'), ('TORCH_VENV', self.root / 'venv'),
                            ('SPEECH_CACHE', self.root / 'speech'), ('VOICE_MEMOS', self.root / 'memos')]:
            self.patches.enter_context(patch.object(m, name, value))
        self.system = self.patches.enter_context(patch.object(m.platform, 'system', return_value='Linux'))
        self.machine = self.patches.enter_context(patch.object(m.platform, 'machine', return_value='x86_64'))
        self.patches.enter_context(patch.object(m.shutil, 'which', return_value='/mock/tool'))
        self.patches.enter_context(patch.object(m, 'run', return_value=(True, '測試')))
        self.process = self.patches.enter_context(patch.object(m.subprocess, 'run'))
        self.space = self.patches.enter_context(patch.object(m.shutil, 'disk_usage',
                                                   return_value=SimpleNamespace(free=100 * 10**9)))
        self.patches.enter_context(patch.object(m, 'worker_python', return_value='/mock/python'))
        self.patches.enter_context(patch.dict(m.os.environ, {'GEMINI_API_KEY': ''}))

    def cache(self, model, revision='a' * 40, symlinks=False):
        repo = m.HUB / ('models--' + model.replace('/', '--'))
        snapshot = repo / 'snapshots' / revision
        snapshot.mkdir(parents=True, exist_ok=True)
        (repo / 'refs').mkdir(exist_ok=True)
        (repo / 'refs/main').write_text(revision)
        files = {name: '{"fixture": true}' for name in
                 ('config.json', 'tokenizer_config.json', 'preprocessor_config.json', 'chat_template.json', 'vocab.json')}
        files['merges.txt'] = '#version: 0.2\na b\n'
        if model.endswith('1.7B'):
            files.update({'model-00001-of-00002.safetensors': 'fake first shard',
                          'model-00002-of-00002.safetensors': 'fake second shard',
                          'model.safetensors.index.json': json.dumps({'weight_map': {
                              'first': 'model-00001-of-00002.safetensors',
                              'second': 'model-00002-of-00002.safetensors'}})})
        else:
            files['model.safetensors'] = 'fake weights'
        for name, content in files.items():
            if symlinks:
                (repo / 'blobs').mkdir(exist_ok=True)
                (repo / 'blobs' / name).write_text(content)
                (snapshot / name).symlink_to('../../blobs/' + name)
            else:
                (snapshot / name).write_text(content)
        return snapshot

    def qwen_row(self, model):
        return next(row for row in m.checks(model)[0] if row[0] == 'qwen-models')

    def test_cache_requires_selected_asr_and_shared_aligner_on_each_platform(self):
        self.cache('Qwen/Qwen3-ASR-0.6B')
        for system, machine in [('Linux', 'x86_64'), ('Windows', 'AMD64'), ('Darwin', 'arm64')]:
            with self.subTest(system=system):
                self.system.return_value, self.machine.return_value = system, machine
                self.assertFalse(self.qwen_row('0.6B')[1])
                self.assertFalse(self.qwen_row('1.7B')[1])
        self.cache('Qwen/Qwen3-ForcedAligner-0.6B')
        for system, machine in [('Linux', 'x86_64'), ('Windows', 'AMD64'), ('Darwin', 'arm64')]:
            with self.subTest(system=system):
                self.system.return_value, self.machine.return_value = system, machine
                self.assertTrue(self.qwen_row('0.6B')[1])
                self.assertFalse(self.qwen_row('1.7B')[1])
        self.cache('Qwen/Qwen3-ASR-1.7B')
        shutil.rmtree(m.HUB / 'models--Qwen--Qwen3-ASR-0.6B')
        self.assertTrue(self.qwen_row('1.7B')[1])
        self.assertFalse(self.qwen_row('0.6B')[1])
        self.process.assert_not_called()

    def test_empty_repos_are_not_ready_on_any_platform(self):
        for model in m.model_ids('1.7B'):
            (m.HUB / ('models--' + model.replace('/', '--'))).mkdir(parents=True)
        for system, machine in [('Linux', 'x86_64'), ('Windows', 'AMD64'), ('Darwin', 'arm64')]:
            with self.subTest(system=system):
                self.system.return_value, self.machine.return_value = system, machine
                self.assertFalse(self.qwen_row('1.7B')[1])
        self.process.assert_not_called()

    def test_only_refs_main_snapshot_counts(self):
        snapshot = self.cache('Qwen/Qwen3-ASR-1.7B')
        self.cache('Qwen/Qwen3-ForcedAligner-0.6B')
        ref = snapshot.parent.parent / 'refs/main'
        self.assertTrue(self.qwen_row('1.7B')[1])
        for bad in ['b' * 40, '', '../snapshots/' + 'a' * 40, 'a' * 40 + '\n']:
            ref.write_text(bad)
            self.assertFalse(self.qwen_row('1.7B')[1], bad)
        (snapshot.parent / ('b' * 40)).mkdir()
        ref.write_text('b' * 40)
        self.assertFalse(self.qwen_row('1.7B')[1])
        ref.unlink()
        self.assertFalse(self.qwen_row('1.7B')[1])
        ref.symlink_to('missing')
        self.assertFalse(self.qwen_row('1.7B')[1])

    def test_required_files_must_be_nonempty_readable_regular_files(self):
        snapshot = self.cache('Qwen/Qwen3-ASR-0.6B')
        self.cache('Qwen/Qwen3-ForcedAligner-0.6B')
        self.assertTrue(self.qwen_row('0.6B')[1])
        for path in snapshot.iterdir():
            original = path.read_bytes()
            with self.subTest(file=path.name):
                path.write_bytes(b'')
                self.assertFalse(self.qwen_row('0.6B')[1])
                path.unlink()
                self.assertFalse(self.qwen_row('0.6B')[1])
                path.mkdir()
                self.assertFalse(self.qwen_row('0.6B')[1])
                path.rmdir()
                path.write_bytes(original)
                with patch.object(m.os, 'access', side_effect=lambda p, mode: Path(p) != path):
                    self.assertFalse(self.qwen_row('0.6B')[1])
                self.assertTrue(self.qwen_row('0.6B')[1])

    def test_blob_symlinks_work_but_broken_links_do_not(self):
        snapshot = self.cache('Qwen/Qwen3-ASR-1.7B', symlinks=True)
        self.cache('Qwen/Qwen3-ForcedAligner-0.6B', symlinks=True)
        self.assertTrue(self.qwen_row('1.7B')[1])
        for path in snapshot.iterdir():
            target = path.readlink()
            path.unlink()
            path.symlink_to('../../blobs/missing')
            self.assertFalse(self.qwen_row('1.7B')[1], path.name)
            path.unlink()
            path.symlink_to(target)
        self.assertTrue(self.qwen_row('1.7B')[1])

    def test_index_cannot_hide_missing_shards_or_use_invalid_paths(self):
        snapshot = self.cache('Qwen/Qwen3-ASR-1.7B')
        self.cache('Qwen/Qwen3-ForcedAligner-0.6B')
        index = snapshot / 'model.safetensors.index.json'
        original = index.read_text()
        invalid = ['{', '[]', '{}', '{"weight_map": {}}', '{"weight_map": []}']
        invalid += [json.dumps({'weight_map': {'x': name}}) for name in
                    [None, [], '../model.safetensors', '/model.safetensors', 'C:\\model.safetensors',
                     'sub/model.safetensors', 'missing.safetensors']]
        for content in invalid:
            index.write_text(content)
            self.assertFalse(self.qwen_row('1.7B')[1], content)
        index.write_text(original)
        self.assertTrue(self.qwen_row('1.7B')[1])
        (snapshot / 'model-00002-of-00002.safetensors').unlink()
        self.assertFalse(self.qwen_row('1.7B')[1])
        index.unlink()
        self.assertFalse(self.qwen_row('1.7B')[1])

    def test_extra_broken_weight_file_is_rejected_because_mlx_loads_every_shard(self):
        snapshot = self.cache('Qwen/Qwen3-ASR-0.6B')
        self.cache('Qwen/Qwen3-ForcedAligner-0.6B')
        self.assertTrue(self.qwen_row('0.6B')[1])
        (snapshot / 'extra.safetensors').symlink_to('missing')
        self.assertFalse(self.qwen_row('0.6B')[1])

    def test_cached_tree_matches_worker_ignored_files(self):
        snapshot = self.cache('Qwen/Qwen3-ASR-1.7B')
        self.cache('Qwen/Qwen3-ForcedAligner-0.6B')
        trees = snapshot.parent.parent / 'trees'
        trees.mkdir()
        tree = trees / (snapshot.name + '.json')
        files = {name: {'size': 10, 'blob_id': 'fixture'} for name in
                 ['README.md', '.gitattributes', 'generation_config.json']}
        tree.write_text(json.dumps({'format_version': 1, 'files': files}))
        self.assertFalse(self.qwen_row('1.7B')[1])
        (snapshot / 'generation_config.json').write_text('{"fixture": true}')
        self.assertTrue(self.qwen_row('1.7B')[1])
        tree.write_text('{')
        self.assertFalse(self.qwen_row('1.7B')[1])
        for data in [{'format_version': 2, 'files': files},
                     {'format_version': 1, 'files': []},
                     {'format_version': 1, 'files': {'../outside': {}}}]:
            tree.write_text(json.dumps(data))
            self.assertFalse(self.qwen_row('1.7B')[1])

    def test_malformed_config_is_not_ready(self):
        snapshot = self.cache('Qwen/Qwen3-ASR-0.6B')
        self.cache('Qwen/Qwen3-ForcedAligner-0.6B')
        (snapshot / 'config.json').write_text('{')
        self.assertFalse(self.qwen_row('0.6B')[1])

    def test_check_reads_only_small_metadata_and_never_opens_weights(self):
        self.cache('Qwen/Qwen3-ASR-1.7B', symlinks=True)
        self.cache('Qwen/Qwen3-ForcedAligner-0.6B')
        original = Path.open
        opened = []

        def guarded_open(path, *args, **kwargs):
            opened.append(path.name)
            self.assertNotEqual(path.suffix, '.safetensors')
            self.assertNotIn(path.name, ('vocab.json', 'merges.txt'))
            self.assertLessEqual(path.stat().st_size, 1024 * 1024)
            return original(path, *args, **kwargs)

        with patch.object(Path, 'open', guarded_open):
            self.assertTrue(self.qwen_row('1.7B')[1])
        self.assertIn('model.safetensors.index.json', opened)
        self.process.assert_not_called()

    def test_unreadable_metadata_reports_not_ready_without_crashing(self):
        self.cache('Qwen/Qwen3-ASR-0.6B')
        self.cache('Qwen/Qwen3-ForcedAligner-0.6B')
        with patch.object(Path, 'read_text', side_effect=PermissionError('permission denied')):
            row = self.qwen_row('0.6B')
        self.assertFalse(row[1])
        self.assertIn('permission denied', row[3])

    def test_report_discloses_qwen_and_speaker_cache_limits(self):
        self.system.return_value, self.machine.return_value = 'Darwin', 'arm64'
        self.speaker_cache()
        self.cache('Qwen/Qwen3-ASR-0.6B')
        self.cache('Qwen/Qwen3-ForcedAligner-0.6B')
        rows = {row['check']: row for row in m.report(*m.checks())[1]}
        self.assertTrue(rows['qwen-models']['ok'])
        self.assertIn('weight hashes', rows['qwen-models']['scope'])
        self.assertTrue(rows['speaker-models']['ok'])
        self.assertIn('loadability', rows['speaker-models']['scope'])
        self.assertIn('necessary', rows['speaker-models']['scope'])

    def speaker_cache(self):
        community = m.SPEECH_CACHE / 'Pyannote-Community-1-CoreML'
        wespeaker = m.SPEECH_CACHE / 'WeSpeaker-ResNet34-LM-CoreML'
        configs = [(community, {'model_type': 'pyannote-community-1-coreml', 'sample_rate': 16000,
            'segmentation': {'model': 'segmentation.mlmodelc', 'input_name': 'waveform',
                             'output_name': 'log_probabilities'},
            'embedding': {'model': 'embedding.mlmodelc', 'waveform_input_name': 'waveform',
                          'weights_input_name': 'weights', 'output_name': 'embedding'},
            'plda': {'dimension': 128, 'weights': 'plda.safetensors'}}),
            (wespeaker, {'model_type': 'wespeaker-resnet34-lm-coreml', 'sample_rate': 16000})]
        for root, config in configs:
            root.mkdir(parents=True, exist_ok=True)
            (root / 'config.json').write_text(json.dumps(config))
        (community / 'plda.safetensors').write_text('synthetic nonempty payload')
        for root, name in [(community, 'segmentation'), (community, 'embedding'), (wespeaker, 'wespeaker')]:
            for filename in ('model.mil', 'coremldata.bin', 'weights/weight.bin'):
                path = root / (name + '.mlmodelc') / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('synthetic nonempty payload')
        self.system.return_value, self.machine.return_value = 'Darwin', 'arm64'
        return community, wespeaker

    def speaker_row(self, model='1.7B', kind='speaker-models'):
        return next(row for row in m.checks(model)[0] if row[0] == kind)

    def test_speaker_empty_bundles_block_local_speakers(self):
        self.speaker_cache()
        shutil.rmtree(m.SPEECH_CACHE)
        for name in ('Pyannote-Community-1-CoreML', 'WeSpeaker-ResNet34-LM-CoreML'):
            (m.SPEECH_CACHE / name).mkdir(parents=True)
        self.cache('Qwen/Qwen3-ASR-1.7B')
        self.cache('Qwen/Qwen3-ForcedAligner-0.6B')
        self.assertFalse(self.speaker_row()[1])
        self.assertFalse(m.report(*m.checks())[0]['local-speakers'])

    def test_optional_embedding_cache_does_not_block_community_diarization(self):
        community, wespeaker = self.speaker_cache()
        for model in m.model_ids('0.6B'):
            self.cache(model)
        self.system.return_value, self.machine.return_value = 'Darwin', 'arm64'
        skill = self.root / 'skill'
        bridge = skill / 'scripts/community1-bridge/build/community1-bridge'
        bridge.parent.mkdir(parents=True)
        bridge.write_bytes(b'synthetic executable marker')
        shutil.rmtree(wespeaker)
        with patch.object(m, 'SKILL', skill):
            routes, rows = m.report(*m.checks())
            self.assertTrue(routes['local-speakers'])
            by_name = {row['check']: row for row in rows}
            self.assertTrue(by_name['speaker-models']['ok'])
            self.assertFalse(by_name['speaker-embeddings']['ok'])
            self.assertIn('optional', by_name['speaker-embeddings']['next'])
            self.speaker_cache()
            shutil.rmtree(community)
            routes, rows = m.report(*m.checks())
            self.assertFalse(routes['local-speakers'])
            self.assertTrue(next(row for row in rows if row['check'] == 'speaker-embeddings')['ok'])
        self.process.assert_not_called()

    def test_speaker_complete_fixture_and_model_selection_are_read_only(self):
        self.speaker_cache()
        original = Path.open
        def guarded_open(path, *args, **kwargs):
            self.assertEqual(path.name, 'config.json')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded_open):
            for model in ('0.6B', '1.7B'):
                self.assertTrue(self.speaker_row(model)[1])
        self.process.assert_not_called()

    def test_speaker_prefetch_actions_match_required_and_optional_rows(self):
        self.system.return_value, self.machine.return_value = 'Darwin', 'arm64'
        items = {row[0]: row for row in m.checks()[0]}
        for name, expected in [
            ('speaker-models', ['speech', 'diarize', '--engine', 'community1']),
            ('speaker-embeddings', ['speech', 'embed-speaker', '--engine', 'coreml', '--json']),
        ]:
            with self.subTest(name=name):
                sample = self.root / name / 'sample.wav'
                sample.parent.mkdir()
                sample.write_bytes(b'synthetic setup sample')
                self.process.reset_mock()
                with patch.object(m, 'sample_wav', return_value=sample):
                    items[name][4]()
                self.process.assert_called_once_with([*expected, str(sample)], check=True)
                self.assertFalse(sample.parent.exists())

    def test_speaker_missing_empty_broken_or_unreadable_payloads(self):
        community, wespeaker = self.speaker_cache()
        paths = [community / 'plda.safetensors'] + [root / (name + '.mlmodelc') / filename
            for root, name in [(community, 'segmentation'), (community, 'embedding'), (wespeaker, 'wespeaker')]
            for filename in ('model.mil', 'coremldata.bin', 'weights/weight.bin')]
        for path in paths:
            for fault in ('missing', 'empty', 'broken-link', 'directory', 'unreadable'):
                with self.subTest(path=path.relative_to(m.SPEECH_CACHE), fault=fault):
                    path.unlink()
                    if fault == 'empty': path.touch()
                    elif fault == 'broken-link': path.symlink_to('missing-target')
                    elif fault == 'directory': path.mkdir()
                    elif fault == 'unreadable': path.write_text('payload')
                    access = m.os.access
                    with patch.object(m.os, 'access', side_effect=lambda p, mode: False if p == path else access(p, mode)):
                        kind = 'speaker-embeddings' if path.is_relative_to(wespeaker) else 'speaker-models'
                        ready = self.speaker_row(kind=kind)[1]
                    if path.is_dir(): path.rmdir()
                    elif path.exists() or path.is_symlink(): path.unlink()
                    path.write_text('payload')
                    self.assertFalse(ready)
        self.assertTrue(self.speaker_row()[1])

    def test_speaker_bad_config_and_manifest_targets(self):
        community, wespeaker = self.speaker_cache()
        for root in (community, wespeaker):
            path = root / 'config.json'
            original = path.read_text()
            config = json.loads(original)
            cases = ['', '{broken', '[]', json.dumps({**config, 'model_type': 'wrong'}),
                     json.dumps({**config, 'sample_rate': 8000}), json.dumps({**config, 'sample_rate': '16000'})]
            if root == community:
                cases += [json.dumps({**config, 'plda': {'dimension': 64, 'weights': 'plda.safetensors'}}),
                          json.dumps({**config, 'embedding': {**config['embedding'], 'model': '../escape.mlmodelc'}}),
                          json.dumps({**config, 'segmentation': {'model': 'segmentation.mlmodelc'}}),
                          json.dumps({**config, 'plda': {'dimension': 128, 'weights': 'missing.safetensors'}})]
            for value in cases:
                with self.subTest(bundle=root.name, value=value[:80]):
                    path.write_text(value)
                    kind = 'speaker-embeddings' if root == wespeaker else 'speaker-models'
                    self.assertFalse(self.speaker_row(kind=kind)[1])
            path.write_text(original)
        self.assertTrue(self.speaker_row()[1])

    def test_download_argv_contains_only_selected_pair(self):
        for model in ('0.6B', '1.7B'):
            with self.subTest(model=model):
                self.process.reset_mock()
                m.download_models(model)
                self.process.assert_called_once()
                args, kwargs = self.process.call_args
                self.assertEqual(args[0][:2], ['/mock/python', '-c'])
                self.assertEqual(args[0][3:], [f'Qwen/Qwen3-ASR-{model}',
                                              'Qwen/Qwen3-ForcedAligner-0.6B'])
                self.assertEqual(kwargs, {'check': True})

    def test_checks_bind_download_action_to_selected_model(self):
        for system, machine in [('Linux', 'x86_64'), ('Darwin', 'arm64')]:
            self.system.return_value, self.machine.return_value = system, machine
            for model in ('0.6B', '1.7B'):
                with self.subTest(system=system, model=model):
                    self.process.reset_mock()
                    row = self.qwen_row(model)
                    self.assertIn(f'ASR-{model}', row[3])
                    self.assertIn('not a measured download size', row[3])
                    row[4]()
                    self.assertEqual(self.process.call_args.args[0][3:],
                                     [f'Qwen/Qwen3-ASR-{model}', 'Qwen/Qwen3-ForcedAligner-0.6B'])

    def test_low_space_never_downloads_either_model(self):
        for model, required in [('0.6B', 6), ('1.7B', 12)]:
            with self.subTest(model=model):
                self.space.return_value.free = (required - 0.1) * 10**9
                with self.assertRaisesRegex(SystemExit, f'reserve {required} GB'):
                    m.download_models(model)
        self.process.assert_not_called()

    def test_space_sufficient_for_small_model_does_not_admit_large_model(self):
        self.space.return_value.free = 6 * 10**9
        with self.assertRaises(SystemExit):
            m.download_models('1.7B')
        self.process.assert_not_called()
        m.download_models()  # The default uses the 0.6B reservation.
        self.process.assert_called_once()

    def test_torch_environment_uses_selected_reservation_before_install(self):
        for model, required in [('0.6B', 8), ('1.7B', 14)]:
            with self.subTest(model=model):
                self.space.return_value.free = (required - 0.1) * 10**9
                with self.assertRaisesRegex(SystemExit, f'reserve {required} GB'):
                    m.build_torch_venv(model)
        self.process.assert_not_called()
        self.space.return_value.free = 8 * 10**9
        action = next(row[4] for row in m.checks('0.6B')[0] if row[0] == 'torch-worker')
        action()
        self.assertEqual(self.process.call_count, 2)
        self.assertEqual(self.process.call_args_list[0].args[0],
                         ['uv', 'venv', '--python', '3.12', str(m.TORCH_VENV)])

    def test_cli_default_and_explicit_model_are_read_only(self):
        self.cache('Qwen/Qwen3-ASR-0.6B')
        self.cache('Qwen/Qwen3-ForcedAligner-0.6B')
        for argv, expected, local in [([], '0.6B', True), (['--model', '1.7B'], '1.7B', False),
                                      (['--model', '0.6B'], '0.6B', True)]:
            with self.subTest(argv=argv), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(m.main([*argv, '--json']), 0)
                report = json.loads(output.getvalue())
                self.assertEqual(report['model'], expected)
                self.assertEqual(report['routes']['local'], local)
        self.process.assert_not_called()

    def test_cli_fix_keeps_model_for_initial_and_followup_checks(self):
        for argv, expected in [([], '0.6B'), (['--model', '1.7B'], '1.7B'), (['--model', '0.6B'], '0.6B')]:
            with self.subTest(argv=argv), patch.object(m, 'checks', wraps=m.checks) as checks, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.process.reset_mock()
                m.main([*argv, '--fix'])
                self.assertEqual([call.args for call in checks.call_args_list], [(expected,), (expected,)])
                self.process.assert_called_once()
                self.assertEqual(self.process.call_args.args[0][3:],
                                 [f'Qwen/Qwen3-ASR-{expected}', 'Qwen/Qwen3-ForcedAligner-0.6B'])

    def test_cli_fix_with_low_space_does_not_download(self):
        self.space.return_value.free = 5 * 10**9
        with contextlib.redirect_stdout(io.StringIO()) as output:
            m.main(['--fix'])
        self.assertIn('reserve 6 GB', output.getvalue())
        self.process.assert_not_called()

    def test_invalid_cli_fails_before_checks(self):
        for argv in [['--model', '2B'], ['--model'], ['--unknown']]:
            with self.subTest(argv=argv), patch.object(m, 'checks') as checks, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                m.main(argv)
            self.assertEqual(error.exception.code, 2)
            checks.assert_not_called()
        self.process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
