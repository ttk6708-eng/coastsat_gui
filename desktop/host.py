"""Owns the app window and local server. Closing the window stops child jobs."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser


def windows_job():
    # Windows closes every descendant when the owner exits, including cancelled UI sessions.
    class BASIC(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ['ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount']]
    class EXTENDED(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', BASIC), ('IoInfo', IO), ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel.CreateJobObjectW(None, None)
    limits = EXTENDED()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def main():
    base = Path(__file__).resolve().parents[1]
    os.chdir(base)
    state = Path(os.environ.get('COASTSAT_STATE_DIR', str(Path.home() / 'Documents' / 'CoastSatDesktop')))
    state.mkdir(parents=True, exist_ok=True)
    os.environ['MPLBACKEND'] = 'Agg'
    os.environ['MPLCONFIGDIR'] = str(state / 'matplotlib')
    os.environ['PYTHONUTF8'] = '1'
    log = (state / 'launcher.log').open('a', encoding='utf-8')
    sys.stdout = sys.stderr = log
    server = None
    try:
        job_handle = windows_job()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        server = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(base / 'desktop_app.py'),
            '--server.address=127.0.0.1', f'--server.port={port}', '--server.headless=true',
            '--browser.gatherUsageStats=false', '--server.fileWatcherType=none', '--server.maxUploadSize=1024'],
            cwd=base, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError('화면 서버를 실행하지 못했습니다.')
            try:
                with urllib.request.urlopen(url + '/_stcore/health', timeout=2) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(.4)
        else:
            raise RuntimeError('화면 시작 시간이 초과되었습니다.')
        if '--smoke-test' in sys.argv:
            (state / 'smoke-test.json').write_text(json.dumps({'healthy':True,'port':port,'python':sys.executable}), encoding='utf-8')
            return 0
        import webview
        window = webview.create_window('CoastSat · 위성영상 전처리', url, width=1240, height=900, min_size=(900,650))
        try:
            webview.start(gui='edgechromium', private_mode=True)
        except Exception:
            import traceback
            traceback.print_exc()
            # Fallback remains fully local and does not require installing a Python runtime.
            webbrowser.open(url)
            ctypes.windll.user32.MessageBoxW(0, '앱 창을 열 수 없어 기본 브라우저로 열었습니다.\n사용을 마친 후 이 창의 확인 버튼을 누르면 종료됩니다.', 'CoastSat 실행 중', 64)
        return 0
    except Exception as error:
        import traceback
        traceback.print_exc()
        ctypes.windll.user32.MessageBoxW(0, f'{error}\n\n실행 로그: {state / "launcher.log"}', 'CoastSat 실행 오류', 16)
        return 1
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        log.flush()


if __name__ == '__main__':
    raise SystemExit(main())
