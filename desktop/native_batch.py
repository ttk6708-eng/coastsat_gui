"""Explicit band mapping for independent, multiband local image files."""
import copy
from pathlib import Path
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QMessageBox)
from desktop.processing import inspect
from desktop.native_dialogs import BandDialog


def remap_scene(template, path):
    metadata = inspect(path)
    scene = copy.deepcopy(template)
    scene['name'] = Path(path).stem
    entries = [*scene['bands'],scene.get('qa'),scene.get('probability'),scene.get('pan')]
    for entry in entries:
        if entry:
            if not 1 <= entry.get('band',1) <= metadata['bands']:
                raise ValueError(f'{metadata["bands"]}개 밴드만 있어 설정을 복사할 수 없습니다.')
            entry['path'] = metadata['path']
    return scene


class BatchImportDialog(QDialog):
    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle('여러 위성영상 등록 · 로그인 불필요'); self.resize(850,570)
        self.rows = []; self.scenes = []
        layout = QVBoxLayout(self)
        note = QLabel('파일 하나를 촬영 장면 하나로 등록합니다. 각 파일에 RGB 또는 5개 영상 밴드가 들어 있어야 합니다.\n밴드별 파일을 합쳐야 한다면 메인 화면의 “밴드 파일 묶기”를 사용하세요.\n첫 파일의 밴드를 지정한 후, 밴드 순서·위성·구름 정보 형식이 같은 파일에만 설정을 복사하세요.')
        note.setWordWrap(True); layout.addWidget(note)
        self.table = QTableWidget(0,3); self.table.setHorizontalHeaderLabels(['영상 파일','자료 구성','등록 상태'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        for path in dict.fromkeys(str(Path(p).resolve()) for p in paths):
            row = {'path':path,'scene':None,'metadata':None,'message':'밴드 지정 필요'}
            try:
                row['metadata'] = inspect(path)
                if row['metadata']['bands'] < 3:
                    row['message'] = '밴드 부족 · 메인 화면에서 밴드 파일 묶기 사용'
            except Exception as error:
                row['message'] = str(error)
            self.rows.append(row)
        buttons = QHBoxLayout()
        edit = QPushButton('선택 파일 밴드 지정'); edit.clicked.connect(self.configure_selected); buttons.addWidget(edit)
        apply = QPushButton('선택 설정을 나머지에 복사'); apply.clicked.connect(self.copy_settings); buttons.addWidget(apply)
        remove = QPushButton('선택 파일 제외'); remove.clicked.connect(self.remove_selected); buttons.addWidget(remove)
        layout.addLayout(buttons)
        self.note = QLabel(); self.note.setWordWrap(True); layout.addWidget(self.note)
        actions = QHBoxLayout()
        self.add = QPushButton('목록에 등록'); self.add.setObjectName('primary'); self.add.clicked.connect(self.accept_scenes); actions.addWidget(self.add)
        cancel = QPushButton('취소'); cancel.clicked.connect(self.reject); actions.addWidget(cancel); layout.addLayout(actions)
        self.refresh()
        if self.rows: self.table.selectRow(0)

    def refresh(self):
        selected = self.table.currentRow()
        self.table.setRowCount(len(self.rows))
        for i,row in enumerate(self.rows):
            meta = row['metadata']
            values = [Path(row['path']).name, f'{meta["bands"]}밴드 · {meta["width"]}×{meta["height"]}' if meta else '읽기 실패', row['message']]
            for j,text in enumerate(values):
                item = QTableWidgetItem(text); item.setToolTip(row['path'] if j == 0 else text); self.table.setItem(i,j,item)
        count = sum(row['scene'] is not None for row in self.rows)
        self.note.setText(f'{count}/{len(self.rows)}개 설정 완료 · 미설정 파일은 밴드를 지정하거나 목록에서 제외하세요. 원본 파일은 삭제하지 않습니다.')
        self.add.setEnabled(bool(self.rows) and count == len(self.rows))
        if self.rows: self.table.selectRow(min(max(selected,0),len(self.rows)-1))

    def configure_selected(self):
        i = self.table.currentRow()
        if i < 0: return
        row = self.rows[i]
        try:
            dialog = BandDialog([row['path']],self,initial=row['scene'])
            if dialog.exec() == QDialog.DialogCode.Accepted:
                row['scene'] = dialog.scene; row['message'] = '설정 완료'; self.refresh()
        except Exception as error:
            QMessageBox.warning(self,'파일 확인',str(error))

    def apply_template(self, index):
        template = self.rows[index]['scene']
        if not template:
            raise ValueError('선택 파일의 밴드를 먼저 지정해 주세요.')
        for i,row in enumerate(self.rows):
            if i == index: continue
            try:
                row['scene'] = remap_scene(template,row['path']); row['message'] = '설정 복사 완료 · 같은 구성인지 확인'
            except Exception as error:
                row['scene'] = None; row['message'] = str(error)
        self.refresh()

    def copy_settings(self):
        index = self.table.currentRow()
        if index < 0: return
        try: self.apply_template(index)
        except ValueError as error: QMessageBox.warning(self,'밴드 설정',str(error))

    def remove_selected(self):
        index = self.table.currentRow()
        if index >= 0: self.rows.pop(index); self.refresh()

    def accept_scenes(self):
        if self.rows and all(row['scene'] for row in self.rows):
            self.scenes = [row['scene'] for row in self.rows]; self.accept()
