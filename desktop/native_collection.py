"""Native GEE authentication and local KML collection-area selection."""
import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, QDate, QTimer, QUrl
from PySide6.QtGui import QPainterPath, QPen, QColor, QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QComboBox, QCheckBox, QDoubleSpinBox, QLineEdit, QPushButton, QFileDialog,
    QDateEdit, QGroupBox, QGraphicsView, QGraphicsScene, QMessageBox, QWidget, QScrollArea)
import uuid

from desktop import jobs
from desktop.kml_regions import read_regions, validate_bounds


class DownloadDialog(QDialog):
    def __init__(self, state_root, project='', parent=None):
        super().__init__(parent)
        self.setWindowTitle('GEE 로그인 · KML 영역으로 위성영상 수집')
        self.resize(700, 810)
        self.root = Path(state_root)
        self.spec = None
        self.auth_job = None
        self.auth_started = 0
        self.regions = []
        self.preferences = self.root/'gee-project.json'
        if not project:
            try:
                project = json.loads(self.preferences.read_text(encoding='utf-8')).get('project', '')
            except (OSError, ValueError, AttributeError):
                pass
        outer = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); layout = QVBoxLayout(content)
        scroll.setWidget(content); outer.addWidget(scroll)
        account = QGroupBox('1. GEE 로그인 · 연결 확인')
        account_layout = QVBoxLayout(account)
        note = QLabel('본인의 Google 계정과 Earth Engine 사용 등록을 마친 Cloud 프로젝트가 필요합니다.\n로그인은 기본 브라우저에서 진행합니다. 로컬 영상 전처리에는 로그인이 필요 없습니다.')
        note.setWordWrap(True); account_layout.addWidget(note)
        form = QFormLayout()
        self.project = QLineEdit(project); self.project.setPlaceholderText('프로젝트 이름이 아닌 ID · 예: ee-my-project')
        self.project.textChanged.connect(self.project_changed)
        form.addRow('프로젝트 ID', self.project); account_layout.addLayout(form)
        actions = QHBoxLayout()
        self.login = QPushButton('Google 로그인 / 계정 변경')
        self.login.clicked.connect(lambda: self.accept_mode('authenticate')); actions.addWidget(self.login)
        self.check = QPushButton('GEE 연결 확인')
        self.check.clicked.connect(lambda: self.accept_mode('check')); actions.addWidget(self.check)
        self.cancel_auth = QPushButton('인증 중지'); self.cancel_auth.clicked.connect(self.stop_auth); self.cancel_auth.setEnabled(False); actions.addWidget(self.cancel_auth)
        account_layout.addLayout(actions)
        self.connection = QLabel('연결 미확인 · 로그인 또는 GEE 연결 확인을 눌러 주세요.')
        self.connection.setWordWrap(True); self.connection.setTextFormat(Qt.TextFormat.PlainText); account_layout.addWidget(self.connection)
        guide = QPushButton('GEE 등록·인증 안내 열기')
        guide.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://developers.google.com/earth-engine/guides/auth')))
        account_layout.addWidget(guide); layout.addWidget(account)

        area = QGroupBox('2. 수집 영역'); area_layout = QVBoxLayout(area)
        row = QHBoxLayout()
        self.area_mode = QComboBox(); self.area_mode.addItems(['경도·위도로 사각형 지정', 'KML에서 영역 선택'])
        self.area_mode.currentIndexChanged.connect(self.update_area); row.addWidget(self.area_mode, 1)
        self.kml_button = QPushButton('KML 파일 불러오기'); self.kml_button.clicked.connect(self.choose_kml); row.addWidget(self.kml_button)
        area_layout.addLayout(row)
        self.kml_name = QLabel('KML 파일 미선택'); self.kml_name.setTextFormat(Qt.TextFormat.PlainText); self.kml_name.setWordWrap(True); area_layout.addWidget(self.kml_name)
        self.region_choice = QComboBox(); self.region_choice.setAccessibleName('KML 수집 영역 선택')
        self.region_choice.currentIndexChanged.connect(self.update_area); area_layout.addWidget(self.region_choice)
        coord_row = QHBoxLayout(); self.bounds = {}
        for key, label, value, limit in [('west','서쪽',129.10,180), ('east','동쪽',129.13,180), ('south','남쪽',35.14,85), ('north','북쪽',35.17,85)]:
            cell = QVBoxLayout(); cell.addWidget(QLabel(label))
            spin = QDoubleSpinBox(); spin.setDecimals(6); spin.setRange(-limit,limit); spin.setValue(value)
            self.bounds[key] = spin; cell.addWidget(spin); coord_row.addLayout(cell)
        area_layout.addLayout(coord_row)
        self.map_scene = QGraphicsScene(self)
        self.area_view = QGraphicsView(self.map_scene); self.area_view.setMinimumHeight(125); self.area_view.setMaximumHeight(155)
        self.area_view.setAccessibleName('KML 영역 윤곽 미리보기'); area_layout.addWidget(self.area_view)
        self.area_note = QLabel(); self.area_note.setTextFormat(Qt.TextFormat.PlainText); self.area_note.setWordWrap(True); area_layout.addWidget(self.area_note)
        detail = QLabel('WGS84 경도·위도 · 영역 폭 각각 0.15도 이하\nKML은 선택한 다각형으로 영상을 검색합니다. 내려받는 파일은 영역을 감싸는 사각형이며, 경계대로 잘라내지는 않습니다.')
        detail.setWordWrap(True); area_layout.addWidget(detail); layout.addWidget(area)

        form = QFormLayout()
        self.site = QLineEdit('my_coast'); form.addRow('조사 지역 이름',self.site)
        self.start = QDateEdit(QDate.currentDate().addDays(-90)); self.end = QDateEdit(QDate.currentDate())
        for edit in (self.start,self.end):
            edit.setCalendarPopup(True); edit.setDisplayFormat('yyyy-MM-dd'); edit.setDateRange(QDate(1984,1,1),QDate.currentDate())
        dates = QHBoxLayout(); dates.addWidget(self.start); dates.addWidget(QLabel('~')); dates.addWidget(self.end)
        form.addRow('기간 · 종료일 미포함',dates)
        satellites = QHBoxLayout(); self.sats = {}
        for sat in ['L5','L7','L8','L9','S2']:
            cb = QCheckBox(sat); cb.setChecked(sat == 'S2'); self.sats[sat] = cb; satellites.addWidget(cb)
        form.addRow('위성',satellites)
        folder = QHBoxLayout(); self.folder = QLineEdit(str(self.root/'downloads'))
        browse = QPushButton('찾기'); browse.clicked.connect(self.choose_folder); folder.addWidget(self.folder); folder.addWidget(browse)
        form.addRow('저장 위치',folder); layout.addLayout(form)
        actions = QHBoxLayout()
        self.download = QPushButton('선택 영역의 영상 수집'); self.download.setObjectName('primary'); self.download.clicked.connect(lambda: self.accept_mode('download'))
        actions.addWidget(self.download); close = QPushButton('닫기'); close.clicked.connect(self.reject); actions.addWidget(close); outer.addLayout(actions)
        self.timer = QTimer(self); self.timer.setInterval(300); self.timer.timeout.connect(self.poll_auth)
        self.update_area()

    def project_changed(self):
        if hasattr(self, 'connection'):
            self.connection.setText('프로젝트가 바뀌었습니다. GEE 연결을 다시 확인해 주세요.')

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self,'영상 저장 폴더',self.folder.text())
        if folder:
            self.folder.setText(folder)

    def choose_kml(self):
        path, _ = QFileDialog.getOpenFileName(self,'수집 영역 KML 선택','','KML 영역 (*.kml *.KML)')
        if path:
            try:
                self.load_kml(path)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self,'KML 확인',str(error))

    def load_kml(self, path):
        regions = read_regions(path)
        self.regions = regions
        self.region_choice.blockSignals(True); self.region_choice.clear()
        for region in regions:
            self.region_choice.addItem(region['name'])
        self.region_choice.blockSignals(False)
        self.kml_name.setText(f'{Path(path).name} · {len(regions)}개 영역 · 아래 목록에서 하나를 선택하세요.')
        self.area_mode.setCurrentIndex(1); self.update_area()

    def update_area(self, *args):
        if not hasattr(self, 'area_note'):
            return
        using_kml = self.area_mode.currentIndex() == 1
        self.region_choice.setVisible(using_kml); self.area_view.setVisible(using_kml); self.kml_name.setVisible(using_kml)
        for spin in self.bounds.values():
            spin.setEnabled(not using_kml)
        self.map_scene.clear()
        if not using_kml:
            self.area_note.setText('서쪽 < 동쪽, 남쪽 < 북쪽 순서로 입력하세요.'); return
        index = self.region_choice.currentIndex()
        if index < 0:
            self.area_note.setText('KML 파일을 불러와 수집할 다각형을 선택하세요.'); return
        region = self.regions[index]
        for key, value in zip(['west','south','east','north'], region['bounds']):
            self.bounds[key].setValue(value)
        # Local outline only. Translation/scaling prevents tiny geographic coordinates
        # from producing an oversized pen; odd-even filling preserves inner holes.
        west,south,east,north = region['bounds']; scale = 1000/max(east-west,north-south)
        path = QPainterPath(); path.setFillRule(Qt.FillRule.OddEvenFill)
        for ring in region['polygon']:
            path.moveTo((ring[0][0]-west)*scale, -(ring[0][1]-south)*scale)
            for x,y in ring[1:]:
                path.lineTo((x-west)*scale, -(y-south)*scale)
            path.closeSubpath()
        pen = QPen(QColor('#007d88')); pen.setCosmetic(True); pen.setWidth(2)
        self.map_scene.addPath(path,pen,QColor('#bfe7e9'))
        self.area_view.setSceneRect(path.boundingRect().adjusted(-20,-20,20,20))
        self.area_view.fitInView(self.area_view.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)
        try:
            validate_bounds(region['bounds'])
            message = f"선택: {region['name']} · 경도 폭 {east-west:.5f}° / 위도 폭 {north-south:.5f}° · 북쪽이 위 (배경지도 없음)"
        except ValueError as error:
            message = str(error)
        self.area_note.setText(message)

    def configuration(self, mode):
        project = self.project.text().strip()
        if not project:
            raise ValueError('프로젝트 ID를 입력해 주세요.')
        spec = {'mode':mode,'project':project}
        if mode != 'download':
            return spec
        if self.area_mode.currentIndex() == 1:
            index = self.region_choice.currentIndex()
            if index < 0:
                raise ValueError('KML 파일을 불러와 영역을 선택해 주세요.')
            region = self.regions[index]
            validate_bounds(region['bounds'])
            polygon = region['polygon']
            spec['region'] = region
        else:
            west,east,south,north = (self.bounds[k].value() for k in ['west','east','south','north'])
            validate_bounds([west,south,east,north])
            polygon = [[[west,south],[east,south],[east,north],[west,north],[west,south]]]
        if self.start.date() >= self.end.date():
            raise ValueError('종료일은 시작일 이후여야 합니다.')
        sats = [sat for sat,cb in self.sats.items() if cb.isChecked()]
        if not sats:
            raise ValueError('위성을 선택해 주세요.')
        site = self.site.text().strip()
        if not site or any(c in site for c in '\\/:*?"<>|') or site in ('.','..'):
            raise ValueError('조사 지역 이름에 경로 문자를 사용할 수 없습니다.')
        if not self.folder.text().strip():
            raise ValueError('저장 위치를 선택해 주세요.')
        spec['inputs'] = {'filepath':self.folder.text().strip(),'sitename':site+'_'+uuid.uuid4().hex[:8],
            'polygon':polygon,'dates':[self.start.date().toString('yyyy-MM-dd'),self.end.date().toString('yyyy-MM-dd')],
            'sat_list':sats,'landsat_collection':'C02'}
        return spec

    def accept_mode(self, mode):
        if self.auth_job:
            return
        try:
            spec = self.configuration(mode)
            self.preferences.parent.mkdir(parents=True,exist_ok=True)
            jobs_path = self.preferences.with_suffix('.tmp')
            jobs_path.write_text(json.dumps({'project':spec['project']},ensure_ascii=False),encoding='utf-8')
            jobs_path.replace(self.preferences)
            if mode == 'download':
                self.spec = spec; self.accept(); return
            self.auth_job = jobs.start(spec); self.auth_started = time.monotonic()
            self.set_auth_busy(True)
            self.connection.setText('기본 브라우저에서 Google 계정을 선택하고 권한을 허용해 주세요. 완료되면 자동으로 연결을 확인합니다.' if mode == 'authenticate' else '저장된 인증으로 GEE 프로젝트 연결을 확인하고 있습니다…')
            self.timer.start()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self,'입력 확인',str(error))

    def set_auth_busy(self, busy):
        for widget in (self.login,self.check,self.project,self.download):
            widget.setEnabled(not busy)
        self.cancel_auth.setEnabled(busy)

    def poll_auth(self):
        if not self.auth_job:
            return
        if time.monotonic()-self.auth_started > 300:
            self.stop_auth(); self.connection.setText('인증 대기 시간이 5분을 넘었습니다. 다시 로그인해 주세요.'); return
        try:
            state = jobs.status(self.auth_job)
        except (OSError, ValueError):
            return
        if self.auth_job['process'].poll() is None:
            return
        project = self.auth_job['project']
        self.auth_job = None; self.timer.stop(); self.set_auth_busy(False)
        if state.get('state') == 'done' and state.get('connected'):
            self.connection.setText(f'GEE 연결 성공 · {project}\n이 창에서 영역과 기간을 설정하고 영상을 수집하세요.')
        else:
            message = state.get('message', '연결하지 못했습니다.')
            self.connection.setText('GEE 연결 실패 · 로그인 계정, 프로젝트 ID, Earth Engine 등록 및 권한을 확인하세요.\n' + message[:650])

    def stop_auth(self):
        self.timer.stop()
        if self.auth_job:
            process = self.auth_job['process']
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except Exception:
                    process.kill(); process.wait(timeout=2)
            self.auth_job = None
        self.set_auth_busy(False)
        self.connection.setText('인증을 중지했습니다. 열려 있는 로그인 브라우저 탭을 닫아 주세요.')

    def done(self, result):
        if self.auth_job:
            self.stop_auth()
        super().done(result)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self,'area_view') and not self.map_scene.itemsBoundingRect().isEmpty():
            self.area_view.fitInView(self.area_view.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)
