import tempfile
import unittest
from pathlib import Path
import numpy as np
from osgeo import gdal, osr
from desktop.processing import process_scene, aligned_band, open_raster


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.srs = osr.SpatialReference()
        self.srs.ImportFromEPSG(32652)

    def tearDown(self):
        self.temp.cleanup()

    def raster(self, name, values, pixel=10, x=300000):
        arr = np.asarray(values, dtype='float32')
        if arr.ndim == 2:
            arr = arr[None]
        path = self.root / name
        ds = gdal.GetDriverByName('GTiff').Create(str(path), arr.shape[2], arr.shape[1], arr.shape[0], gdal.GDT_Float32)
        ds.SetGeoTransform((x,pixel,0,3900000,0,-pixel))
        ds.SetProjection(self.srs.ExportToWkt())
        for i, data in enumerate(arr,1):
            ds.GetRasterBand(i).WriteArray(data)
            ds.GetRasterBand(i).SetNoDataValue(-9999)
        ds = None
        return str(path)

    def test_offline_preserves_crs_and_marks_unknown_clouds(self):
        arr = np.arange(3*16*16,dtype='float32').reshape(3,16,16)+1
        arr[:,0,0] = -9999
        path = self.raster('한글 테스트.tif', arr)
        result = process_scene({'name':'test','bands':[{'path':path,'band':i} for i in (1,2,3)]}, self.root/'out')
        ds = open_raster(Path(result['folder'])/'preprocessed.tif')
        self.assertEqual(ds.GetGeoTransform(), (300000,10,0,3900000,0,-10))
        self.assertTrue(self.srs.IsSame(osr.SpatialReference(wkt=ds.GetProjection())))
        self.assertTrue(np.isnan(ds.ReadAsArray()[:,0,0]).all())
        np.testing.assert_array_equal(ds.ReadAsArray()[:,1:,1:], arr[:,1:,1:])
        masks = gdal.Open(str(Path(result['folder'])/'masks.tif')).ReadAsArray()
        self.assertTrue((masks[1]==255).all())
        self.assertEqual(masks[2,0,0],1)
        ds = None

    def test_cloud_mask_and_nearest_alignment(self):
        path = self.raster('ms.tif', np.ones((3,16,16)))
        mask = np.zeros((8,8)); mask[:4,:4] = 1
        qa = self.raster('cloud.tif', mask, pixel=20)
        result = process_scene({'name':'cloud','bands':[{'path':path,'band':i} for i in (1,2,3)], 'qa':{'path':qa,'kind':'binary'}}, self.root/'out')
        ds = gdal.Open(str(Path(result['folder'])/'preprocessed.tif'))
        arr = ds.ReadAsArray()
        self.assertTrue(np.isnan(arr[:,:8,:8]).all())
        self.assertTrue(np.isfinite(arr[:,8:,8:]).all())
        ds = None

    def test_nonoverlap_is_rejected(self):
        a = self.raster('a.tif', np.ones((16,16)))
        b = self.raster('b.tif', np.ones((16,16)), x=500000)
        with self.assertRaisesRegex(ValueError, '유효 픽셀'):
            process_scene({'name':'bad','bands':[{'path':a},{'path':a},{'path':b}]}, self.root/'out')

    def test_invalid_band_is_rejected(self):
        path = self.raster('a.tif', np.ones((16,16)))
        with self.assertRaisesRegex(ValueError, '밴드'):
            aligned_band({'path':path,'band':2}, open_raster(path))

    def test_combined_qa60_bits(self):
        path = self.raster('ms.tif', np.ones((3,16,16)))
        mask = np.zeros((16,16)); mask[:8] = 3072
        qa = self.raster('qa.tif', mask)
        result = process_scene({'name':'s2','bands':[{'path':path,'band':i} for i in (1,2,3)],'qa':{'path':qa,'kind':'s2_qa60'}}, self.root/'out')
        arr = gdal.Open(str(Path(result['folder'])/'masks.tif')).ReadAsArray()
        self.assertTrue((arr[1,:8]==1).all())
        self.assertTrue((arr[1,8:]==0).all())

    def test_pansharpen_landsat_on_pan_grid(self):
        rng = np.random.default_rng(123)
        path = self.raster('landsat.tif', rng.uniform(.1,.9,(5,16,16)), pixel=30)
        pan = self.raster('pan.tif', rng.uniform(.1,.9,(32,32)), pixel=15)
        result = process_scene({'name':'pan','satellite':'L8',
            'bands':[{'path':path,'band':i} for i in range(1,6)], 'pan':{'path':pan}}, self.root/'out')
        ds = open_raster(Path(result['folder'])/'preprocessed.tif')
        self.assertEqual((ds.RasterXSize,ds.RasterYSize),(32,32))
        self.assertEqual(ds.GetGeoTransform()[1],15)
        self.assertTrue(np.isfinite(ds.ReadAsArray()).all())
        ds = None


if __name__ == '__main__':
    unittest.main()
