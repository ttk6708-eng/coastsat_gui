"""Disposable previews use the same full-resolution pipeline as final exports."""
from pathlib import Path
import hashlib
import json

import numpy as np
from PIL import Image

from desktop.processing import compute_scene
from desktop.display import stretch_ranges, preview_rgb


def scene_signature(scene):
    files = []
    for entry in [*scene['bands'], scene.get('qa'), scene.get('probability'), scene.get('pan')]:
        if entry:
            path = Path(entry['path']).expanduser().resolve()
            stat = path.stat()
            files.append([str(path), stat.st_size, stat.st_mtime_ns])
    if scene.get('quality_reference'):
        path=Path(scene['quality_reference']).resolve();stat=path.stat()
        files.append([str(path),stat.st_size,stat.st_mtime_ns])
    return hashlib.sha256(json.dumps({'scene':scene, 'files':files}, sort_keys=True).encode()).hexdigest()


def create_preview(scene, folder, expected_signature=None, progress=None):
    signature = scene_signature(scene)
    if expected_signature and signature != expected_signature:
        raise ValueError('미리보기 요청 이후 입력 파일이 바뀌었습니다. 다시 갱신해 주세요.')
    computed = compute_scene(scene, allow_empty=True, progress=progress)
    if signature != scene_signature(scene):
        raise ValueError('처리 중 입력 파일이 바뀌었습니다. 다시 갱신해 주세요.')
    step = computed['preview_step']
    before = computed['before_rgb']
    after = computed['data'][::step, ::step, [2, 1, 0]]
    ranges = stretch_ranges(before)
    cloud, known, nodata = (computed[key][::step, ::step] for key in ('cloud', 'known', 'nodata'))
    mask = np.zeros((*cloud.shape, 4), dtype='uint8')
    mask[~known & ~nodata] = [157, 92, 226, 255]
    mask[cloud & ~nodata] = [255, 102, 51, 255]
    mask[nodata] = [130, 144, 159, 255]
    out = Path(folder)
    if progress:
        progress('미리보기 생성', '진행 중', '원본·처리 결과와 구름·결측 겹침 영상을 만듭니다.')
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(preview_rgb(before, ranges)).save(out / 'before.png')
    Image.fromarray(preview_rgb(after, ranges)).save(out / 'after.png')
    Image.fromarray(mask).save(out / 'mask.png')
    from desktop.quality import quality_report
    quality,region=quality_report(scene,computed)
    empty=np.zeros_like(mask)
    Image.fromarray(empty).save(out/'quality-empty.png')
    missing=empty.copy();missing[nodata]=[130,144,159,255]
    excluded=mask.copy();excluded[~computed['invalid'][::step,::step]]=0
    if region is not None:
        outside=~region[::step,::step]
        missing[outside]=[50,110,180,120];excluded[outside]=[50,110,180,120]
    Image.fromarray(missing).save(out/'quality-nodata.png')
    Image.fromarray(excluded).save(out/'quality-excluded.png')
    full_known = computed['known'] & ~computed['nodata']
    info = {'folder':str(out.resolve()), 'signature':signature, 'scene':scene,
            'quality':quality,
            'warnings':computed['warnings'], 'valid_percent':float(np.mean(~computed['invalid']) * 100),
            'cloud_percent':float(np.mean(computed['cloud'] & ~computed['nodata']) * 100) if full_known.any() else None,
            'unknown_percent':float(np.mean(~computed['known'] & ~computed['nodata']) * 100),
            'nodata_percent':float(np.mean(computed['nodata']) * 100),
            'can_export':bool((~computed['invalid']).any()),
            'display_ranges':ranges, 'display_step':step,
            'width':computed['target'].RasterXSize, 'height':computed['target'].RasterYSize}
    if signature != scene_signature(scene):
        raise ValueError('품질 통계 생성 중 입력 또는 기준 파일이 바뀌었습니다. 다시 갱신해 주세요.')
    (out / 'preview.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    if progress:
        progress('미리보기 생성', '완료', f'{info["width"]} × {info["height"]} 픽셀 처리 완료 · 표시는 {step}배 간격으로 축소')
    return info


def blended_preview(folder, which, opacity):
    """Opacity is display-only; changing it never re-runs scientific processing."""
    root = Path(folder)
    with Image.open(root / f'{which}.png') as source, Image.open(root / 'mask.png') as overlay:
        base = source.convert('RGBA')
        mask = overlay.convert('RGBA')
        mask.putalpha(mask.getchannel('A').point(lambda alpha: int(alpha * opacity)))
        return Image.alpha_composite(base, mask).convert('RGB')
