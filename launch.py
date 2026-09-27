"""Small frozen launcher. Scientific libraries live in the adjacent env folder."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys


def main():
    base = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    python = base / 'env' / 'pythonw.exe'
    host = base / 'desktop' / 'host.py'
    if not python.is_file() or not host.is_file():
        ctypes.windll.user32.MessageBoxW(0, '압축파일 전체를 먼저 풀어 주세요. EXE와 env, desktop 폴더가 같은 위치에 있어야 합니다.', 'CoastSat 실행 안내', 16)
        return 1
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    env['PYTHONNOUSERSITE'] = '1'
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)
    try:
        return subprocess.call([str(python), str(host), *sys.argv[1:]], cwd=str(base), env=env,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(0, str(error), 'CoastSat 실행 오류', 16)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
