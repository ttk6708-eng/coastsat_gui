"""Georeferenced local preprocessing; never authenticates or loads pickle files."""
from pathlib import Path
from datetime import datetime, timezone
import json
import uuid

import numpy as np
from osgeo import gdal, osr
from PIL import Image
from desktop.display import stretch_ranges, preview_rgb

gdal.UseExceptions()
NAMES = ['Blue', 'Green', 'Red', 'NIR', 'SWIR1']
MAX_PIXELS = 12_000_000


def open_raster(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f'파일을 찾을 수 없습니다: {path}')
    ds = gdal.Open(str(path), gdal.GA_ReadOnly)
    if ds is None or not ds.GetProjection() or ds.GetGeoTransform(can_return_null=True) is None:
        raise ValueError(f'좌표계 또는 위치정보가 없는 영상입니다: {path.name}')
    return ds


def inspect(path):
    ds = open_raster(path)
    return {'path': str(Path(path).resolve()), 'width': ds.RasterXSize,
            'height': ds.RasterYSize, 'bands': ds.RasterCount,
            'projection': ds.GetProjection(), 'transform': list(ds.GetGeoTransform()),
            'descriptions': [ds.GetRasterBand(i).GetDescription() for i in range(1, ds.RasterCount + 1)]}


def probability_zero_policy(scene):
    """Only the embedded CoastSat S2 probability band has this convention."""
    bands, probability = scene.get('bands', []), scene.get('probability', {})
    return bool(scene.get('coastsat') and scene.get('satellite') == 'S2' and len(bands) == 5
        and int(probability.get('band', 0)) == 5
        and Path(probability.get('path', '')).resolve() == Path(bands[0]['path']).resolve())


def band_validity(band, values, mask, allow_zero_nodata=False):
    nodata = band.GetNoDataValue()
    # Ignore only the mask synthesized from NoData=0, never an explicit mask/alpha.
    recover_zero = allow_zero_nodata and nodata == 0 and band.GetMaskFlags() == gdal.GMF_NODATA
    valid = np.isfinite(values) & (True if recover_zero else mask != 0)
    if nodata is not None and not recover_zero:
        valid &= values != nodata
    return valid, bool(recover_zero)


def aligned_band(entry, target, nearest=False, allow_zero_nodata=False):
    """Warp each band and its validity mask onto the exact target affine grid."""
    src = open_raster(entry['path'])
    if src.RasterXSize * src.RasterYSize > MAX_PIXELS:
        raise ValueError('현재 버전은 입력 영상당 1,200만 픽셀까지 지원합니다. 작은 영역의 영상을 사용해 주세요.')
    index = int(entry.get('band', 1))
    if not 1 <= index <= src.RasterCount:
        raise ValueError(f'{Path(entry["path"]).name}: {index}번 밴드가 없습니다.')
    band = src.GetRasterBand(index)
    values = band.ReadAsArray().astype('float32')
    valid, _ = band_validity(band, values, band.GetMaskBand().ReadAsArray(), allow_zero_nodata)
    values[~valid] = np.nan
    source = gdal.GetDriverByName('MEM').Create('', src.RasterXSize, src.RasterYSize, 1, gdal.GDT_Float32)
    source.SetGeoTransform(src.GetGeoTransform())
    source.SetProjection(src.GetProjection())
    source.GetRasterBand(1).SetNoDataValue(float('nan'))
    source.GetRasterBand(1).WriteArray(values)
    dest = gdal.GetDriverByName('MEM').Create('', target.RasterXSize, target.RasterYSize, 1, gdal.GDT_Float32)
    dest.SetGeoTransform(target.GetGeoTransform())
    dest.SetProjection(target.GetProjection())
    dest.GetRasterBand(1).SetNoDataValue(float('nan'))
    dest.GetRasterBand(1).Fill(float('nan'))
    gdal.ReprojectImage(source, dest, source.GetProjection(), dest.GetProjection(),
                        gdal.GRA_NearestNeighbour if nearest else gdal.GRA_Bilinear)
    out = dest.ReadAsArray()
    # Explicit user values take precedence; otherwise honor dataset calibration.
    scale = entry.get('scale', band.GetScale() if band.GetScale() is not None else 1.0)
    offset = entry.get('offset', band.GetOffset() if band.GetOffset() is not None else 0.0)
    if not nearest:
        if not np.isfinite([float(scale), float(offset)]).all():
            raise ValueError('스케일·오프셋은 유한한 숫자여야 합니다.')
        out = out * float(scale) + float(offset)
    return out


def write_tif(path, arrays, target, names, byte=False, nodata=None):
    ds = gdal.GetDriverByName('GTiff').Create(str(path), target.RasterXSize, target.RasterYSize,
        len(arrays), gdal.GDT_Byte if byte else gdal.GDT_Float32,
        options=['COMPRESS=DEFLATE', 'TILED=YES', 'BIGTIFF=IF_SAFER'])
    ds.SetGeoTransform(target.GetGeoTransform())
    ds.SetProjection(target.GetProjection())
    for i, (arr, name) in enumerate(zip(arrays, names), 1):
        band = ds.GetRasterBand(i)
        band.SetDescription(name)
        if nodata is not None:
            band.SetNoDataValue(float(nodata))
        band.WriteArray(arr)
    ds.FlushCache()
    ds = None


def compute_scene(scene, allow_empty=False, progress=None):
    """Shared full-resolution computation for previews and final exports."""
    emit = progress or (lambda *args: None)
    emit('입력 확인', '진행 중', '밴드 구성, 좌표계와 처리 가능한 영상 크기를 확인합니다.')
    entries = scene['bands']
    if len(entries) not in (3, 5):
        raise ValueError('RGB 3개 또는 Blue/Green/Red/NIR/SWIR1 5개 밴드를 지정해 주세요.')
    satellite = scene.get('satellite', 'OTHER')
    pan = scene.get('pan')
    if pan and (satellite not in ('L7', 'L8', 'L9') or len(entries) != 5):
        raise ValueError('선명화는 5개 밴드와 PAN 밴드가 있는 Landsat 7/8/9에서 지원합니다.')
    target = open_raster((pan or entries[0])['path'])
    if target.RasterXSize * target.RasterYSize > MAX_PIXELS:
        raise ValueError('현재 버전은 출력 영상당 1,200만 픽셀까지 지원합니다. 더 작은 영역을 사용해 주세요.')
    emit('입력 확인', '완료', f'{len(entries)}개 밴드 · 기준 격자 {target.RasterXSize} × {target.RasterYSize} 픽셀 · ' + ('PAN 기준' if pan else '파랑 밴드 기준'))
    arrays = []
    for i, entry in enumerate(entries):
        emit('밴드 정렬·값 보정', '진행 중', f'{i+1}/{len(entries)} · {NAMES[i]} · {Path(entry["path"]).name}의 {entry.get("band",1)}번 밴드 → 기준 격자에 정렬')
        arrays.append(aligned_band(entry, target))
    data = np.stack(arrays, axis=2)
    del arrays
    emit('밴드 정렬·값 보정', '완료', '영상은 쌍선형 보간, 스케일·오프셋은 지정값 또는 파일 메타데이터를 적용했습니다. 대기보정은 수행하지 않습니다.')
    emit('구름·결측 판정', '진행 중', '유효하지 않은 값과 제공된 구름 정보를 확인합니다. 품질정보는 최근접 보간으로 정렬합니다.')
    preview_step = max(1, int(np.ceil(max(data.shape[:2]) / 1400)))
    before_rgb = data[::preview_step, ::preview_step, [2, 1, 0]].copy()
    nodata = ~np.all(np.isfinite(data), axis=2)
    if scene.get('coastsat') and len(entries) == 5:
        nodata |= np.all(data[:, :, [1, 3, 4]] == 0, axis=2)
        if satellite == 'S2':
            from coastsat.SDS_preprocess import pad_edges
            nodata = pad_edges(data[:, :, [4]], nodata)
    cloud = np.zeros(nodata.shape, dtype=bool)
    known = np.zeros(nodata.shape, dtype=bool)
    warnings = []
    qa = scene.get('qa')
    probability = scene.get('probability')
    if qa:
        values = aligned_band(qa, target, nearest=True)
        available = np.isfinite(values)
        if np.any(available & ((values < 0) | (values != np.floor(values)))):
            raise ValueError('구름 QA/마스크는 음수가 아닌 정수 데이터여야 합니다.')
        integers = np.nan_to_num(values).astype('uint32')
        kind = qa.get('kind', 'binary')
        if kind == 'landsat_qa_pixel':
            if satellite not in ('L5', 'L7', 'L8', 'L9'):
                raise ValueError('QA_PIXEL은 Landsat 영상을 선택했을 때 사용할 수 있습니다.')
            from coastsat.SDS_preprocess import create_cloud_mask
            cloud |= create_cloud_mask(integers, satellite, bool(scene.get('cloud_mask_issue', False))) & available
            nodata |= available & ((integers & 1) != 0)
        elif kind == 's2_qa60':
            cloud |= ((integers & ((1 << 10) | (1 << 11))) != 0) & available
        elif kind == 's2_scl':
            cloud |= np.isin(integers, [3, 8, 9, 10]) & available
            nodata |= np.isin(integers, [0, 1]) & available
        elif kind == 'binary':
            cloud |= (integers != 0) & available
        else:
            raise ValueError('지원하지 않는 구름 마스크 형식입니다.')
        known |= available
    if probability:
        recover_zero = probability_zero_policy(scene)
        values = aligned_band(probability, target, nearest=True, allow_zero_nodata=recover_zero)
        available = np.isfinite(values) & (values >= 0) & (values <= 100)
        if recover_zero:
            warnings.append('CoastSat S2 내장 구름 확률: NoData=0 충돌 시 영상 밴드가 유효한 영역의 확률 0은 유효값으로 해석합니다. 별도 마스크와 영상 결측은 유지합니다.')
        from coastsat.SDS_preprocess import create_s2cloudless_mask
        cloud |= create_s2cloudless_mask(np.where(available, values, 0), float(scene.get('cloud_threshold', 40))) & available
        known |= available & ~nodata
    if not known.any():
        warnings.append('구름 정보 없음: 구름 제거를 수행하지 않았습니다. 구름 마스크는 255(미확인)입니다.')
    elif np.any(~known & ~nodata) and scene.get('apply_cloud_mask', True):
        warnings.append('일부 픽셀은 구름 정보가 없어 처리 결과에서 제외했습니다.')
    apply_cloud_mask = scene.get('apply_cloud_mask', True)
    invalid = nodata | cloud if apply_cloud_mask else nodata.copy()
    if known.any() and apply_cloud_mask:
        invalid |= ~known
    if known.any() and not apply_cloud_mask:
        warnings.append('구름 제외를 해제했습니다. 구름 픽셀이 처리 결과에 남아 있습니다.')
    cloud_text = f'{np.mean(cloud & ~nodata)*100:.2f}%' if known.any() else '판정 불가 (정보 없음)'
    emit('구름·결측 판정', '완료', f'구름 {cloud_text} · 결측 {np.mean(nodata)*100:.2f}% · 구름 제외 {"켜짐" if apply_cloud_mask else "꺼짐"}' + (f' · 확률 기준 {scene.get("cloud_threshold",40)}%' if probability else ' · 확률 기준 미사용'))
    if pan:
        emit('PAN 선명화', '진행 중', 'PAN 밴드로 세부 윤곽을 보강합니다.')
        from coastsat.SDS_preprocess import pansharpen
        pan_data = aligned_band(pan, target)
        nodata |= ~np.isfinite(pan_data)
        invalid |= nodata
        indexes = [1, 2, 3] if satellite == 'L7' else [0, 1, 2]
        if np.count_nonzero(~invalid) < 10 or np.mean(invalid) > .95:
            raise ValueError('선명화에 필요한 유효 픽셀이 부족합니다.')
        sharpened = pansharpen(data[:, :, indexes], pan_data, invalid)
        if not np.all(np.isfinite(sharpened[~invalid])):
            raise ValueError('선명화 결과가 유효하지 않습니다. 선명화를 해제하고 다시 실행해 주세요.')
        data[:, :, indexes] = sharpened
        emit('PAN 선명화', '완료', '선택 밴드의 선명화를 적용했습니다.')
    else:
        emit('PAN 선명화', '건너뜀', '선명화를 선택하지 않았거나 지원 PAN 자료가 없습니다.')
    data[invalid] = np.nan
    if not np.any(~invalid) and not allow_empty:
        raise ValueError('처리 후 남는 유효 픽셀이 없습니다. 구름·결측 정보와 밴드 설정을 확인해 주세요.')
    emit('유효 픽셀 확인', '완료', f'최종 유효 픽셀 {np.count_nonzero(~invalid):,} / {invalid.size:,} ({np.mean(~invalid)*100:.2f}%)')
    return {'data': data, 'target': target, 'nodata': nodata, 'cloud': cloud,
            'known': known, 'invalid': invalid, 'warnings': warnings,
            'before_rgb': before_rgb, 'preview_step': preview_step}


def process_scene(scene, output_root, progress=None):
    steps = []
    def emit(stage, state, message):
        steps.append({'stage':stage, 'state':state, 'message':message, 'time':datetime.now(timezone.utc).isoformat()})
        if progress:
            progress(stage, state, message)
    computed = compute_scene(scene, progress=emit)
    data, target = computed['data'], computed['target']
    nodata, cloud, known = (computed[key] for key in ('nodata', 'cloud', 'known'))
    invalid, warnings = computed['invalid'], computed['warnings']
    entries, pan = scene['bands'], scene.get('pan')
    name = Path(scene.get('name', 'scene')).stem
    name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in name)[:80] or 'scene'
    folder = Path(output_root).resolve() / f'{name}_{uuid.uuid4().hex[:8]}'
    folder.mkdir(parents=True, exist_ok=False)
    incomplete = folder / 'INCOMPLETE.txt'
    incomplete.write_text('처리가 완료되지 않았습니다. 이 폴더의 결과를 사용하지 마세요.', encoding='utf-8')
    try:
        emit('결과 저장', '진행 중', '좌표정보를 유지한 GeoTIFF와 구름·결측 마스크를 저장합니다.')
        write_tif(folder / 'preprocessed.tif', np.moveaxis(data, 2, 0), target, NAMES[:len(entries)], nodata=np.nan)
        cloud_export = np.where(known, cloud.astype('uint8'), 255).astype('uint8')
        write_tif(folder / 'masks.tif', [invalid.astype('uint8'), cloud_export, nodata.astype('uint8')],
                  target, ['Excluded_0_or_1', 'Cloud_0_clear_1_cloud_255_unknown', 'NoData_0_or_1'], byte=True)
        step = computed['preview_step']
        rgb = data[::step, ::step, [2, 1, 0]]
        ranges = stretch_ranges(computed['before_rgb'])
        preview = preview_rgb(rgb, ranges)
        Image.fromarray(preview).save(folder / 'preview.png')
        report = {'created_utc': datetime.now(timezone.utc).isoformat(), 'scene': scene,
                  'cloud_detection_available': bool(known.any()), 'warnings': warnings,
                  'valid_fraction': float(np.mean(~invalid)), 'width': target.RasterXSize,
                  'height': target.RasterYSize, 'transform': list(target.GetGeoTransform()),
                  'projection_wkt': target.GetProjection(),
                  'resampling': 'continuous: bilinear; categorical: nearest',
                  'radiometry': 'Explicit band scale/offset or GeoTIFF metadata applied; no atmospheric correction',
                  'pansharpened': bool(pan), 'mask_bands': ['excluded', 'cloud (255 unknown)', 'nodata']}
        report['display_ranges'] = ranges
        report['steps'] = steps + [{'stage':'결과 저장','state':'완료','message':str(folder),
                                  'time':datetime.now(timezone.utc).isoformat()}]
        (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        incomplete.unlink()
        emit('결과 저장', '완료', str(folder))
        return {'folder': str(folder), 'warnings': warnings, 'steps':steps,
                'valid_percent':float(np.mean(~invalid)*100)}
    except Exception:
        # Keep a visible incomplete marker; never present partial files as a completed scene.
        (folder / 'INCOMPLETE.txt').write_text('처리가 완료되지 않았습니다. 이 폴더의 결과를 사용하지 마세요.', encoding='utf-8')
        raise


def scan_coastsat(folder, pansharpen=False, threshold=40):
    from coastsat import SDS_tools
    root = Path(folder).resolve()
    scenes = []
    for sat in ['L5', 'L7', 'L8', 'L9', 'S2']:
        for ms in sorted((root / sat / 'ms').glob('*.tif')):
            inputs = {'filepath': str(root.parent), 'sitename': root.name}
            paths = SDS_tools.get_filenames(ms.name, SDS_tools.get_filepath(inputs, sat), sat)
            if any(not Path(p).is_file() for p in paths):
                raise ValueError(f'{ms.name}: 같은 장면의 필수 밴드 파일이 누락되었습니다.')
            scene = {'name': ms.stem, 'satellite': sat, 'coastsat': True,
                     'cloud_threshold': threshold}
            if sat == 'S2':
                if open_raster(ms).RasterCount != 5:
                    raise ValueError('Sentinel-2는 현재 CoastSat의 5밴드 ms 파일 형식만 지원합니다.')
                scene['bands'] = [{'path': str(ms), 'band': b, 'scale': .0001, 'offset': 0} for b in range(1, 5)]
                scene['bands'].append({'path': paths[1], 'band': 1, 'scale': .0001, 'offset': 0})
                scene['probability'] = {'path': str(ms), 'band': 5}
                scene['qa'] = {'path': paths[2], 'band': 1, 'kind': 's2_qa60'}
            else:
                if open_raster(ms).RasterCount != 5:
                    raise ValueError(f'{ms.name}: CoastSat 5밴드 영상이 필요합니다.')
                scene['bands'] = [{'path': str(ms), 'band': b} for b in range(1, 6)]
                scene['qa'] = {'path': paths[-1], 'band': 1, 'kind': 'landsat_qa_pixel'}
                if pansharpen and sat in ('L7', 'L8', 'L9'):
                    scene['pan'] = {'path': paths[1], 'band': 1}
            scenes.append(scene)
    if not scenes:
        raise ValueError('L5/L7/L8/L9/S2 아래 ms 폴더가 있는 CoastSat 사이트 폴더를 선택해 주세요.')
    return scenes
