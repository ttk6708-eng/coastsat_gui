"""Isolated, cancellable jobs. Local processing never imports Earth Engine."""
import json
import sys
import traceback
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def save(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    # Windows can briefly deny replacement while the UI reads the status file.
    for attempt in range(10):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.02 * (attempt + 1))


def run(spec_path):
    root = Path(spec_path).parent
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    status = root / 'status.json'
    save(status, {'state': 'running', 'message': '작업 준비 중', 'progress': 0})
    try:
        mode = spec['mode']
        if mode in ('ai_download', 'ai_preview'):
            from desktop.ai_models import model_dir, download_models
            def ai_progress(message, fraction):
                save(status, {'state':'running','message':message,'progress':fraction})
            if mode == 'ai_download':
                result = {'ai_models':download_models(model_dir(), ai_progress)}
            else:
                from desktop.ai_preview import compare_ai
                result = {'ai_comparison':compare_ai(spec['scene'], root/'ai-comparison', model_dir(), ai_progress)}
        elif mode == 'inspect':
            from desktop.input_review import review_input
            save(status, {'state':'running','message':'입력 밴드·좌표·보정값 점검 및 구름 제거 전 RGB 생성 중','progress':0})
            result = {'input_review':review_input(spec['scene'],root/'input-review')}
        elif mode in ('preview', 'process'):
            from desktop.local_queue import run_local
            return run_local(spec, root, save)
        elif mode in ('authenticate', 'download', 'check'):
            import ee
            ee.data.setDeadline(120000)
            if mode == 'authenticate':
                save(status, {'state': 'running', 'message': '기본 브라우저에서 Google 로그인·권한 허용을 완료해 주세요.', 'progress': 0})
                ee.Authenticate(auth_mode='localhost:0', force=True)
            save(status, {'state': 'running', 'message': 'GEE 프로젝트 연결 확인 중', 'progress': 0})
            ee.Initialize(project=spec['project'])
            ee.Number(1).getInfo()
            if mode == 'download':
                from coastsat import SDS_download
                save(status, {'state': 'running', 'message': '위성영상 수집 중 · 상세 로그에서 진행 상황 확인', 'progress': 0})
                site = Path(spec['inputs']['filepath']) / spec['inputs']['sitename']
                site.mkdir(parents=True, exist_ok=True)
                save(site / 'collection-request.json', {'project':spec['project'], 'inputs':spec['inputs'],
                    'region':spec.get('region'), 'footprint':'다운로드 파일은 선택 영역을 감싸는 사각형입니다.'})
                SDS_download.retrieve_images(spec['inputs'])
                result = {'site': str(Path(spec['inputs']['filepath']) / spec['inputs']['sitename'])}
            else:
                result = {'connected': True}
        else:
            raise ValueError('지원하지 않는 작업입니다.')
        save(status, {'state': 'done', 'message': '완료', 'progress': 1, **result})
        return 0
    except Exception as error:
        traceback.print_exc()
        save(status, {'state': 'error', 'message': str(error)})
        return 1


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1]))
