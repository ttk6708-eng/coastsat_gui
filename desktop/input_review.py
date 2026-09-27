"""Read-only input review; sampled statistics and a pre-mask RGB preview."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path

import numpy as np
from osgeo import gdal, osr
from PIL import Image
from desktop.processing import open_raster, aligned_band, MAX_PIXELS, NAMES
from desktop.display import stretch_ranges, preview_rgb


def review_input(scene, folder):
    out = Path(folder); out.mkdir(parents=True, exist_ok=True)
    rows, issues, datasets, versions = [], [], {}, {}
    roles = list(zip(NAMES,scene['bands']))
    roles += [(label,scene[key]) for key,label in [('qa','구름 품질정보'),('probability','구름 확률'),('pan','PAN')] if scene.get(key)]
    if len(scene['bands']) not in (3,5):
        issues.append('지원하지 않는 영상 밴드 수입니다. RGB 3개 또는 5개 밴드를 지정하세요.')
    for role,entry in roles:
        path = str(Path(entry['path']).resolve())
        row = {'role':role,'path':path,'band':entry.get('band',1),'error':None}
        rows.append(row)
        try:
            if path not in datasets:
                stat = Path(path).stat(); versions[path] = (stat.st_size,stat.st_mtime_ns)
                datasets[path] = open_raster(path)
            ds = datasets[path]; number = int(entry.get('band',1))
            if not 1 <= number <= ds.RasterCount:
                raise ValueError(f'{number}번 밴드가 없습니다.')
            band = ds.GetRasterBand(number)
            transform = ds.GetGeoTransform(); srs = osr.SpatialReference(wkt=ds.GetProjection())
            unit = srs.GetAngularUnitsName() if srs.IsGeographic() else srs.GetLinearUnitsName()
            scale = entry.get('scale', band.GetScale() if band.GetScale() is not None else 1.0)
            offset = entry.get('offset', band.GetOffset() if band.GetOffset() is not None else 0.0)
            if not np.isfinite([scale,offset]).all():
                raise ValueError('스케일·오프셋은 유한한 값이어야 합니다.')
            width,height = min(256,ds.RasterXSize),min(256,ds.RasterYSize)
            sample = band.ReadAsArray(buf_xsize=width,buf_ysize=height).astype('float64')
            valid = band.GetMaskBand().ReadAsArray(buf_xsize=width,buf_ysize=height) != 0
            valid &= np.isfinite(sample)
            nodata = band.GetNoDataValue()
            if nodata is not None: valid &= sample != nodata
            values = sample[valid]
            raw_range = [float(values.min()),float(values.max())] if values.size else None
            categorical = role in ('구름 품질정보','구름 확률')
            effective_scale,effective_offset = (1.,0.) if categorical else (float(scale),float(offset))
            corrected = values*effective_scale+effective_offset
            metadata = ds.GetMetadata()
            row.update(width=ds.RasterXSize,height=ds.RasterYSize,description=band.GetDescription(),
                dtype=gdal.GetDataTypeName(band.DataType),crs=srs.GetName() or '이름 없는 좌표계',
                projection=ds.GetProjection(),transform=list(transform),
                pixel_size=[math.hypot(transform[1],transform[4]),math.hypot(transform[2],transform[5])],unit=unit,
                scale=effective_scale,offset=effective_offset,
                calibration_source='품질정보 원값 유지' if categorical else ('사용자 지정' if 'scale' in entry or 'offset' in entry else '파일 메타데이터 / 기본값'),
                nodata=str(nodata) if nodata is not None else '미지정',sample_count=int(sample.size),
                sampled_invalid_percent=float(np.mean(~valid)*100),raw_range=raw_range,
                calibrated_range=[float(corrected.min()),float(corrected.max())] if values.size else None,
                processing_level=metadata.get('PROCESSING_LEVEL') or metadata.get('processing_level') or '미확인',
                processing_baseline=metadata.get('PROCESSING_BASELINE') or '미확인')
            if ds.RasterXSize*ds.RasterYSize > MAX_PIXELS:
                issues.append(f'{role}: 현재 전처리 한도인 1,200만 픽셀을 초과합니다.')
            if not values.size: issues.append(f'{role}: 표본에 유효한 값이 없습니다. 전체 영상의 유효 픽셀이 없다는 뜻은 아닙니다.')
            if band.DataType == gdal.GDT_Byte and role in NAMES:
                issues.append(f'{role}: 8비트 자료입니다. 분석용 원본 밴드인지 화면용으로 변환한 영상인지 확인하세요.')
        except Exception as error:
            row['error'] = str(error); issues.append(f'{role}: {error}')
    base = next((r for r in rows if r['role']=='Blue' and not r['error']),None)
    for row in rows:
        row['alignment'] = '점검 불가'
        if base and not row['error']:
            same = (row['width'],row['height'],row['transform']) == (base['width'],base['height'],base['transform'])
            same = same and bool(osr.SpatialReference(wkt=row['projection']).IsSame(osr.SpatialReference(wkt=base['projection'])))
            row['alignment'] = '파랑 밴드와 동일' if same else '정렬 필요'
    if not scene.get('qa') and not scene.get('probability'):
        issues.append('구름 정보가 없습니다. 현재 기본 처리에서는 구름을 자동 판정하지 않습니다.')
    if any(r.get('processing_level') == '미확인' for r in rows if r['role'] in NAMES and not r['error']):
        issues.append('TOA/지표반사율 등 처리 수준을 메타데이터만으로 확인하지 못했습니다. 값의 크기나 촬영 날짜만으로 보정 여부를 추정하지 않습니다.')
    if scene.get('satellite') == 'S2':
        issues.append('Sentinel-2 오프셋은 일괄 차감하지 않습니다. 이미 보정된 자료인지 확인한 뒤 밴드·보정 설정에서 지정하세요.')
    info = {'name':scene['name'],'created_utc':datetime.now(timezone.utc).isoformat(),'scene':scene,
            'bands':rows,'issues':issues,'preview_path':None,'preview_error':None,
            'capabilities':{'basic_cloud':bool(scene.get('qa') or scene.get('probability')),
                'cloud_probability':bool(scene.get('probability')),
                'nir_assigned':len(scene['bands'])==5,
                'pan_selected':bool(scene.get('pan')),'ai_implemented':True,'ai_applied':False},
            'statistics_note':'각 밴드의 최대 256×256 표본을 최근접 방식으로 읽었습니다. 표본 범위·결측 비율이며 전체 통계가 아닙니다.'}
    # Reuse the actual alignment/calibration implementation, but only build a small
    # RGB display grid. No cloud mask, sharpening or atmospheric correction here.
    try:
        if base is None or any(r['error'] for r in rows[:3]):
            raise ValueError('RGB 입력을 확인해야 미리보기를 만들 수 있습니다.')
        target_source = datasets[base['path']]
        factor = max(1,math.ceil(max(base['width'],base['height'])/1000))
        width,height = math.ceil(base['width']/factor),math.ceil(base['height']/factor)
        target = gdal.GetDriverByName('MEM').Create('',width,height,1,gdal.GDT_Byte)
        gt = base['transform']; sx,sy = base['width']/width,base['height']/height
        target.SetGeoTransform((gt[0],gt[1]*sx,gt[2]*sy,gt[3],gt[4]*sx,gt[5]*sy))
        target.SetProjection(target_source.GetProjection())
        rgb = np.stack([aligned_band(scene['bands'][i],target) for i in [2,1,0]],axis=2)
        if not np.isfinite(rgb).all(axis=2).any():
            raise ValueError('축소 미리보기에서 RGB가 함께 유효한 영역을 찾지 못했습니다. 겹침·결측·밴드 설정을 확인하세요.')
        preview = out/'input-rgb.png'; Image.fromarray(preview_rgb(rgb,stretch_ranges(rgb))).save(preview)
        info['preview_path'] = str(preview.resolve())
        info['preview_note'] = f'입력 RGB 확인용 · {width}×{height} 픽셀 표시. 지정된 보정값·좌표 정렬과 2–98% 명암 조절만 적용. 구름 제거·선명화·대기보정 없음.'
    except Exception as error:
        info['preview_error'] = str(error)
    for path,old in versions.items():
        try:
            stat = Path(path).stat()
            if old != (stat.st_size,stat.st_mtime_ns): raise ValueError()
        except (OSError,ValueError):
            info['preview_path'] = None; info['preview_error'] = '점검 중 입력 파일이 바뀌었습니다. 다시 점검하세요.'
            issues.append(info['preview_error']); break
    info['folder'] = str(out.resolve())
    (out/'input-review.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    return info
