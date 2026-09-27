import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from desktop.native_collection import DownloadDialog
from desktop.kml_regions import read_regions
from desktop.worker import run


def kml(body):
    return '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'+body+'</Document></kml>'


def polygon(coords='129.10,35.14,0 129.13,35.14,0 129.12,35.17,0 129.10,35.14,0'):
    return '<Polygon><outerBoundaryIs><LinearRing><coordinates>'+coords+'</coordinates></LinearRing></outerBoundaryIs></Polygon>'


class CollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root/'해안 영역.kml'
        self.dialog = DownloadDialog(self.root, 'ee-test')

    def tearDown(self):
        self.dialog.reject()
        self.dialog.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def write(self, value):
        self.path.write_text(value, encoding='utf-8')
        return self.path

    def test_multiple_regions_preserve_selected_triangle_and_hole(self):
        hole = '<innerBoundaryIs><LinearRing><coordinates>129.112,35.145 129.118,35.145 129.116,35.15 129.112,35.145</coordinates></LinearRing></innerBoundaryIs>'
        second = polygon().replace('</Polygon>',hole+'</Polygon>')
        self.write(kml('<Placemark><name>첫 영역</name>'+polygon()+'</Placemark><Placemark><name>두 번째</name>'+second+'</Placemark>'))
        self.dialog.load_kml(self.path)
        self.assertEqual(self.dialog.region_choice.count(), 2)
        self.dialog.region_choice.setCurrentIndex(1)
        spec = self.dialog.configuration('download')
        self.assertEqual(spec['region']['name'], '두 번째')
        self.assertEqual(len(spec['inputs']['polygon']), 2)
        self.assertEqual(len(spec['inputs']['polygon'][0]), 4)  # Triangle, not bounding rectangle
        self.assertFalse(self.dialog.bounds['west'].isEnabled())
        self.dialog.area_mode.setCurrentIndex(0)
        self.assertEqual(len(self.dialog.configuration('download')['inputs']['polygon'][0]),5)

    def test_invalid_and_unsupported_kml(self):
        invalid = [kml('<Placemark><Point><coordinates>129,35</coordinates></Point></Placemark>'),
            kml('<Placemark>'+polygon('0,0 1,1 0,1 1,0 0,0')+'</Placemark>'),
            kml('<Placemark>'+polygon('nan,35 129,35 129,36')+'</Placemark>'),
            '<!DOCTYPE kml [<!ENTITY x SYSTEM "file:///private">]><kml>&x;</kml>', '<broken>']
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                read_regions(self.write(value))

    def test_large_valid_polygon_rejected_before_collection(self):
        self.dialog.load_kml(self.write(kml('<Placemark>'+polygon('129,35 130,35 130,36 129,35')+'</Placemark>')))
        with self.assertRaisesRegex(ValueError, '0.15'):
            self.dialog.configuration('download')

    def test_failed_load_does_not_replace_existing_selection(self):
        self.dialog.load_kml(self.write(kml('<Placemark>'+polygon()+'</Placemark>')))
        original = self.dialog.configuration('download')['inputs']['polygon']
        with self.assertRaises(ValueError):
            self.dialog.load_kml(self.write('<invalid>'))
        self.assertEqual(self.dialog.configuration('download')['inputs']['polygon'],original)

    def test_auth_stays_in_dialog_and_success_updates_status(self):
        process = Mock(); process.poll.return_value = None
        job = {'process':process,'project':'ee-test'}
        self.dialog.show()
        with patch('desktop.native_collection.jobs.start', return_value=job) as start:
            self.dialog.accept_mode('authenticate')
            self.assertTrue(self.dialog.isVisible())
            self.assertFalse(self.dialog.download.isEnabled())
            self.assertEqual(start.call_args.args[0],{'mode':'authenticate','project':'ee-test'})
        process.poll.return_value = 0
        with patch('desktop.native_collection.jobs.status',return_value={'state':'done','connected':True}):
            self.dialog.poll_auth()
        self.assertIn('연결 성공',self.dialog.connection.text())
        self.assertTrue(self.dialog.download.isEnabled())
        saved = json.loads(self.dialog.preferences.read_text(encoding='utf-8'))
        self.assertEqual(saved, {'project':'ee-test'})

    def test_close_cancels_auth_and_failure_is_not_success(self):
        process = Mock(); process.poll.return_value = 1
        self.dialog.auth_job = {'process':process,'project':'ee-test'}
        import time
        self.dialog.auth_started = time.monotonic()
        with patch('desktop.native_collection.jobs.status',return_value={'state':'error','message':'permission denied'}):
            self.dialog.poll_auth()
        self.assertIn('연결 실패',self.dialog.connection.text())
        process.poll.return_value = None
        self.dialog.auth_job = {'process':process,'project':'ee-test'}
        self.dialog.reject()
        process.terminate.assert_called_once()

    def test_worker_uses_official_localhost_auth_and_checks_project(self):
        spec = self.root/'job.json'
        spec.write_text(json.dumps({'mode':'authenticate','project':'ee-test'}))
        ee = Mock()
        with patch.dict('sys.modules', {'ee':ee}):
            self.assertEqual(run(spec),0)
        ee.Authenticate.assert_called_once_with(auth_mode='localhost:0',force=True)
        ee.Initialize.assert_called_once_with(project='ee-test')
        ee.Number.return_value.getInfo.assert_called_once()
        self.assertTrue(json.loads((self.root/'status.json').read_text(encoding='utf-8'))['connected'])


if __name__ == '__main__':
    unittest.main()
