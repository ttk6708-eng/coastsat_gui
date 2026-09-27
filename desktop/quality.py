"""Full-grid quality statistics; reference footprints never change export pixels."""
from pathlib import Path
import numpy as np
from osgeo import gdal,ogr,osr
from desktop.site_review import raster_header,polygon


def reference_region(scene,target):
    path=scene.get('quality_reference')
    if not path:return None
    if target.RasterXSize*target.RasterYSize>12_000_000:
        raise ValueError('공통 영역 비교는 처리 격자 1,200만 픽셀까지 지원합니다.')
    source=Path(scene['bands'][0]['path']).resolve(); ref=Path(path).resolve()
    if scene.get('coastsat') and source.parent.parent.parent!=ref.parent.parent.parent:
        raise ValueError('공통 영역 기준은 같은 지역의 ms 영상에서 선택하세요.')
    header=raster_header(ref)
    srs=osr.SpatialReference(wkt=target.GetProjection())
    other=osr.SpatialReference(wkt=header['wkt'])
    if not srs.IsProjected() or not srs.IsSame(other):
        raise ValueError('공통 영역 비교는 같은 투영 좌표계에서 지원합니다.')
    ds=gdal.GetDriverByName('MEM').Create('',target.RasterXSize,target.RasterYSize,1,gdal.GDT_Byte)
    ds.SetGeoTransform(target.GetGeoTransform());ds.SetProjection(target.GetProjection())
    vector=ogr.GetDriverByName('Memory').CreateDataSource('')
    layer=vector.CreateLayer('footprint',srs,ogr.wkbPolygon)
    feature=ogr.Feature(layer.GetLayerDefn());feature.SetGeometry(polygon(header['points']));layer.CreateFeature(feature)
    if gdal.RasterizeLayer(ds,[1],layer,burn_values=[1])!=0:raise ValueError('공통 영역 계산 실패')
    return ds.ReadAsArray().astype(bool)


def statistics(computed,region=None):
    nodata,cloud,known,invalid=(computed[k] for k in ('nodata','cloud','known','invalid'))
    scope=np.ones(nodata.shape,dtype=bool) if region is None else region
    count=int(scope.sum())
    # Classification partitions and actual exclusions are intentionally separate.
    masks={'nodata':nodata,'cloud':cloud & known & ~nodata,'unknown':~known & ~nodata,
           'clear':known & ~cloud & ~nodata,'valid':~invalid,'excluded':invalid,
           'excluded_cloud':invalid & cloud & known & ~nodata,
           'excluded_unknown':invalid & ~known & ~nodata}
    counts={k:int(np.count_nonzero(v & scope)) for k,v in masks.items()}
    return {'pixels':count,'counts':counts,'percent':{k:v/count*100 if count else None for k,v in counts.items()}}


def quality_report(scene,computed):
    region=reference_region(scene,computed['target'])
    return {'whole':statistics(computed),'common':statistics(computed,region) if region is not None else None,
            'reference':scene.get('quality_reference'),
            'note':'공통 영역은 현재 처리 격자의 픽셀 중심이 기준 영상 외곽 안에 있는 영역입니다. 기준 영상의 구름·결측은 반영하지 않습니다. 영역 선택은 저장 영상의 범위를 바꾸지 않습니다.'},region
