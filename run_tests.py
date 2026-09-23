"""Run offline tests using installed Hermes, never the active home or credentials."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
source = os.environ.get('HERMES_SOURCE')
if not source:
    spec = importlib.util.find_spec('providers')
    if spec is None:
        raise SystemExit('Use the Hermes Python interpreter or set HERMES_SOURCE to its source tree')
    source = str(Path(spec.origin).resolve().parents[1])
with tempfile.TemporaryDirectory(prefix='.offline-', dir=ROOT) as folder:
    home = Path(folder)/'user'
    home.mkdir()
    env = {'PATH':os.environ.get('PATH',''), 'HOME':str(home), 'HERMES_HOME':str(home/'hermes'),
        'TMPDIR':folder, 'PYTHONPATH':os.pathsep.join([source, str(ROOT)]),
        'PYTHONDONTWRITEBYTECODE':'1', 'HERMES_NO_UPDATE_CHECK':'1'}
    code = '''
import socket, unittest, sys
from unittest.mock import patch
with patch.object(socket.socket, 'connect', side_effect=AssertionError('Live network forbidden in offline tests')):
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests'))
sys.exit(not result.wasSuccessful())
'''
    print('OFFLINE: synthetic HTTP only; isolated HOME/HERMES_HOME; installed Hermes contract tests', flush=True)
    raise SystemExit(subprocess.call([sys.executable, '-c', code], cwd=ROOT, env=env))
