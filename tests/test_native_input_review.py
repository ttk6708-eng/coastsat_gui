import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from osgeo import gdal,osr
from PIL import Image
from PySide6.QtWidgets import QApplication
from desktop.input_review import review_input
from desktop.native_input_review import InputReviewDialog


class InputReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.path = self.raster('입력.tif')
        self.scene = {'name':'입력 점검 시험','satellite':'S2','bands':[{'path':str(self.path),'band':b} for b in (1,2,3)]}

    def tearDown(self): self.temp.cleanup()

    def raster(self,name,epsg=32652,pixel=10,x=300000):
        path = self.root/name; srs = osr.SpatialReference(); srs.ImportFromEPSG(epsg)
        ds = gdal.GetDriverByName('GTiff').Create(str(path),16,16,3,gdal.GDT_Float32)
        ds.SetProjection(srs.ExportToWkt()); ds.SetGeoTransform((x,pixel,0,3900000 if epsg==32652 else 35,0,-pixel))
        for b in (1,2,3):
            values = np.arange(256,dtype='float32').reshape(16,16)+b; values[0,0]=-9999
            band = ds.GetRasterBand(b); band.WriteArray(values); band.SetNoDataValue(-9999)
            band.SetScale(.01); band.SetOffset(-.1)
        ds = None
        return path

    def test_metadata_sampling_and_read_only_rgb(self):
        original = hashlib.sha256(self.path.read_bytes()).hexdigest()
        result = review_input(self.scene,self.root/'review')
        self.assertIsNotNone(result['preview_path'],result['preview_error'])
        band = result['bands'][0]
        self.assertEqual(band['scale'],.01); self.assertEqual(band['offset'],-.1)
        self.assertAlmostEqual(band['sampled_invalid_percent'],100/256)
        self.assertEqual(band['raw_range'],[2.,256.])
        np.testing.assert_allclose(band['calibrated_range'],[-.08,2.46])
        self.assertEqual(band['processing_level'],'미확인')
        self.assertTrue(result['capabilities']['ai_implemented'])
        self.assertFalse(result['capabilities']['ai_applied'])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),original)
        self.assertTrue((self.root/'review/input-review.json').exists())

    def test_missing_band_retains_report_and_disables_rgb(self):
        self.scene['bands'][2]['band']=99
        result = review_input(self.scene,self.root/'review')
        self.assertIn('99번',result['bands'][2]['error'])
        self.assertIsNone(result['preview_path']); self.assertIsNotNone(result['preview_error'])
        self.assertEqual(result['bands'][0]['alignment'],'파랑 밴드와 동일')

    def test_distinct_grid_is_not_reported_as_matching(self):
        self.scene['bands'][1]['path']=str(self.raster('다른 격자.tif',pixel=20))
        result=review_input(self.scene,self.root/'review')
        self.assertEqual(result['bands'][1]['alignment'],'정렬 필요')
        self.assertIsNotNone(result['preview_path'],result['preview_error'])

    def test_degrees_not_meters_and_cloud_settings_do_not_mask_rgb(self):
        geographic=self.raster('경위도.tif',epsg=4326,pixel=.0001,x=129)
        self.scene['bands']=[{'path':str(geographic),'band':b} for b in (1,2,3)]
        first=review_input(self.scene,self.root/'a')
        self.assertIn('degree',first['bands'][0]['unit'].lower())
        self.scene['qa']={'path':str(geographic),'band':1,'kind':'binary'}
        self.scene['apply_cloud_mask']=True
        second=review_input(self.scene,self.root/'b')
        self.assertEqual(Path(first['preview_path']).read_bytes(),Path(second['preview_path']).read_bytes())
        self.assertEqual(second['bands'][-1]['scale'],1)
        self.assertEqual(second['bands'][-1]['offset'],0)

    def test_inspection_dialog_labels_sample_statistics(self):
        result=review_input(self.scene,self.root/'review')
        dialog=InputReviewDialog(result); dialog.show(); self.app.processEvents()
        self.assertEqual(dialog.table.rowCount(),3)
        self.assertIn('표본',dialog.band_details.toPlainText())
        self.assertIn('미확인',dialog.band_details.toPlainText())
        self.assertIn('다음 단계',dialog.findings.toPlainText())
        dialog.close()


if __name__=='__main__': unittest.main()
