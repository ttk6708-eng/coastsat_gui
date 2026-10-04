"""Build a Qt-only standalone Windows distribution (no Streamlit/WebView)."""
from pathlib import Path
import argparse
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--models',help='Optional verified OmniCloudMask v4 folder for an offline AI edition')
    args = parser.parse_args()
    from download_font import ensure_font
    ensure_font()
    source = Path(__file__).resolve().parent
    runtime,out = Path(args.runtime).resolve(),Path(args.output).resolve()
    if out.exists():
        raise SystemExit('Choose a new output folder to preserve previous distributions.')
    if (runtime/'pyvenv.cfg').exists() or not (runtime/'python.exe').exists():
        raise SystemExit('A standalone Python runtime is required.')
    subprocess.run([str(runtime/'python.exe'),'-c',
        "import importlib.util;from PySide6.QtWidgets import QApplication;assert importlib.util.find_spec('streamlit') is None;assert importlib.util.find_spec('webview') is None"],check=True)
    subprocess.run([str(runtime/'python.exe'),'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed',
        '--name','CoastSatStudio','--distpath',str(source/'dist'), '--workpath',str(source/'build-native'),
        str(source/'native_launch.py')],cwd=source,check=True)
    out.mkdir(parents=True)
    shutil.copy2(source/'dist'/'CoastSatStudio.exe',out)
    shutil.copytree(runtime,out/'env',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(source/'desktop',out/'desktop',ignore=shutil.ignore_patterns('__pycache__','*.pyc','host.py'))
    shutil.copytree(source/'coastsat',out/'coastsat',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (out/'classification/models').mkdir(parents=True)
    shutil.copy2(source/'classification/models/NN_4classes_S2_new.pkl',out/'classification/models/NN_4classes_S2_new.pkl')
    shutil.copytree(source/'assets',out/'assets')
    (out/'tests').mkdir()
    for path in [*(source/'tests').glob('test_native*.py'),source/'tests'/'test_desktop_processing.py']:
        shutil.copy2(path,out/'tests'/path.name)
    if (source/'licenses').is_dir():
        shutil.copytree(source/'licenses',out/'licenses')
    for name in ['native_app.py','native_launch.py','build_native.py','download_font.py','README_NATIVE.md','VALIDATION_NATIVE.md',
                 'THIRD_PARTY_NATIVE.md','LICENSE','requirements-native.lock.txt']:
        shutil.copy2(source/name,out/name)
    if (runtime/'Lib/site-packages/omnicloudmask').is_dir():
        shutil.copy2(source/'requirements-ai.lock.txt',out/'requirements-ai.lock.txt')
    if args.models:
        from desktop.ai_models import verify_models, MODELS
        model_source = Path(args.models).resolve()
        verify_models(model_source)
        destination = out/'models/omnicloudmask-v4'; destination.mkdir(parents=True)
        for name, *_ in MODELS:
            shutil.copy2(model_source/name,destination/name)
    print(out)


if __name__ == '__main__':
    main()
