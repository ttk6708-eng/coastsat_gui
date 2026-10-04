"""Thin native-app executable launcher; all runtime paths are relocatable."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys


def main():
    base = Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
    python, app = base/'env'/'pythonw.exe',base/'native_app.py'
    if not python.is_file() or not app.is_file():
        ctypes.windll.user32.MessageBoxW(0,'ZIP 전체를 먼저 압축 해제해 주세요. EXE와 env 폴더를 함께 유지해야 합니다.','CoastSat 실행 안내',16)
        return 1
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'; env['PYTHONNOUSERSITE'] = '1'
    env.pop('PYTHONHOME',None); env.pop('PYTHONPATH',None)
    # Prefer plugins shipped with this runtime rather than a system Qt installation.
    env.pop('QT_PLUGIN_PATH',None); env.pop('QT_QPA_PLATFORM_PLUGIN_PATH',None)
    try:
        return subprocess.call([str(python),str(app),*sys.argv[1:]],cwd=base,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(0,str(error),'CoastSat 실행 오류',16)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
