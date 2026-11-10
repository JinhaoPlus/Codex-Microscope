"""Export an explicit source allowlist, without Git history or local data."""
import argparse
from datetime import datetime
from pathlib import Path
import shutil
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'scripts/public-files.txt'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='new source directory (must not exist)')
    args = parser.parse_args()
    output = args.output or ROOT / '.local/releases' / ('codex-microscope-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    output = output.absolute()
    archive = output.with_name(output.name + '.zip')
    if output.exists() or archive.exists():
        parser.error('output directory or ZIP already exists; choose a new path')

    files = []
    seen = set()
    for line in MANIFEST.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        relative = Path(line)
        if relative.is_absolute() or '..' in relative.parts or line in seen:
            parser.error('invalid or duplicate manifest entry: ' + line)
        source = ROOT / relative
        if not source.is_file() or any(p.is_symlink() for p in (source, *source.parents)):
            parser.error('missing file or symbolic link: ' + line)
        if any(part in ('.git', '.local', '__pycache__', 'node_modules') for part in relative.parts):
            parser.error('private/generated directory in manifest: ' + line)
        seen.add(line)
        files.append((source, relative))

    output.mkdir(parents=True)
    for source, relative in files:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for _, relative in files:
            bundle.write(output / relative, arcname=Path(output.name) / relative)
    print(f'Exported {len(files)} files without Git history.\nSource: {output}\nZIP: {archive}')


if __name__ == '__main__':
    main()
