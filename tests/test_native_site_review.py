import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from osgeo import gdal,osr
from desktop.site_review import inventory,inspect_row,compare


class SiteReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for k in ('ms','swir','mask','meta'):(self.root/'S2'/k).mkdir(parents=True)
        for name,gt in [('a',(0,10,0,100,0,-10)),('b',(50,10,0,100,0,-10))]:
            self.make_scene(name,gt)

    def tearDown(self):self.tmp.cleanup()

    def make_scene(self,name,gt):
        for k,n in [('ms',5),('swir',1),('mask',1)]:
            ds=gdal.GetDriverByName('GTiff').Create(str(self.root/'S2'/k/f'{name}_{k}.tif'),10,10,n,gdal.GDT_Byte)
            srs=osr.SpatialReference();srs.ImportFromEPSG(32652)
            ds.SetProjection(srs.ExportToWkt());ds.SetGeoTransform(gt);ds=None
        (self.root/'S2/meta'/f'{name}.txt').write_text(f'filename\t{name}_ms.tif\n',encoding='utf-8')

    def test_inventory_does_not_open_rasters(self):
        with patch('desktop.site_review.gdal.Open',side_effect=AssertionError('must not read headers')):
            rows=inventory(self.root)
        self.assertEqual(len(rows),2);self.assertFalse(rows[0]['issues'])

    def test_missing_duplicate_and_corrupt_are_reported(self):
        (self.root/'S2/mask/a_mask.tif').unlink()
        (self.root/'S2/ms/a_ms.tiff').write_text('invalid')
        rows=inventory(self.root);self.assertIn('mask 누락',rows[0]['issues']);self.assertIn('ms 중복',rows[0]['issues'])
        (self.root/'S2/ms/b_ms.tif').write_text('invalid')
        out=inspect_row(rows[1]);self.assertTrue(any('ms 읽기 오류' in i for i in out['issues']))

    def test_overlap_geometry_and_cross_site_guard(self):
        a,b=map(inspect_row,inventory(self.root));r=compare(a,b)
        self.assertAlmostEqual(r['reference_coverage_percent'],50)
        self.assertAlmostEqual(r['candidate_coverage_percent'],50)
        self.assertEqual(compare(a,a)['status'],'동일 격자')
        b['site']='other'
        with self.assertRaisesRegex(ValueError,'같은 지역'):compare(a,b)

    def test_contained_rotated_and_nonoverlap(self):
        self.make_scene('c',(0,5,0,100,0,-5))
        self.make_scene('d',(200,10,0,100,0,-10))
        self.make_scene('e',(0,10,2,100,1,-10))
        a,b,c,d,e=map(inspect_row,inventory(self.root))
        r=compare(a,c);self.assertAlmostEqual(r['reference_coverage_percent'],25);self.assertAlmostEqual(r['candidate_coverage_percent'],100)
        self.assertEqual(compare(a,d)['status'],'겹침 없음')
        self.assertAlmostEqual(compare(e,e)['reference_coverage_percent'],100)

    def test_dialog_reference_selection_and_uninspected_state(self):
        from PySide6.QtWidgets import QApplication
        from desktop.native_site_review import SiteReviewDialog
        app=QApplication.instance() or QApplication([])
        dialog=SiteReviewDialog();dialog.add_folder(self.root);dialog.add_folder(self.root)
        self.assertEqual(dialog.site.count(),1)
        self.assertEqual(dialog.reference.count(),0)
        dialog.select_samples();self.assertEqual(len(dialog.table.selectionModel().selectedRows()),2)
        dialog.accept_results([inspect_row(r) for r in dialog.rows])
        dialog.table.setCurrentCell(1,0)
        self.assertIn('50.00%',dialog.detail.toPlainText())
        dialog.reference.setCurrentIndex(1)
        self.assertIn('동일 격자',dialog.detail.toPlainText())
        dialog.close()


if __name__=='__main__':unittest.main()
