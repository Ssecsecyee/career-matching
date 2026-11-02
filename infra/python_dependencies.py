"""Build Linux x86_64 validation dependencies for the Python 3.11 Lambda ZIP."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def vendor_validation(folder):
    target = folder / 'lambda-validation-dependencies'
    target.mkdir(exist_ok=False)
    result = subprocess.run([sys.executable, '-m', 'pip', 'install',
        '-r', str(ROOT / 'app/backend/requirements.validation.txt'), '--target', str(target),
        '--platform', 'manylinux2014_x86_64', '--implementation', 'cp', '--python-version', '3.11',
        '--only-binary=:all:', '--no-compile', '--disable-pip-version-check'],
        capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError('Lambda validation dependency build failed; worker was not changed')
    if not list((target / 'pydantic_core').glob('*x86_64-linux-gnu.so')):
        raise RuntimeError('Linux x86_64 validation wheel missing')
    return target


def add_validation(archive, folder):
    for path in sorted(folder.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            archive.write(path, path.relative_to(folder).as_posix())
