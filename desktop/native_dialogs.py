from pathlib import Path
from datetime import date, timedelta
import uuid

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QComboBox, QCheckBox, QDoubleSpinBox, QDialogButtonBox, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QLineEdit, QPushButton, QFileDialog, QDateEdit, QGroupBox)

from desktop.processing import inspect, NAMES


class BandDialog(QDialog):
    def __init__(self, paths, parent=None, initial=None):
        super().__init__(parent)
        self.setWindowTitle('영상 구성 · 밴드 지정')
        self.resize(720,700)
        self.scene = None
        rasters = [inspect(path) for path in paths]
        self.entries = [(f'{Path(r["path"]).name} · {i}번 {r["descriptions"][i-1]}', {'path':r['path'],'band':i})
                        for r in rasters for i in range(1,r['bands']+1)]
        layout = QVBoxLayout(self)
        heading = QLabel('밴드 순서를 확인해 주세요')
        heading.setObjectName('sectionTitle')
        layout.addWidget(heading)
        note = QLabel('같은 촬영 장면의 파일만 함께 지정하세요. 밴드 이름은 자동으로 추측하지 않습니다.\n구름 정보가 없어도 영상을 처리할 수 있습니다.')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.name = QLineEdit(Path(paths[0]).stem)
        self.satellite = QComboBox()
        for label, value in [('기타 / 모름','OTHER'),('Landsat 5','L5'),('Landsat 7','L7'),('Landsat 8','L8'),('Landsat 9','L9'),('Sentinel-2','S2')]:
            self.satellite.addItem(label,value)
        self.rgb = QCheckBox('RGB 3개 밴드만 사용')
        self.rgb.setChecked(sum(r['bands'] for r in rasters) < 5)
        form.addRow('장면 이름',self.name)
        form.addRow('위성',self.satellite)
        form.addRow('',self.rgb)
        layout.addLayout(form)
        self.table = QTableWidget(5,4)
        self.table.setHorizontalHeaderLabels(['역할','파일 · 밴드','스케일','오프셋'])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0,65)
        self.table.setColumnWidth(2,112)
        self.table.setColumnWidth(3,112)
        self.combos, self.scales, self.offsets = [], [], []
        for row, name in enumerate(NAMES):
            item = QTableWidgetItem(name)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row,0,item)
            combo = self.band_combo()
            scale, offset = QDoubleSpinBox(), QDoubleSpinBox()
            for box in (scale,offset):
                box.setRange(-1e9,1e9)
                box.setDecimals(8)
            scale.setValue(1)
            self.table.setCellWidget(row,1,combo)
            self.table.setCellWidget(row,2,scale)
            self.table.setCellWidget(row,3,offset)
            self.combos.append(combo); self.scales.append(scale); self.offsets.append(offset)
        self.table.setMinimumHeight(205)
        layout.addWidget(self.table)
        self.calibration = QCheckBox('스케일·오프셋을 직접 지정 (해제 시 파일 메타데이터 사용)')
        self.calibration.toggled.connect(self.update_fields)
        layout.addWidget(self.calibration)
        masks = QFormLayout()
        self.qa_type = QComboBox()
        for label,value in [('없음 · 구름 판정 없이 처리','none'),('구름 마스크 · 0 맑음 / 그 외 구름','binary'),
                            ('Landsat Collection 2 QA_PIXEL','landsat_qa_pixel'),('Sentinel-2 QA60','s2_qa60'),
                            ('Sentinel-2 SCL','s2_scl'),('s2cloudless 확률 · 0–100','s2cloudless')]:
            self.qa_type.addItem(label,value)
        self.qa = self.band_combo()
        self.pan = self.band_combo('사용하지 않음')
        masks.addRow('구름 정보 형식', self.qa_type)
        masks.addRow('구름 정보 밴드', self.qa)
        masks.addRow('PAN 선명화 밴드', self.pan)
        layout.addLayout(masks)
        self.rgb.toggled.connect(self.update_fields)
        self.satellite.currentIndexChanged.connect(self.update_fields)
        self.qa_type.currentIndexChanged.connect(self.update_fields)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('장면 추가')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.accept_scene)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if initial:
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText('설정 적용')
            self.name.setText(initial['name'])
            self.satellite.setCurrentIndex(self.satellite.findData(initial.get('satellite','OTHER')))
            self.rgb.setChecked(len(initial['bands']) == 3)
            self.calibration.setChecked(any('scale' in band or 'offset' in band for band in initial['bands']))
            def choose(combo,entry):
                if entry:
                    for i in range(1,combo.count()):
                        data = combo.itemData(i)
                        if data['path'] == str(Path(entry['path']).resolve()) and data['band'] == entry.get('band',1):
                            combo.setCurrentIndex(i); break
            for row,band in enumerate(initial['bands']):
                choose(self.combos[row],band)
                self.scales[row].setValue(band.get('scale',1))
                self.offsets[row].setValue(band.get('offset',0))
            qa = initial.get('probability') or initial.get('qa')
            if qa:
                kind = 's2cloudless' if initial.get('probability') else qa.get('kind','binary')
                self.qa_type.setCurrentIndex(self.qa_type.findData(kind)); choose(self.qa,qa)
            choose(self.pan,initial.get('pan'))
        self.update_fields()

    def band_combo(self, empty='선택해 주세요'):
        combo = QComboBox()
        combo.addItem(empty,None)
        for label,entry in self.entries:
            combo.addItem(label,entry)
        return combo

    def update_fields(self,*args):
        for row in range(5):
            self.table.setRowHidden(row, self.rgb.isChecked() and row >= 3)
            self.scales[row].setEnabled(self.calibration.isChecked())
            self.offsets[row].setEnabled(self.calibration.isChecked())
        self.qa.setEnabled(self.qa_type.currentData() != 'none')
        self.pan.setEnabled(not self.rgb.isChecked() and self.satellite.currentData() in ('L7','L8','L9'))

    def configuration(self):
        count = 3 if self.rgb.isChecked() else 5
        bands = [self.combos[i].currentData() for i in range(count)]
        if any(b is None for b in bands):
            raise ValueError('필요한 영상 밴드를 모두 지정해 주세요.')
        if len({(b['path'],b['band']) for b in bands}) != count:
            raise ValueError('같은 밴드를 중복 지정할 수 없습니다.')
        scene = {'name':self.name.text().strip() or 'scene', 'satellite':self.satellite.currentData(),
                 'bands':[dict(b) for b in bands], 'cloud_threshold':40, 'apply_cloud_mask':True, 'cloud_mask_issue':False}
        if self.calibration.isChecked():
            for i,band in enumerate(scene['bands']):
                band.update(scale=self.scales[i].value(),offset=self.offsets[i].value())
        kind = self.qa_type.currentData()
        if kind != 'none':
            if self.qa.currentData() is None:
                raise ValueError('구름 정보 밴드를 지정해 주세요.')
            if kind == 'landsat_qa_pixel' and scene['satellite'] not in ('L5','L7','L8','L9'):
                raise ValueError('QA_PIXEL을 사용하려면 Landsat 위성을 선택해 주세요.')
            scene['probability' if kind == 's2cloudless' else 'qa'] = dict(self.qa.currentData(),kind=kind)
        if self.pan.isEnabled() and self.pan.currentData():
            scene['pan'] = dict(self.pan.currentData())
        return scene

    def accept_scene(self):
        try:
            self.scene = self.configuration()
            self.accept()
        except ValueError as error:
            QMessageBox.warning(self,'입력 확인',str(error))


# Kept as a public import for existing callers.
from desktop.native_collection import DownloadDialog
