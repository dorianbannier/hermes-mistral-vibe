"""Install or update the Mistral Vibe community plugin in a Hermes home."""
import argparse
from pathlib import Path
import shutil
import uuid

MANAGED_FILES = ('__init__.py', 'plugin.yaml', 'vibe_provider.py')


def _remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', required=True, type=Path,
                        help='explicit Hermes home (for example "$HERMES_HOME")')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--update', action='store_true',
                      help='replace an existing install containing only managed files')
    mode.add_argument('--force', action='store_true',
                      help='replace the plugin directory even if it contains unexpected files')
    args = parser.parse_args()

    home = args.home.expanduser().resolve()
    if home.exists() and not home.is_dir():
        parser.error('--home must name a directory')
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = home / 'plugins' / 'model-providers' / 'mistral-vibe'

    if target.exists() or target.is_symlink():
        if not (args.update or args.force):
            parser.error('plugin already exists; use --update after reviewing it, or --force to replace it')
        if not args.force:
            if target.is_symlink() or not target.is_dir():
                parser.error('existing plugin is not a regular directory; use --force to replace it')
            entries = list(target.iterdir())
            unexpected = sorted(entry.name for entry in entries
                                if entry.name not in MANAGED_FILES or
                                not entry.is_file() or entry.is_symlink())
            if unexpected:
                parser.error('existing plugin has unexpected files; refusing update: ' +
                             ', '.join(unexpected))

    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / ('.mistral-vibe.install-' + uuid.uuid4().hex)
    source = Path(__file__).resolve().parent
    try:
        staging.mkdir(mode=0o700)
        for name in MANAGED_FILES:
            shutil.copy2(source / name, staging / name)
        if target.exists() or target.is_symlink():
            _remove(target)
        staging.replace(target)
    finally:
        _remove(staging)

    action = 'Updated' if args.update or args.force else 'Installed'
    print(f'{action} Mistral Vibe in {target}')
    print('No Hermes configuration, credentials, auth.json, or .env files were read or changed.')


if __name__ == '__main__':
    main()
