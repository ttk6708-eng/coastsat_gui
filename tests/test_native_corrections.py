import copy
from pathlib import Path
import tempfile
import unittest
import numpy as np
from osgeo import gdal, osr
from desktop.processing import compute_scene, aligned_band, open_raster
from desktop.correction_status import correction_status
from desktop.input_review import review_input


class CorrectionsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.path=self.root/'sample_ms.tif'
        ds=gdal.GetDriverByName('GTiff').Create(str(self.path),32,32,5,gdal.GDT_UInt16)
        srs=osr.SpatialReference();srs.ImportFromEPSG(32652)
        ds.SetProjection(srs.ExportToWkt());ds.SetGeoTransform((300000,10,0,3900000,0,-10))
        for i in range(1,6):
            a=np.full((32,32),1000 if i<5 else 0,dtype='uint16');a[0,:]=0
            ds.GetRasterBand(i).WriteArray(a);ds.GetRasterBand(i).SetNoDataValue(0)
        ds=None
        self.scene={'name':'sample','satellite':'S2','coastsat':True,
            'bands':[{'path':str(self.path),'band':i} for i in [1,2,3,4,1]],
            'probability':{'path':str(self.path),'band':5}}

    def tearDown(self):
        self.temp.cleanup()

    def test_zero_probability_valid_only_inside_spectral_footprint(self):
        out=compute_scene(self.scene)
        self.assertTrue(out['known'][1:,:].all())
        self.assertFalse(out['invalid'][1:,:].any())
        self.assertTrue(out['nodata'][0,:].all())
        self.assertFalse(out['known'][0,:].any())
        self.assertFalse(out['cloud'].any())

    def test_generic_nodata_and_explicit_mask_not_overridden(self):
        self.scene['coastsat']=False
        out=compute_scene(self.scene)
        self.assertFalse(out['known'].any())
        ds=gdal.Open(str(self.path),gdal.GA_Update)
        ds.GetRasterBand(5).CreateMaskBand(gdal.GMF_PER_DATASET)
        mask=np.full((32,32),255,dtype='uint8');mask[:,0]=0
        ds.GetRasterBand(5).GetMaskBand().WriteArray(mask);ds=None
        values=aligned_band(self.scene['probability'],open_raster(self.path),nearest=True,allow_zero_nodata=True)
        self.assertTrue(np.isnan(values[:,0]).all())

    def test_input_review_explains_zero_conflict_and_unknown_corrections(self):
        report=review_input(self.scene,self.root/'review')
        self.assertEqual(report['bands'][-1]['raw_range'],[0.,0.])
        self.assertTrue(any('0/NoData' in issue for issue in report['issues']))
        self.assertEqual(report['corrections']['rows'][1]['input_status'],'확인 불가')

    def test_l2a_requires_consistent_metadata_not_date(self):
        rows=[{'role':role,'processing_level':'Level-2A','alignment':'파랑 밴드와 동일'} for role in ['Blue','Green','Red','NIR','SWIR1']]
        status=correction_status(self.scene,rows)
        self.assertEqual(status['rows'][1]['input_status'],'메타데이터상 수행됨')
        rows[0]['processing_level']='미확인'
        self.assertEqual(correction_status(self.scene,rows)['rows'][1]['input_status'],'확인 불가')
        rows[0]['processing_level']='L1C'
        status=correction_status(self.scene,rows)
        self.assertEqual(status['rows'][1]['input_status'],'확인 불가')
        self.assertIn('충돌',status['rows'][1]['evidence'])

    def test_passed_quality_is_not_atmospheric_or_ortho_proof(self):
        ms=self.root/'S2/ms';ms.mkdir(parents=True)
        meta=self.root/'S2/meta';meta.mkdir()
        scene=copy.deepcopy(self.scene);scene['bands'][0]['path']=str(ms/'sample_ms.tif')
        (meta/'sample.txt').write_text('filename\tsample_ms.tif\nacc_georef\tPASSED\nimage_quality\tPASSED\n',encoding='utf-8')
        status=correction_status(scene,[])
        self.assertEqual(status['coastsat_metadata']['acc_georef'],'PASSED')
        self.assertEqual(status['rows'][1]['input_status'],'확인 불가')
        self.assertEqual(status['rows'][2]['input_status'],'확인 불가')


if __name__=='__main__':unittest.main()
