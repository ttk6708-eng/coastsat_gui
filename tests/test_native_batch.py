import builtins
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from osgeo import gdal, osr
from PySide6.QtWidgets import QApplication
from desktop.native_batch import BatchImportDialog, remap_scene
from desktop.native_window import MainWindow
from desktop.worker import run
from desktop import jobs


class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.first = self.raster('첫 영상.tif',3); self.second = self.raster('두 번째.tif',3)
        self.scene = {'name':'첫 영상','bands':[{'path':str(self.first),'band':i} for i in (1,2,3)]}

    def tearDown(self):
        self.temp.cleanup()

    def raster(self,name,bands):
        path = self.root/name
        ds = gdal.GetDriverByName('GTiff').Create(str(path),16,16,bands,gdal.GDT_Float32)
        srs = osr.SpatialReference(); srs.ImportFromEPSG(32652)
        ds.SetProjection(srs.ExportToWkt()); ds.SetGeoTransform((300000,10,0,3900000,0,-10))
        for i in range(1,bands+1): ds.GetRasterBand(i).WriteArray(np.arange(256,dtype='float32').reshape(16,16)+i)
        ds = None
        return path

    def test_template_retargets_each_file_without_changing_original(self):
        copied = remap_scene(self.scene,self.second)
        self.assertEqual(copied['name'],'두 번째')
        self.assertTrue(all(b['path'] == str(self.second) for b in copied['bands']))
        self.assertEqual(self.scene['bands'][0]['path'],str(self.first))
        with self.assertRaises(ValueError): remap_scene(self.scene,self.raster('single.tif',1))

    def test_import_does_not_guess_bands_and_requires_all_ready(self):
        single = self.raster('single.tif',1)
        dialog = BatchImportDialog([self.first,self.second,single])
        self.assertFalse(dialog.add.isEnabled())
        dialog.rows[0]['scene'] = copy.deepcopy(self.scene)
        dialog.apply_template(0)
        self.assertIsNotNone(dialog.rows[1]['scene'])
        self.assertIsNone(dialog.rows[2]['scene'])
        self.assertFalse(dialog.add.isEnabled())
        dialog.table.selectRow(2); dialog.remove_selected()
        self.assertTrue(dialog.add.isEnabled())
        dialog.accept_scenes(); self.assertEqual(len(dialog.scenes),2)
        dialog.close()

    def test_sequential_failure_continues_and_records_actual_stages_without_gee(self):
        bad = copy.deepcopy(self.scene); bad['name'] = '잘못된 밴드'; bad['bands'][0]['band'] = 20
        scenes = [self.scene,bad,remap_scene(self.scene,self.second)]
        spec = self.root/'job.json'; spec.write_text(json.dumps({'mode':'process','scenes':scenes,'output':str(self.root/'out')}),encoding='utf-8')
        real_import = builtins.__import__
        def offline_import(name,*args,**kwargs):
            if name == 'ee' or name.startswith('ee.'): raise AssertionError('Offline batch imported Google Earth Engine')
            return real_import(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=offline_import): self.assertEqual(run(spec),0)
        state = json.loads((self.root/'status.json').read_text(encoding='utf-8'))
        self.assertEqual([r['state'] for r in state['queue']],['완료','실패','완료'])
        self.assertEqual(len(state['results']),2)
        self.assertEqual(state['queue'][1]['stage'],'밴드 정렬·값 보정')
        first_end = state['queue'][0]['events'][-1]['time']; next_start = state['queue'][1]['events'][0]['time']
        self.assertLessEqual(first_end,next_start)
        events = state['queue'][0]['events']
        self.assertTrue(any(e['stage']=='PAN 선명화' and e['state']=='건너뜀' for e in events))
        self.assertTrue(any('판정 불가' in e['message'] for e in events))
        report = json.loads((Path(state['results'][0]['folder'])/'report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['steps'][-1]['state'],'완료')

    def test_interrupted_worker_keeps_completed_results(self):
        (self.root/'status.json').write_text(json.dumps({'state':'running','queue':[{'state':'완료'}],'results':[{'folder':'already-saved'}]}))
        process = Mock(); process.poll.return_value = 1
        state = jobs.status({'folder':str(self.root),'process':process})
        self.assertEqual(state['state'],'error'); self.assertEqual(len(state['results']),1)
        self.assertEqual(state['queue'][0]['state'],'완료')

    def test_scene_order_and_selected_stage_details(self):
        with patch.dict(os.environ,{'COASTSAT_STATE_DIR':str(self.root/'state')}): window = MainWindow()
        window.add_scenes([self.scene,remap_scene(self.scene,self.second)])
        window.scenes.setCurrentRow(1); window.move_scene(-1)
        self.assertEqual(window.entries[0]['base']['name'],'두 번째')
        window.update_queue({'queue':[{'name':'시험','state':'완료','stage':'결과 저장','message':'완료','events':[
            {'stage':'구름·결측 판정','state':'완료','message':'구름 정보 없음'}]}]})
        self.assertIn('구름 정보 없음',window.stage_details.toPlainText())
        window.close()


if __name__ == '__main__': unittest.main()
