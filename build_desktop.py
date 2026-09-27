"""Package a complete relocatable Python runtime beside a tiny PyInstaller EXE."""
from pathlib import Path
import argparse
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    runtime = Path(args.runtime).resolve()
    out = Path(args.output).resolve()
    if out.exists():
        raise SystemExit('Output already exists; choose a new folder to preserve previous builds.')
    if (runtime / 'pyvenv.cfg').exists() or not (runtime / 'python.exe').is_file():
        raise SystemExit('A standalone runtime is required, not a virtualenv.')
    subprocess.run([str(runtime/'python.exe'), '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
                    '--windowed', '--name', 'CoastSatPreprocess', '--distpath', str(source/'dist'),
                    '--workpath', str(source/'build'), str(source/'launch.py')], cwd=source, check=True)
    out.mkdir(parents=True)
    shutil.copy2(source/'dist'/'CoastSatPreprocess.exe', out)
    shutil.copytree(runtime, out/'env', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ['desktop', 'coastsat', 'tests']:
        shutil.copytree(source/name, out/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ['desktop_app.py','launch.py','build_desktop.py','README_DESKTOP.md','LICENSE','THIRD_PARTY_NOTICES.md','requirements-desktop.lock.txt','environment-desktop.yml','VALIDATION_DESKTOP.md']:
        if (source/name).exists():
            shutil.copy2(source/name,out/name)
    print(out)


if __name__ == '__main__':
    main()
