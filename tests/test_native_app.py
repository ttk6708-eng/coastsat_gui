import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

import numpy as np
from osgeo import gdal, osr
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from desktop.native_style import configure_application
from desktop.native_window import MainWindow
from desktop.native_dialogs import BandDialog, DownloadDialog


class NativeAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        configure_application(cls.application)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root/'시험 영상.tif'
        y,x = np.mgrid[:64,:96]
        srs = osr.SpatialReference(); srs.ImportFromEPSG(32652)
        ds = gdal.GetDriverByName('GTiff').Create(str(self.image),96,64,4,gdal.GDT_Float32)
        ds.SetProjection(srs.ExportToWkt()); ds.SetGeoTransform((300000,10,0,3900000,0,-10))
        for i,arr in enumerate([x+y+10, x+2*y+20, 2*x+y+30,np.where(x<32,20,np.where(x<64,60,90))],1):
            ds.GetRasterBand(i).WriteArray(arr)
        ds = None
        self.scene = {'name':'합성 시험 영상','satellite':'S2','bands':[{'path':str(self.image),'band':i} for i in (1,2,3)],
            'probability':{'path':str(self.image),'band':4},'cloud_threshold':40,'apply_cloud_mask':True,'cloud_mask_issue':False}
        self.window = MainWindow()
        self.window.output.setText(str(self.root/'results'))
        self.window.show(); self.application.processEvents()

    def tearDown(self):
        self.window.close(); self.application.processEvents(); self.window.deleteLater()
        self.application.processEvents(); self.temp.cleanup()

    def wait_job(self):
        deadline = time.monotonic()+60
        while self.window.job is not None and time.monotonic()<deadline:
            self.application.processEvents(); QTest.qWait(20)
        self.assertIsNone(self.window.job,'worker did not finish')
        self.assertEqual(self.window.last_result['state'],'done',self.window.last_result)

    def test_runtime_has_no_streamlit_or_webview(self):
        self.assertIsNone(importlib.util.find_spec('streamlit'))
        self.assertIsNone(importlib.util.find_spec('webview'))
        self.assertFalse(self.window.preview_button.isEnabled())
        self.assertEqual(self.window.stack.currentIndex(),0)

    def test_band_mapping_validation(self):
        dialog = BandDialog([str(self.image)],self.window)
        for i in range(3):
            dialog.combos[i].setCurrentIndex(i+1)
        dialog.satellite.setCurrentIndex(dialog.satellite.findData('S2'))
        dialog.qa_type.setCurrentIndex(dialog.qa_type.findData('s2cloudless'))
        dialog.qa.setCurrentIndex(4)
        spec = dialog.configuration()
        self.assertEqual([b['band'] for b in spec['bands']],[1,2,3])
        self.assertEqual(spec['probability']['band'],4)
        dialog.combos[1].setCurrentIndex(1)
        with self.assertRaisesRegex(ValueError,'중복'):
            dialog.configuration()
        dialog.close()

    def test_edit_dialog_preserves_mapping_and_scale(self):
        scene = copy.deepcopy(self.scene)
        for band in scene['bands']:
            band.update(scale=.0001,offset=.02)
        dialog = BandDialog([str(self.image)],self.window,initial=scene)
        edited = dialog.configuration()
        self.assertEqual(edited['bands'],scene['bands'])
        self.assertEqual(edited['probability']['band'],scene['probability']['band'])
        self.assertEqual(edited['satellite'],scene['satellite'])
        dialog.close()

    def test_preview_refresh_and_export_end_to_end(self):
        self.window.add_scenes([self.scene])
        self.window.request_preview(); self.wait_job()
        low = self.window.entries[0]['preview']
        self.assertEqual(self.window.stack.currentIndex(),1)
        self.assertIn('현재 설정과 일치',self.window.notice.text())
        self.window.threshold.setValue(80)
        self.assertIn('이전 결과',self.window.notice.text())
        self.window.request_preview(); self.wait_job()
        high = self.window.entries[0]['preview']
        self.assertGreater(high['valid_percent'],low['valid_percent'])
        self.window.request_export(); self.wait_job()
        result = self.window.last_result['results'][0]
        folder = Path(result['folder'])
        masks = gdal.Open(str(folder/'masks.tif')).ReadAsArray()
        self.assertAlmostEqual(high['valid_percent'],100*np.mean(masks[0]==0))
        self.assertEqual((folder/'preview.png').read_bytes(),(Path(high['folder'])/'after.png').read_bytes())
        self.assertEqual(self.window.results.count(),1)

    def test_overlay_and_zoom_are_display_only(self):
        self.window.add_scenes([self.scene]); self.window.request_preview(); self.wait_job()
        signature = self.window.entries[0]['preview']['signature']
        self.window.opacity.setValue(25)
        self.assertEqual(self.window.before.mask.opacity(),.25)
        self.assertEqual(self.window.after.mask.opacity(),.25)
        self.window.before.scale(1.5,1.5); self.window.before.broadcast()
        self.assertAlmostEqual(self.window.before.transform().m11(),self.window.after.transform().m11())
        self.window.overlay.setChecked(False)
        self.assertEqual(self.window.after.mask.opacity(),0)
        self.assertIsNone(self.window.job)
        self.assertEqual(signature,self.window.entries[0]['preview']['signature'])

    def test_scene_settings_are_retained_and_can_apply_to_all(self):
        other = copy.deepcopy(self.scene); other['name'] = 'second'
        self.window.add_scenes([self.scene,other])
        self.window.threshold.setValue(70)
        self.window.scenes.setCurrentRow(1)
        self.assertEqual(self.window.threshold.value(),40)
        self.window.scenes.setCurrentRow(0)
        self.assertEqual(self.window.threshold.value(),70)
        self.window.apply_all()
        self.window.scenes.setCurrentRow(1)
        self.assertEqual(self.window.threshold.value(),70)
        self.window.remove_scene()
        self.assertEqual(len(self.window.entries),1)

    def test_close_stops_running_worker(self):
        self.window.add_scenes([self.scene]); self.window.request_preview()
        process = self.window.job['process']
        self.window.close()
        self.assertIsNotNone(process.poll())

    def test_google_configuration_checks_without_authenticating(self):
        dialog = DownloadDialog(self.root,'ee-test',self.window)
        spec = dialog.configuration('download')
        self.assertEqual(spec['inputs']['sat_list'],['S2'])
        self.assertEqual(spec['project'],'ee-test')
        dialog.bounds['east'].setValue(dialog.bounds['west'].value())
        with self.assertRaisesRegex(ValueError,'영역'):
            dialog.configuration('download')
        dialog.close()


if __name__ == '__main__':
    unittest.main()
