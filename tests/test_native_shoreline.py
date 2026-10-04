import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
from PIL import Image
from osgeo import osr
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from desktop.shoreline import (DEFAULTS,split_segments,pixel_world,settings_checked,
    water_contours,export_reviewed,extract)
from desktop.preview import scene_signature
from desktop.native_shoreline import ShorelineReviewDialog


class ShorelineTests(unittest.TestCase):
    def test_bundled_model_predict_matches_saved_network_weights(self):
        import joblib, warnings, hashlib
        from desktop.shoreline import MODEL_SHA
        path=Path(__file__).resolve().parents[1]/'classification/models/NN_4classes_S2_new.pkl'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),MODEL_SHA)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore');model=joblib.load(path)
        self.assertEqual(model.activation,'relu');self.assertEqual(model.out_activation_,'softmax')
        x=np.random.default_rng(42).normal(size=(200,20))
        hidden=np.maximum(x@model.coefs_[0]+model.intercepts_[0],0)
        expected=model.classes_[np.argmax(hidden@model.coefs_[1]+model.intercepts_[1],axis=1)]
        np.testing.assert_array_equal(model.predict(x),expected)

    def test_cloud_gap_is_not_bridged(self):
        contour=np.column_stack((np.full(21,10),np.arange(21)))
        cloud=np.zeros((30,30),bool);cloud[10,10]=True
        result=split_segments([contour],(0,10,0,300,0,-10),cloud,np.zeros_like(cloud),
                              {'min_length_sl':10,'dist_clouds':20})
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]['length_m'],80)
        self.assertEqual(result[1]['length_m'],80)
        self.assertLess(result[0]['pixels'][-1][1],result[1]['pixels'][0][1])

    def test_length_applied_after_split_and_nodata_buffer(self):
        c=np.column_stack((np.full(21,10),np.arange(21)))
        mask=np.zeros((30,30),bool);mask[10,10]=True
        result=split_segments([c],(0,10,0,300,0,-10),np.zeros_like(mask),mask,
                              {'min_length_sl':80,'dist_clouds':0})
        self.assertEqual(result,[])

    def test_coastsat_coordinate_convention(self):
        self.assertEqual(pixel_world([[2,3]],(100,10,0,200,0,-10)).tolist(),[[130,180]])

    def test_threshold_uses_same_index_and_is_repeatable(self):
        index=np.tile(np.linspace(-.8,.6,100),(20,1))
        labels=np.zeros((20,100,3),bool);labels[:,:30,0]=True;labels[:,60:,2]=True
        first=water_contours(index,labels);second=water_contours(index,labels)
        self.assertEqual(first[1],second[1]);self.assertTrue(first[0])
        for a,b in zip(first[0],second[0]):np.testing.assert_array_equal(a,b)
        self.assertIn('same SWIR/G',first[2])
        with self.assertRaises(ValueError):water_contours(np.zeros((20,100)),labels)

    def test_invalid_settings_and_unsupported_inputs(self):
        for value in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):settings_checked({'dist_clouds':value})
        with self.assertRaises(ValueError):extract({'bands':[]},None,'unused')
        with self.assertRaises(ValueError):extract({'coastsat':True,'satellite':'S2','bands':[{}]*5,'apply_cloud_mask':False},None,'unused')

    def report(self,root):
        path=root/'input';path.write_text('unchanged')
        scene={'name':'test','bands':[{'path':str(path),'band':1}]}
        Image.new('RGB',(100,100)).save(root/'original.png')
        Image.new('RGBA',(100,100)).save(root/'classes.png')
        Image.new('RGBA',(100,100)).save(root/'empty.png')
        srs=osr.SpatialReference();srs.ImportFromEPSG(32652)
        return {'folder':str(root),'scene':scene,'signature':scene_signature(scene),
                'projection_wkt':srs.ExportToWkt(),'preview_step':1,'threshold':0,'warnings':[],
                'segments':[{'id':1,'length_m':100,'pixels':[[1,1],[2,2]],
                             'coordinates':[[520000,4140000],[520000,4140100]]},
                            {'id':2,'length_m':100,'pixels':[[8,8],[9,9]],
                             'coordinates':[[521000,4140000],[521000,4140100]]}]}

    def test_export_selected_geometry_axis_order_and_stale_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);report=self.report(root)
            with self.assertRaises(ValueError):export_reviewed(report,[],root/'out')
            output=Path(export_reviewed(report,[2],root/'out'))
            features=json.loads((output/'shoreline.geojson').read_text(encoding='utf-8'))['features']
            self.assertEqual(len(features),1);self.assertEqual(features[0]['properties']['segment_id'],2)
            lon,lat=features[0]['geometry']['coordinates'][0]
            self.assertTrue(128<lon<130);self.assertTrue(36<lat<39)
            self.assertFalse((output/'INCOMPLETE.txt').exists())
            (root/'input').write_text('changed original')
            with self.assertRaises(ValueError):export_reviewed(report,[1],root/'out')

    def test_review_requires_explicit_selection(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            report=self.report(Path(temp));dialog=ShorelineReviewDialog(report,temp)
            self.assertFalse(dialog.save_button.isEnabled())
            dialog.candidates.item(0).setCheckState(Qt.CheckState.Checked)
            self.assertEqual(dialog.selected(),[1]);self.assertTrue(dialog.save_button.isEnabled())
            dialog.close();dialog.deleteLater();app.processEvents()


if __name__=='__main__':unittest.main()
