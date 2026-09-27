from pathlib import Path
import json
import os
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def state_root():
    root = Path(os.environ.get('COASTSAT_STATE_DIR', str(Path.home() / 'Documents' / 'CoastSatDesktop')))
    root.mkdir(parents=True, exist_ok=True)
    return root


def start(spec):
    folder = state_root() / 'jobs' / uuid.uuid4().hex
    folder.mkdir(parents=True)
    (folder / 'job.json').write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    env['MPLBACKEND'] = 'Agg'
    with (folder / 'job.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-u', str(ROOT / 'desktop' / 'worker.py'), str(folder / 'job.json')],
            stdout=log, stderr=log, cwd=str(ROOT), env=env,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return {'folder': str(folder), 'process': process, 'mode': spec['mode'], 'project': spec.get('project')}


def status(job):
    path = Path(job['folder']) / 'status.json'
    value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'state': 'running', 'message': '시작 중', 'progress': 0}
    if job['process'].poll() is not None and value['state'] == 'running':
        value.update(state='error', message='작업이 중단되었습니다. 로그를 확인해 주세요.')
    return value
