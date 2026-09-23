"""Filesystem installation and real Hermes discovery; no live network."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANAGED = ('__init__.py', 'plugin.yaml', 'vibe_provider.py')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class InstallTests(unittest.TestCase):
    def run_installer(self, home, *extra):
        return subprocess.run(
            [sys.executable, str(ROOT / 'install.py'), '--home', str(home), *extra],
            capture_output=True, text=True)

    def test_install_into_existing_home_preserves_configuration_and_secrets(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            home = Path(folder) / 'existing-home'
            home.mkdir()
            protected = {
                'config.yaml': 'model:\n  provider: existing\n',
                'auth.json': '{"secret":"do-not-touch"}\n',
                '.env': 'SECRET=do-not-touch\n',
            }
            for name, content in protected.items():
                (home / name).write_text(content)
            before = {name: digest(home / name) for name in protected}

            result = self.run_installer(home)

            self.assertEqual(result.returncode, 0, result.stderr)
            target = home / 'plugins' / 'model-providers' / 'mistral-vibe'
            self.assertEqual(sorted(path.name for path in target.iterdir()), sorted(MANAGED))
            self.assertEqual(before, {name: digest(home / name) for name in protected})

    def test_existing_managed_install_requires_update(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            home = Path(folder) / 'home'
            home.mkdir()
            self.assertEqual(self.run_installer(home).returncode, 0)

            refused = self.run_installer(home)
            updated = self.run_installer(home, '--update')

            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('--update', refused.stderr)
            self.assertEqual(updated.returncode, 0, updated.stderr)

    def test_update_refuses_unexpected_plugin_files_and_force_replaces_them(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            home = Path(folder) / 'home'
            home.mkdir()
            self.assertEqual(self.run_installer(home).returncode, 0)
            target = home / 'plugins' / 'model-providers' / 'mistral-vibe'
            unexpected = target / 'foreign.txt'
            unexpected.write_text('not owned by this installer')

            refused = self.run_installer(home, '--update')
            forced = self.run_installer(home, '--force')

            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('unexpected', refused.stderr.lower())
            self.assertEqual(forced.returncode, 0, forced.stderr)
            self.assertFalse(unexpected.exists())
            self.assertEqual(sorted(path.name for path in target.iterdir()), sorted(MANAGED))

    def test_install_discovery_runtime_and_picker_status_in_fresh_process(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            home = Path(folder) / 'home'
            home.mkdir()
            result = self.run_installer(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            env = dict(os.environ, HERMES_HOME=str(home),
                       MISTRAL_VIBE_API_KEY='fake-plan-key', MISTRAL_API_KEY='fake-payg')
            code = '''
from providers import get_provider_profile
from hermes_cli.runtime_provider import resolve_runtime_provider
p = get_provider_profile('mistral-vibe')
assert p is not None and p.display_name == 'Mistral Vibe'
r = resolve_runtime_provider(requested='mistral-vibe', target_model='mistral-vibe-cli-latest')
assert r['provider'] == 'mistral-vibe' and r['api_key'] == 'fake-plan-key', r
assert r['base_url'] == 'https://api.mistral.ai/v1'
from hermes_cli.models import list_available_providers, cached_provider_model_ids
row = next(row for row in list_available_providers() if row['id'] == 'mistral-vibe')
assert row['authenticated'], row
import httpx
from unittest.mock import patch
payload = {'data': [
    {'id':'chat-visible', 'capabilities':{'completion_chat':True}},
    {'id':'embed-hidden', 'capabilities':{'completion_chat':False}},
]}
with patch('httpx.HTTPTransport', return_value=httpx.MockTransport(
        lambda req: httpx.Response(200, json=payload))):
    ids = cached_provider_model_ids('mistral-vibe', force_refresh=True)
assert ids == ['mistral-vibe-cli-latest', 'chat-visible'], ids
cache_text = __import__('pathlib').Path(__import__('os').environ['HERMES_HOME']).joinpath(
    'provider_models_cache.json').read_text()
assert 'fake-plan-key' not in cache_text
print('discovery, picker and runtime OK')
'''
            result = subprocess.run([sys.executable, '-c', code], cwd=home, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
