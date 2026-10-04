import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np
from osgeo import gdal, osr
from PIL import Image
from streamlit.testing.v1 import AppTest

from desktop.processing import process_scene, inspect
from desktop.preview import create_preview, scene_signature, blended_preview


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(32652)
        y, x = np.mgrid[:60,:60]
        values = [x+y+10, x+2*y+20, 2*x+y+30, np.where(x < 20, 20, np.where(x < 40, 60, 90))]
        self.path = self.root / 'scene.tif'
        ds = gdal.GetDriverByName('GTiff').Create(str(self.path),60,60,4,gdal.GDT_Float32)
        ds.SetProjection(srs.ExportToWkt())
        ds.SetGeoTransform((300000,10,0,3900000,0,-10))
        for i, arr in enumerate(values,1):
            ds.GetRasterBand(i).WriteArray(arr)
        ds = None
        self.scene = {'name':'scene','satellite':'S2', 'bands':[{'path':str(self.path),'band':i} for i in (1,2,3)],
                      'probability':{'path':str(self.path),'band':4},'cloud_threshold':40,
                      'apply_cloud_mask':True,'cloud_mask_issue':False}

    def tearDown(self):
        self.temp.cleanup()

    def test_threshold_changes_preview_and_matches_final_export(self):
        low = create_preview(self.scene, self.root/'low')
        high_scene = dict(self.scene, cloud_threshold=80)
        high = create_preview(high_scene, self.root/'high')
        self.assertLess(low['valid_percent'], high['valid_percent'])
        self.assertGreater(low['cloud_percent'], high['cloud_percent'])
        self.assertEqual(low['display_ranges'], high['display_ranges'])
        saved = process_scene(high_scene, self.root/'final')
        ds = gdal.Open(str(Path(saved['folder'])/'masks.tif'))
        excluded = ds.GetRasterBand(1).ReadAsArray()
        ds = None
        self.assertAlmostEqual(high['valid_percent'], 100*np.mean(excluded == 0))
        with Image.open(Path(saved['folder'])/'preview.png') as exported, Image.open(self.root/'high'/'after.png') as shown:
            np.testing.assert_array_equal(np.asarray(exported),np.asarray(shown))
        self.assertEqual({p.name for p in (self.root/'high').iterdir()}, {'before.png','after.png','mask.png','preview.json'})

    def test_cloud_toggle_keeps_mask_but_changes_exclusion(self):
        masked = create_preview(self.scene, self.root/'masked')
        unmasked = create_preview(dict(self.scene,apply_cloud_mask=False),self.root/'unmasked')
        self.assertEqual(masked['cloud_percent'],unmasked['cloud_percent'])
        self.assertEqual(unmasked['valid_percent'],100)
        self.assertLess(masked['valid_percent'],100)

    def test_all_clouds_are_visible_in_preview_but_export_is_rejected(self):
        scene = dict(self.scene,cloud_threshold=0)
        preview = create_preview(scene,self.root/'all')
        self.assertFalse(preview['can_export'])
        self.assertEqual(preview['valid_percent'],0)
        with self.assertRaisesRegex(ValueError,'유효 픽셀'):
            process_scene(scene,self.root/'final')

    def test_opacity_changes_display_only(self):
        preview = create_preview(self.scene,self.root/'preview')
        report_before = (Path(preview['folder'])/'preview.json').read_bytes()
        zero = np.asarray(blended_preview(preview['folder'],'before',0))
        full = np.asarray(blended_preview(preview['folder'],'before',1))
        with Image.open(Path(preview['folder'])/'before.png') as image:
            np.testing.assert_array_equal(zero,np.asarray(image))
        self.assertFalse(np.array_equal(zero,full))
        self.assertEqual(report_before,(Path(preview['folder'])/'preview.json').read_bytes())

    def test_settings_and_file_changes_invalidate_signature(self):
        signature = scene_signature(self.scene)
        self.assertNotEqual(signature,scene_signature(dict(self.scene,cloud_threshold=80)))
        stat = self.path.stat()
        os.utime(self.path,ns=(stat.st_atime_ns,stat.st_mtime_ns+1_000_000))
        self.assertNotEqual(signature,scene_signature(self.scene))
        with self.assertRaisesRegex(ValueError,'입력 파일'):
            create_preview(self.scene,self.root/'out',expected_signature=signature)

    def test_ui_marks_changed_settings_as_stale(self):
        preview = create_preview(self.scene,self.root/'preview')
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'desktop_app.py')).run(timeout=40)
        app.sidebar.radio[0].set_value('CoastSat 폴더 전처리').run()
        site_box = next(x for x in app.text_input if x.label.startswith('사이트 폴더'))
        site_box.set_value(str(self.root))
        app.session_state['folder_scenes'] = [self.scene]
        app.session_state['folder_scenes_path'] = str(self.root.resolve())
        app.session_state['folder_revision'] = 'test'
        app.session_state['preview_folder'] = preview
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any('현재 설정과 일치' in x.value for x in app.success))
        threshold = next(x for x in app.slider if x.label.startswith('Sentinel-2'))
        threshold.set_value(80).run()
        self.assertFalse(app.exception)
        self.assertTrue(any('이전 설정의 미리보기' in x.value for x in app.warning))
        self.assertIn('40%', next(x.value for x in app.caption if x.value.startswith('표시 장면:')))
        opacity = next(x for x in app.slider if x.label.startswith('마스크 투명도'))
        opacity.set_value(20).run()
        self.assertFalse(app.exception)

    def test_local_preview_button_runs_worker_and_refreshes_results(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'desktop_app.py')).run(timeout=40)
        app.session_state['rasters'] = [inspect(self.path)]
        app.session_state['input_revision'] = 'preview-worker-test'
        app.run()
        next(x for x in app.checkbox if x.label.startswith('RGB 3개')).set_value(True).run()
        for i, name in enumerate(['Blue','Green','Red'],1):
            box = next(x for x in app.selectbox if x.label == name)
            box.select_index(i).run()
        next(x for x in app.selectbox if x.label == '위성 종류').set_value('S2').run()
        next(x for x in app.selectbox if x.label == '구름 정보 형식').set_value('s2cloudless').run()
        next(x for x in app.selectbox if x.label == '구름 정보 밴드').select_index(4).run()
        next(x for x in app.button if x.label == '미리보기 갱신').click().run()
        job = app.session_state['job']
        self.assertEqual(job['process'].wait(timeout=60),0)
        app.run()
        self.assertFalse(app.exception)
        preview = app.session_state['preview_local']
        self.assertTrue(any('현재 설정과 일치' in x.value for x in app.success))
        next(x for x in app.slider if x.label == '구름 확률 기준 (%)').set_value(80).run()
        self.assertTrue(any('이전 설정의 미리보기' in x.value for x in app.warning))
        next(x for x in app.button if x.label == '미리보기 갱신').click().run()
        self.assertEqual(app.session_state['job']['process'].wait(timeout=60),0)
        app.run()
        self.assertFalse(app.exception)
        self.assertGreater(app.session_state['preview_local']['valid_percent'],preview['valid_percent'])


if __name__ == '__main__':
    unittest.main()
