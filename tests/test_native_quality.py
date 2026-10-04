import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy,json,tempfile,unittest
from pathlib import Path
import numpy as np
from osgeo import gdal,osr
from desktop.processing import compute_scene,process_scene,open_raster
from desktop.preview import create_preview,scene_signature
from desktop.quality import quality_report,statistics,reference_region


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.path=self.root/'image.tif';self.ref=self.root/'reference.tif';self.qa=self.root/'qa.tif'
        self.raster(self.path,3,0);self.raster(self.ref,1,100);self.raster(self.qa,1,0)
        ds=gdal.Open(str(self.qa),gdal.GA_Update);a=np.zeros((20,20),dtype='float32');a[:,10:]=1;ds.GetRasterBand(1).WriteArray(a);ds=None
        self.scene={'name':'sample','bands':[{'path':str(self.path),'band':i} for i in (1,2,3)],
                    'qa':{'path':str(self.qa),'band':1,'kind':'binary'},'quality_reference':str(self.ref)}
    def raster(self,path,count,x):
        ds=gdal.GetDriverByName('GTiff').Create(str(path),20,20,count,gdal.GDT_Float32)
        srs=osr.SpatialReference();srs.ImportFromEPSG(32652);ds.SetProjection(srs.ExportToWkt());ds.SetGeoTransform((x,10,0,200,0,-10))
        for i in range(1,count+1):ds.GetRasterBand(i).Fill(1)
        ds=None
    def tearDown(self):self.tmp.cleanup()
    def test_common_denominator_and_exclusion_toggle(self):
        computed=compute_scene(self.scene);report,region=quality_report(self.scene,computed)
        self.assertEqual(report['whole']['pixels'],400);self.assertEqual(report['common']['pixels'],200)
        self.assertEqual(report['whole']['percent']['valid'],50);self.assertEqual(report['common']['percent']['valid'],0)
        self.scene['apply_cloud_mask']=False
        report,_=quality_report(self.scene,compute_scene(self.scene))
        self.assertEqual(report['common']['percent']['cloud'],100);self.assertEqual(report['common']['percent']['valid'],100)
        self.assertEqual(report['common']['counts']['excluded_cloud'],0)
    def test_empty_overlap_is_not_zero_quality(self):
        self.raster(self.ref,1,1000)
        report,_=quality_report(self.scene,compute_scene(self.scene))
        self.assertEqual(report['common']['pixels'],0);self.assertIsNone(report['common']['percent']['valid'])
    def test_classification_partition_and_no_cloud_information(self):
        self.scene.pop('qa');computed=compute_scene(self.scene);stats=statistics(computed)
        self.assertEqual(stats['counts']['unknown'],400);self.assertEqual(stats['counts']['valid'],400)
        self.assertEqual(stats['counts']['excluded_unknown'],0)
        self.assertEqual(sum(stats['counts'][k] for k in ('nodata','cloud','unknown','clear')),400)
    def test_preview_export_statistics_and_snapshot(self):
        preview=create_preview(self.scene,self.root/'preview')
        result=process_scene(self.scene,self.root/'export');report=json.loads((Path(result['folder'])/'report.json').read_text(encoding='utf-8'))
        self.assertEqual(preview['quality'],report['quality'])
        old=scene_signature(self.scene);self.raster(self.ref,1,200)
        self.assertNotEqual(old,scene_signature(self.scene))
    def test_cross_site_and_crs_rejected(self):
        scene=copy.deepcopy(self.scene);scene['coastsat']=True
        scene['bands'][0]['path']=str(self.root/'site/S2/ms/a.tif')
        with self.assertRaisesRegex(ValueError,'같은 지역'):reference_region(scene,open_raster(self.path))
        ds=gdal.Open(str(self.ref),gdal.GA_Update);srs=osr.SpatialReference();srs.ImportFromEPSG(4326);ds.SetProjection(srs.ExportToWkt());ds=None
        with self.assertRaisesRegex(ValueError,'좌표계'):reference_region(self.scene,open_raster(self.path))
    def test_dialog_stages_do_not_change_settings(self):
        from PySide6.QtWidgets import QApplication
        from desktop.native_quality import QualityDialog
        app=QApplication.instance() or QApplication([])
        preview=create_preview(self.scene,self.root/'preview');original=copy.deepcopy(preview)
        dialog=QualityDialog(preview)
        for i in range(5):dialog.stage.setCurrentIndex(i)
        dialog.common.setChecked(True);dialog.opacity.setValue(80)
        self.assertIn('200 픽셀',dialog.detail.toPlainText());self.assertEqual(original,preview);dialog.close()


if __name__=='__main__':unittest.main()
