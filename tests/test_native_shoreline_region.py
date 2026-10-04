import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from osgeo import osr
from PIL import Image
from PySide6.QtCore import QPointF,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from desktop.preview import scene_signature
from desktop.shoreline import pixel_world,export_reviewed
from desktop.shoreline_region import clip_region
from desktop.native_shoreline import ShorelineReviewDialog


class RegionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        path=self.root/'input.tif';path.write_bytes(b'unchanged source')
        scene={'name':'test','bands':[{'path':str(path),'band':1}]}
        for name in ['original','classes','empty']:
            Image.new('RGBA',(100,100)).save(self.root/(name+'.png'))
        transform=(520000,10,0,4140000,0,-10)
        pixels=[[50,0],[50,100]]
        srs=osr.SpatialReference();srs.ImportFromEPSG(32652)
        self.report={'folder':str(self.root),'scene':scene,'signature':scene_signature(scene),
            'preview_step':1,'transform':transform,'projection_wkt':srs.ExportToWkt(),
            'threshold':0,'warnings':[],'settings':{'min_length_sl':500},
            'segments':[{'id':1,'pixels':pixels,'coordinates':pixel_world(pixels,transform).tolist(),'length_m':1000}]}
        self.polygon=[(20,40),(80,40),(80,60),(20,60)]

    def tearDown(self):
        self.app.processEvents();self.temp.cleanup()

    def test_keep_interpolates_crossings_and_preserves_original(self):
        before=copy.deepcopy(self.report)
        result=clip_region(self.report,self.polygon,'keep')
        self.assertEqual(self.report,before)
        segment=result['segments'][0]
        self.assertEqual(segment['pixels'],[[50,20],[50,80]])
        self.assertEqual(segment['coordinates'],[[520200,4139500],[520800,4139500]])
        self.assertEqual(segment['length_m'],600)
        self.assertEqual(segment['source_segment_id'],1)

    def test_exclude_splits_and_keeps_short_manual_pieces(self):
        result=clip_region(self.report,self.polygon,'exclude')
        self.assertEqual([s['length_m'] for s in result['segments']],[200,200])
        self.assertEqual([s['pixels'] for s in result['segments']],[[[50,0],[50,20]],[[50,80],[50,100]]])

    def test_preview_decimation_matches_full_resolution_selection(self):
        small=copy.deepcopy(self.report);small['preview_step']=2
        result=clip_region(small,[(x/2,y/2) for x,y in self.polygon],'keep')
        expected=clip_region(self.report,self.polygon,'keep')
        self.assertEqual(result['segments'],expected['segments'])

    def test_invalid_empty_and_point_touch_are_rejected(self):
        cases=[[(0,0),(1,1)],[(0,0),(1,1),(2,2)],[(0,0),(80,80),(0,80),(80,0)],
               [(0,0),(1,float('nan')),(2,2)],[(0,0),(10,0),(10,10),(0,10)],
               [(0,50),(10,60),(0,60)]]
        for polygon in cases:
            with self.subTest(polygon=polygon), self.assertRaises(ValueError):clip_region(self.report,polygon,'keep')

    def test_consecutive_edits_keep_provenance_and_disconnected_lines(self):
        result=clip_region(self.report,self.polygon,'exclude')
        result=clip_region(result,[(5,40),(95,40),(95,60),(5,60)],'keep')
        self.assertEqual(len(result['region_edits']),2)
        self.assertEqual(len(result['segments']),2)
        self.assertEqual([s['source_segment_id'] for s in result['segments']],[1,1])

    def test_export_only_clipped_geometry_and_edit_history(self):
        result=clip_region(self.report,self.polygon,'exclude')
        folder=Path(export_reviewed(result,[1,2],self.root/'saved'))
        data=json.loads((folder/'shoreline.geojson').read_text(encoding='utf-8'))
        self.assertEqual(len(data['features']),2)
        self.assertTrue(all(f['properties']['region_edited'] for f in data['features']))
        saved=json.loads((folder/'report.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['region_edits'][0]['mode'],'exclude')
        self.assertEqual(saved['segments'],result['segments'])
        self.assertEqual((self.root/'input.tif').read_bytes(),b'unchanged source')

    def dialog(self):
        d=ShorelineReviewDialog(self.report,str(self.root));d.show();self.app.processEvents()
        self.addCleanup(d.deleteLater);self.addCleanup(d.close)
        return d

    def test_ui_apply_undo_reset_and_pending_save_guard(self):
        d=self.dialog();d.candidates.item(0).setCheckState(Qt.CheckState.Checked)
        d.begin_region();self.assertFalse(d.save_button.isEnabled())
        d.view.set_points(self.polygon);d.apply_region('exclude')
        self.assertEqual(len(d.report['segments']),2);self.assertTrue(d.save_button.isEnabled())
        d.undo_region();self.assertEqual(d.report,self.report);self.assertEqual(d.selected(),[1])
        d.begin_region();d.view.set_points(self.polygon);d.apply_region('keep')
        d.reset_regions();self.assertEqual(d.report,self.report);self.assertEqual(d.selected(),[])

    def test_failed_selection_and_escape_preserve_previous_result(self):
        d=self.dialog();d.begin_region();d.view.set_points([(0,0),(10,0),(10,10)])
        with patch('desktop.native_shoreline.QMessageBox.warning') as warning:
            d.apply_region('keep');warning.assert_called_once()
        self.assertEqual(d.report,self.report);self.assertTrue(d.view.drawing)
        d.reject();self.assertFalse(d.view.drawing);self.assertTrue(d.isVisible())

    def test_mouse_click_after_zoom_uses_image_coordinates(self):
        d=self.dialog();d.begin_region()
        d.view.scale(1.4,1.4);d.view.centerOn(50,50);self.app.processEvents()
        target=QPointF(30,40);position=d.view.mapFromScene(target)
        QTest.mouseClick(d.view.viewport(),Qt.MouseButton.LeftButton,pos=position)
        self.assertEqual(len(d.view.points),1)
        np.testing.assert_allclose(d.view.points[0],[30,40],atol=.5)
        d.view.undo_point();self.assertEqual(d.view.points,[])


if __name__=='__main__':unittest.main()
