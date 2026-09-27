"""Pinned, verified model weights. Importing this module never loads torch."""
import hashlib
import importlib.util
from pathlib import Path
import urllib.request

REVISION = 'c9a4fb88188709127aa25cfe51ae7fd41b0132f8'
MODELS = [
    ('PM_model_OCM_7.97_R_G_NIR_3_smp_regnety_004.pycls_in1k_PT_state.safetensors',
     'tu-regnety_004', 27094520, '7f6e4202e17ee73efa4aba7abb5c34f4f90a9f7eb42480820714994dff2db660'),
    ('PM_model_OCM_7.97_R_G_NIR_3_smp_edgenext_small.usi_in1k_PT_state.safetensors',
     'tu-edgenext_small', 30711472, 'd5fe67ad00f6fdb73eb8382ad925849e97fb82cedb46225344afff1a734a9c1d'),
]


def runtime_available():
    return all(importlib.util.find_spec(name) is not None for name in ('torch', 'omnicloudmask'))


def model_dir():
    from desktop.jobs import ROOT, state_root
    bundled = ROOT / 'models' / 'omnicloudmask-v4'
    if all((bundled / name).is_file() for name, *_ in MODELS):
        return bundled
    return state_root() / 'models' / 'omnicloudmask-v4'


def verify_models(folder):
    for name, _, size, digest in MODELS:
        path = Path(folder) / name
        if not path.is_file() or path.stat().st_size != size:
            raise ValueError('AI 모델이 준비되지 않았습니다. 먼저 모델 받기를 실행해 주세요.')
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != digest:
            raise ValueError('AI 모델 파일 검증에 실패했습니다. 모델을 다시 받아 주세요.')


def download_models(folder, progress=None):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    total = sum(m[2] for m in MODELS); done = 0
    for name, _, size, digest in MODELS:
        path = folder / name
        if path.is_file() and path.stat().st_size == size:
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() == digest:
                    done += size
                    continue
        url = f'https://huggingface.co/NickWright/OmniCloudMask/resolve/{REVISION}/{name}'
        temp = path.with_suffix('.download')
        received = 0; hasher = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60) as response, temp.open('wb') as stream:
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > size:
                    raise ValueError('모델 파일 크기가 예상과 다릅니다.')
                stream.write(chunk); hasher.update(chunk)
                if progress:
                    progress(f'AI 모델 다운로드 · {(done + received)/1e6:.1f} / {total/1e6:.1f} MB', (done + received)/total)
        if received != size or hasher.hexdigest() != digest:
            raise ValueError('모델 다운로드 검증 실패. 다시 받기를 실행해 주세요.')
        temp.replace(path); done += size
    verify_models(folder)
    return {'folder':str(folder), 'bytes':total, 'revision':REVISION}
