import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from osgeo import gdal, osr
from desktop.ai_preview import compare_ai
from desktop.ai_models import verify_models


class AIComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.path = self.root/'scene.tif'
        ds = gdal.GetDriverByName('GTiff').Create(str(self.path),128,128,6,gdal.GDT_Float32)
        srs = osr.SpatialReference(); srs.ImportFromEPSG(32652)
        ds.SetProjection(srs.ExportToWkt()); ds.SetGeoTransform((300000,10,0,3900000,0,-10))
        for i in range(1,7):
            values = np.full((128,128), i/10,dtype='float32')
            if i == 6:
                values[:] = 0; values[:,64:] = 1
            values[0,:] = -9999
            ds.GetRasterBand(i).WriteArray(values); ds.GetRasterBand(i).SetNoDataValue(-9999)
        ds = None
        self.scene = {'name':'합성 AI 시험', 'satellite':'S2', 'apply_cloud_mask':True,
            'bands':[{'path':str(self.path),'band':i} for i in range(1,6)],
            'qa':{'path':str(self.path),'band':6,'kind':'binary'}}

    def tearDown(self):
        self.temp.cleanup()

    def predictor(self, inputs, folder):
        self.assertEqual(inputs.shape,(3,128,128))
        self.assertAlmostEqual(float(inputs[0,10,100]),.3,places=5)
        self.assertAlmostEqual(float(inputs[1,10,100]),.2,places=5)
        self.assertAlmostEqual(float(inputs[2,10,100]),.4,places=5)
        self.assertTrue(np.all(inputs[:,0,:] == 0))
        labels=np.zeros((1,128,128),dtype='uint8')
        labels[:,:,32:64]=1; labels[:,:,64:96]=2; labels[:,:,96:]=3
        return labels

    def test_unmasked_input_mapping_nodata_and_disagreement(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest(); original=copy.deepcopy(self.scene)
        report=compare_ai(self.scene,self.root/'out',self.root,predictor=self.predictor)
        ds=gdal.Open(str(self.root/'out/ai-comparison.tif')); masks=ds.ReadAsArray()
        self.assertTrue(np.all(masks[:,0,:]==255))
        self.assertTrue(np.all(masks[1,1:,32:64]==1))
        self.assertAlmostEqual(report['disagreement_percent'],25)
        self.assertEqual(report['percentages'],{str(i):25.0 for i in range(4)})
        self.assertEqual(ds.GetGeoTransform(),(300000,10,0,3900000,0,-10)); ds=None
        self.assertEqual(self.scene,original)
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertFalse((self.root/'out/preprocessed.tif').exists())

    def test_no_existing_qa_is_not_claimed_as_agreement(self):
        self.scene.pop('qa')
        report=compare_ai(self.scene,self.root/'out',self.root,predictor=self.predictor)
        self.assertIsNone(report['disagreement_percent']); self.assertEqual(report['comparable_pixels'],0)

    def test_rgb_fallback_and_invalid_output(self):
        self.scene['bands']=self.scene['bands'][:3]
        def rgb(inputs, folder):
            self.assertTrue(np.all(inputs[2]==0))
            return np.zeros((1,128,128),dtype='uint8')
        report=compare_ai(self.scene,self.root/'out',self.root,predictor=rgb)
        self.assertFalse(report['nir_available']); self.assertTrue(any('NIR 없음' in w for w in report['warnings']))
        with self.assertRaisesRegex(ValueError,'형식'):
            compare_ai(self.scene,self.root/'bad',self.root,predictor=lambda a,b:np.full((128,128),9))

    def test_missing_or_corrupt_models_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'준비'):
            verify_models(self.root)
        p=self.root/'model'; p.write_bytes(b'broken')
        with patch('desktop.ai_models.MODELS',[('model','unused',6,'0'*64)]):
            with self.assertRaisesRegex(ValueError,'검증'):
                verify_models(self.root)

    def test_source_changed_during_inference_rejected(self):
        def changed(inputs, folder):
            labels=self.predictor(inputs,folder)
            st=self.path.stat(); os.utime(self.path,ns=(st.st_atime_ns,st.st_mtime_ns+1000000))
            return labels
        with self.assertRaisesRegex(ValueError,'바뀌'):
            compare_ai(self.scene,self.root/'out',self.root,predictor=changed)

    def test_dialog_overlay_does_not_modify_report(self):
        from PySide6.QtWidgets import QApplication
        from desktop.native_ai import AIComparisonDialog
        app=QApplication.instance() or QApplication([])
        report=compare_ai(self.scene,self.root/'out',self.root,predictor=self.predictor)
        original=json.dumps(report,sort_keys=True)
        dialog=AIComparisonDialog(report); dialog.show(); app.processEvents()
        dialog.opacity.setValue(25); self.assertEqual(dialog.after.mask.opacity(),.25)
        dialog.overlay.setChecked(False); self.assertEqual(dialog.before.mask.opacity(),0)
        self.assertEqual(original,json.dumps(report,sort_keys=True)); dialog.close()


if __name__ == '__main__':
    unittest.main()
