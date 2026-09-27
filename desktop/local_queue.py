"""Sequential offline jobs with durable, per-scene stage reports."""
from datetime import datetime, timezone
from pathlib import Path
import traceback


def run_local(spec, root, save):
    from desktop.processing import process_scene, scan_coastsat
    from desktop.preview import create_preview
    preview = spec['mode'] == 'preview'
    scenes = [spec['scene']] if preview else spec.get('scenes')
    if scenes is None:
        scenes = scan_coastsat(spec['site'],spec.get('pansharpen',False),spec.get('threshold',40))
    if not scenes:
        raise ValueError('처리할 장면이 없습니다.')
    queue = [{'name':s['name'], 'state':'대기', 'stage':'', 'message':'', 'events':[]} for s in scenes]
    results, failed = [], []
    payload = {}
    report_path = root/'batch-report.json'

    def publish(message, terminal=None):
        complete = sum(row['state'] in ('완료','실패') for row in queue)
        value = {'state':terminal or 'running', 'message':message, 'progress':complete/len(queue),
                 'queue':queue, 'results':results, 'failed':failed, 'batch_report':str(report_path), **payload}
        save(report_path,value)
        save(root/'status.json',value)

    publish(f'{len(queue)}개 장면을 목록 순서대로 처리합니다.')
    for i, scene in enumerate(scenes):
        row = queue[i]; row['state'] = '처리 중'
        def update(stage, state, message):
            event = {'stage':stage, 'state':state, 'message':message, 'time':datetime.now(timezone.utc).isoformat()}
            row['events'].append(event); row['stage'] = stage; row['message'] = message
            publish(f'{i+1}/{len(queue)} · {scene["name"]} · {stage} ({state})')
        try:
            if preview:
                payload['preview'] = create_preview(scene,root/'preview',spec.get('signature'),progress=update)
                payload['preview_context'] = spec.get('preview_context','native')
                row['folder'] = payload['preview']['folder']
                row['valid_percent'] = payload['preview']['valid_percent']
            else:
                result = process_scene(scene,spec['output'],progress=update)
                results.append(result); row['folder'] = result['folder']; row['valid_percent'] = result['valid_percent']
            row['state'] = '완료'
            row['message'] = f'유효 픽셀 {row["valid_percent"]:.2f}% · {row["folder"]}'
        except Exception as error:
            row['state'] = '실패'; row['message'] = str(error)
            row['events'].append({'stage':row['stage'] or '입력 확인', 'state':'실패', 'message':str(error), 'time':datetime.now(timezone.utc).isoformat()})
            failed.append({'name':scene['name'], 'error':str(error)})
            traceback.print_exc()
        publish(f'{i+1}/{len(queue)}개 장면 처리 종료')
    successful = any(row['state'] == '완료' for row in queue)
    publish(f'완료 {sum(r["state"] == "완료" for r in queue)}개 · 실패 {len(failed)}개', 'done' if successful else 'error')
    return 0 if successful else 1
