"""CoastSat's native desktop workspace, implemented entirely with Qt Widgets."""
import copy
import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QToolBar, QDockWidget, QListWidget, QListWidgetItem, QScrollArea,
    QFormLayout, QCheckBox, QSpinBox, QSlider, QLineEdit, QFileDialog, QMessageBox,
    QPlainTextEdit, QSplitter, QStackedWidget, QFrame, QGridLayout, QProgressBar,
    QTabWidget, QStyle, QDialog, QToolButton, QMenu, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)

from desktop import jobs
from desktop.processing import scan_coastsat
from desktop.preview import scene_signature
from desktop.native_widgets import ImageView
from desktop.native_dialogs import BandDialog, DownloadDialog
from desktop.native_help import SettingsHelpDialog, TIPS
from desktop.native_batch import BatchImportDialog
from desktop.native_input_review import InputReviewDialog


STYLE = '''
QMainWindow { background:#f1f5f9; }
QWidget { color:#20374d; font-family:"Noto Sans KR","Malgun Gothic"; font-size:12px; }
QMenuBar, QMenu, QToolBar { background:#ffffff; }
QMenuBar { padding:4px; border-bottom:1px solid #dce4eb; }
QMenuBar::item { padding:5px 12px; }
QMenuBar::item:selected, QMenu::item:selected { background:#e7f4f5; color:#006c77; }
QToolBar { spacing:8px; padding:10px; border-bottom:1px solid #dce4eb; }
QToolButton { border:1px solid transparent; border-radius:5px; padding:7px 10px; }
QToolButton:hover { background:#eaf3f8; border-color:#d5e2eb; }
QDockWidget { font-weight:600; }
QDockWidget::title { background:#eaf0f5; padding:10px; border-bottom:1px solid #d5e0e8; }
QDockWidget > QWidget, QScrollArea { background:white; }
QScrollArea { border:0; }
QListWidget { background:white; border:0; outline:0; padding:6px; }
QListWidget::item { padding:12px 8px; margin:3px 0; border-radius:5px; }
QListWidget::item:selected { background:#dff2f1; color:#006b74; }
QListWidget::item:hover { background:#f0f6f9; }
QPushButton { background:white; border:1px solid #ccd8e2; border-radius:5px; padding:8px 12px; font-weight:600; }
QPushButton:hover { background:#edf7f8; border-color:#86b8bd; }
QPushButton:disabled { color:#9aabb8; background:#f3f6f8; border-color:#e1e8ee; }
QPushButton#primary { background:#007d88; color:white; border:1px solid #007d88; }
QPushButton#primary:hover { background:#006c78; }
QPushButton#primary:disabled { background:#adcbd0; border-color:#adcbd0; }
QPushButton#stop { color:#b34d36; }
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QDateEdit { background:white; border:1px solid #cfdae4; border-radius:4px; padding:6px; selection-background-color:#bfe7e9; }
QComboBox:disabled,QSpinBox:disabled,QDoubleSpinBox:disabled { background:#f3f6f8;color:#8e9eab; }
QCheckBox { spacing:8px; padding:4px 0; }
QCheckBox::indicator { width:16px; height:16px; }
QLabel#sectionTitle { font-size:18px; font-weight:700; color:#142f45; }
QLabel#muted { color:#6d8193; }
QLabel#badge { color:#007d88; background:#e4f4f3; border-radius:10px; padding:5px 10px; }
QLabel#notice { background:#eaf2f7; color:#516c82; padding:10px; border-radius:5px; }
QLabel#stale { background:#fff0d5; color:#95620d; padding:10px; border-radius:5px; }
QFrame#metric { background:white; border:1px solid #dbe5ed; border-radius:7px; }
QLabel#metricValue { font-size:22px; font-weight:700; color:#123e53; }
QFrame#empty { background:white; border:1px dashed #b9ccd9; border-radius:12px; }
QPlainTextEdit { background:#fbfcfe; border:0; font-size:11px; padding:8px; }
QProgressBar { border:1px solid #dce5ec; border-radius:4px; background:#f4f7fa; text-align:center; }
QProgressBar::chunk { background:#14a0a7; }
QSplitter::handle { background:#e3ebf1; width:5px; height:5px; }
QStatusBar { background:white; color:#60798d; border-top:1px solid #dce5ec; }
QGroupBox { border:1px solid #d5e0e8; border-radius:6px; margin-top:12px; padding:14px 10px 10px; }
QGroupBox::title { subcontrol-origin:margin; padding:0 5px; }
QTableWidget { border:1px solid #dce5ec; gridline-color:#e6edf2; }
QHeaderView::section { background:#edf3f7; border:0; padding:7px; }
'''


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('CoastSat Studio · 위성영상 전처리')
        self.resize(1440,900)
        self.setMinimumSize(1120,720)
        self.setStyleSheet(STYLE)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.root = jobs.state_root()
        self.entries = []
        self.job = None
        self.last_result = None
        self.project = ''
        self._loading = False
        self._job_entry = None
        self._log_offset = 0
        self._cancelled = False
        self.build_center()
        self.build_left()
        self.build_right()
        self.build_logs()
        self.build_menus()
        self.log_dock.hide()
        self.progress = QProgressBar(); self.progress.setFixedWidth(210); self.progress.setRange(0,100)
        self.statusBar().addPermanentWidget(QLabel('로컬 데스크톱  ·  CoastSat'))
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage('준비 · 영상을 불러오세요')
        self.timer = QTimer(self); self.timer.setInterval(250); self.timer.timeout.connect(self.poll_job); self.timer.start()
        self.stale_timer = QTimer(self); self.stale_timer.setInterval(2000); self.stale_timer.timeout.connect(self.update_stale); self.stale_timer.start()
        self.resizeDocks([self.left_dock,self.right_dock],[225,335],Qt.Orientation.Horizontal)
        self.resizeDocks([self.log_dock],[145],Qt.Orientation.Vertical)
        self.setCorner(Qt.Corner.BottomLeftCorner,Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner,Qt.DockWidgetArea.RightDockWidgetArea)
        self.update_enabled()

    def build_menus(self):
        menu = self.menuBar().addMenu('파일')
        toolbar = QToolBar('주요 작업'); toolbar.setMovable(False); toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon); self.addToolBar(toolbar)
        self.toolbar = toolbar
        brand = QLabel('COASTSAT  STUDIO  '); brand.setObjectName('sectionTitle'); toolbar.addWidget(brand)
        self.import_actions = []
        import_menu = QMenu(self)
        self.import_button = QToolButton(); self.import_button.setText('영상 불러오기')
        self.import_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.import_button.setMenu(import_menu); toolbar.addWidget(self.import_button)
        for text,slot,icon in [('영상 여러 개 추가',self.choose_batch_files,QStyle.StandardPixmap.SP_FileIcon),
                               ('밴드 파일 묶기',self.choose_files,QStyle.StandardPixmap.SP_FileIcon),
                               ('CoastSat 폴더',self.choose_coastsat,QStyle.StandardPixmap.SP_DirOpenIcon),
                               ('GEE 로그인·수집',self.google_dialog,QStyle.StandardPixmap.SP_ComputerIcon)]:
            action = QAction(self.style().standardIcon(icon),text,self)
            action.triggered.connect(slot); menu.addAction(action); import_menu.addAction(action); self.import_actions.append(action)
        toolbar.addSeparator()
        toolbar.addAction('지역·촬영 범위 점검',self.show_site_review)
        self.history_action = self.log_dock.toggleViewAction(); self.history_action.setText('처리 기록 보기'); toolbar.addAction(self.history_action)
        toolbar.addAction('사용 안내',self.show_help)
        menu.addSeparator(); close_action = menu.addAction('종료'); close_action.triggered.connect(self.close)
        view = self.menuBar().addMenu('보기')
        for dock in (self.left_dock,self.right_dock,self.log_dock):
            view.addAction(dock.toggleViewAction())
        fit = view.addAction('영상 전체 보기'); fit.triggered.connect(self.fit_images)
        help_menu = self.menuBar().addMenu('도움말')
        help_action = help_menu.addAction('사용 안내'); help_action.triggered.connect(self.show_help)
        settings_help = help_menu.addAction('전처리 설정 상세설명'); settings_help.triggered.connect(lambda: self.show_settings_help())
        about = help_menu.addAction('프로그램 정보'); about.triggered.connect(lambda:QMessageBox.information(self,'CoastSat Studio',
            '위성영상 전처리 · 독립 데스크톱 시험판\nCoastSat: Kilian Vos 및 기여자 · GPL-3.0\n화면: Qt / PySide6 · 전처리: GDAL / CoastSat\n실제 사용자 영상과 Google 수집은 추가 검증이 필요합니다.'))

    def show_site_review(self):
        from desktop.native_site_review import SiteReviewDialog
        dialog = SiteReviewDialog(self)
        dialog.exec()

    def dock(self,title,widget,area):
        dock = QDockWidget(title,self)
        dock.setWidget(widget)
        dock.setAllowedAreas(area)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.addDockWidget(area,dock)
        return dock

    def build_left(self):
        pane = QWidget(); layout = QVBoxLayout(pane)
        title = QLabel('내 영상'); title.setObjectName('sectionTitle'); layout.addWidget(title)
        self.count = QLabel('0개 장면'); self.count.setObjectName('muted'); layout.addWidget(self.count)
        self.scenes = QListWidget(); self.scenes.currentRowChanged.connect(self.select_scene); layout.addWidget(self.scenes)
        self.remove_button = QPushButton('선택 장면 제거'); self.remove_button.clicked.connect(self.remove_scene); layout.addWidget(self.remove_button)
        order = QHBoxLayout()
        self.move_up = QPushButton('위로'); self.move_up.clicked.connect(lambda:self.move_scene(-1)); order.addWidget(self.move_up)
        self.move_down = QPushButton('아래로'); self.move_down.clicked.connect(lambda:self.move_scene(1)); order.addWidget(self.move_down)
        layout.addLayout(order)
        note = QLabel('원본 파일은 변경하지 않습니다.\n장면별로 설정을 조절할 수 있습니다.'); note.setWordWrap(True); note.setObjectName('muted'); layout.addWidget(note)
        self.left_dock = self.dock('① 영상 목록',pane,Qt.DockWidgetArea.LeftDockWidgetArea)
        self.left_dock.setMinimumWidth(195); self.left_dock.setMaximumWidth(300)

    def build_center(self):
        pane = QWidget(); layout = QVBoxLayout(pane); layout.setContentsMargins(18,15,18,10); layout.setSpacing(12)
        self.workflow = QLabel('① 영상 불러오기   →   ② 입력 확인   →   ③ 미리보기   →   ④ 저장')
        self.workflow.setObjectName('badge'); self.workflow.setWordWrap(True); layout.addWidget(self.workflow)
        header = QHBoxLayout(); title = QLabel('미리보기로 비교하세요'); title.setObjectName('sectionTitle'); header.addWidget(title)
        header.addStretch(); badge = QLabel('전처리 작업 공간'); badge.setObjectName('badge'); header.addWidget(badge); layout.addLayout(header)
        self.notice = QLabel('파일을 추가하거나 CoastSat 폴더를 선택해 시작하세요.'); self.notice.setWordWrap(True); self.notice.setObjectName('notice'); layout.addWidget(self.notice)
        self.details = QLabel('구름 제외 · 밴드 정렬 · 선명화 · GeoTIFF 저장'); self.details.setWordWrap(True); self.details.setObjectName('muted'); layout.addWidget(self.details)
        self.stack = QStackedWidget()
        empty = QFrame(); empty.setObjectName('empty'); box = QVBoxLayout(empty); box.setAlignment(Qt.AlignmentFlag.AlignCenter); box.setSpacing(18)
        icon = QLabel('▧'); icon.setStyleSheet('font-size:64px;color:#9ab9c8;'); icon.setAlignment(Qt.AlignmentFlag.AlignCenter); box.addWidget(icon)
        prompt = QLabel('분석할 영상을 불러오세요'); prompt.setObjectName('sectionTitle'); prompt.setAlignment(Qt.AlignmentFlag.AlignCenter); box.addWidget(prompt); self.empty_title = prompt
        sub = QLabel('CoastSat 자료는 상단 메뉴에서 ‘CoastSat 폴더’를 선택하세요.'); sub.setObjectName('muted'); sub.setAlignment(Qt.AlignmentFlag.AlignCenter); sub.setWordWrap(True); box.addWidget(sub); self.empty_hint = sub
        button = QPushButton('영상 파일 불러오기'); button.setObjectName('primary'); button.clicked.connect(self.empty_action); self.empty_open = button; box.addWidget(button,0,Qt.AlignmentFlag.AlignHCenter)
        local = QLabel('내 파일은 로그인 없이 사용할 수 있습니다.'); local.setObjectName('muted'); local.setAlignment(Qt.AlignmentFlag.AlignCenter); box.addWidget(local)
        self.stack.addWidget(empty)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.before = ImageView(); self.after = ImageView()
        for label,view in [('원본 · 구름 제외 / 선명화 전',self.before),('전처리 결과',self.after)]:
            panel = QWidget(); side = QVBoxLayout(panel); side.setContentsMargins(0,0,0,0)
            heading = QLabel(label); heading.setStyleSheet('font-weight:700;padding:6px 2px;'); side.addWidget(heading); side.addWidget(view); split.addWidget(panel)
        self.before.changed.connect(self.sync_views); self.after.changed.connect(self.sync_views)
        self.stack.addWidget(split); layout.addWidget(self.stack,1)
        bar = QHBoxLayout()
        self.overlay = QCheckBox('구름·결측 색상 표시'); self.overlay.setChecked(True); self.overlay.toggled.connect(self.update_overlay); bar.addWidget(self.overlay)
        self.overlay.setToolTip(TIPS['overlay']); bar.addWidget(self.help_button('overlay'))
        self.opacity = QSlider(Qt.Orientation.Horizontal); self.opacity.setRange(0,100); self.opacity.setValue(45); self.opacity.setMaximumWidth(130); self.opacity.valueChanged.connect(self.update_overlay)
        self.opacity.setToolTip('마스크 색의 진하기입니다. 높을수록 진해지며 저장 결과에는 영향을 주지 않습니다.')
        bar.addWidget(self.opacity); self.opacity_label = QLabel('45%'); bar.addWidget(self.opacity_label); bar.addStretch()
        self.link_views = QCheckBox('이동·확대 연동'); self.link_views.setChecked(True); bar.addWidget(self.link_views)
        fit = QPushButton('전체 보기'); fit.clicked.connect(self.fit_images); bar.addWidget(fit)
        actual = QPushButton('1:1'); actual.clicked.connect(lambda:(self.before.actual_size(),self.after.actual_size())); bar.addWidget(actual)
        layout.addLayout(bar)
        legend = QLabel('● 주황: 구름   ● 회색: 결측   ● 보라: 미확인   ·   휠로 확대 / 드래그로 이동'); legend.setObjectName('muted'); layout.addWidget(legend)
        grid = QHBoxLayout(); self.metrics = []
        for caption in ['남는 픽셀','구름','구름 미확인','결측']:
            frame = QFrame(); frame.setObjectName('metric'); cell = QVBoxLayout(frame)
            cap = QLabel(caption); cap.setObjectName('muted'); val = QLabel('—'); val.setObjectName('metricValue'); cell.addWidget(cap); cell.addWidget(val); grid.addWidget(frame); self.metrics.append(val)
        layout.addLayout(grid)
        foot = QLabel('양쪽 화면은 동일한 명암 기준을 사용합니다. 원본 보기는 정렬·스케일을 적용한 비교용 영상입니다.'); foot.setWordWrap(True); foot.setObjectName('muted'); layout.addWidget(foot)
        self.setCentralWidget(pane)

    def empty_action(self):
        if self.selected_entry():
            self.request_inspection()
        else:
            self.choose_batch_files()

    def fold(self, layout, title):
        button = QToolButton(); button.setText(title); button.setCheckable(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(button)
        content = QWidget(); inner = QVBoxLayout(content); inner.setContentsMargins(0,4,0,4)
        content.hide(); layout.addWidget(content)
        def toggle(checked):
            content.setVisible(checked)
            button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        button.toggled.connect(toggle)
        return inner

    def build_right(self):
        panel = QWidget(); layout = QVBoxLayout(panel); layout.setContentsMargins(14,12,14,12); layout.setSpacing(9)
        def heading(text):
            label = QLabel(text); label.setStyleSheet('font-weight:700;font-size:15px;padding-top:7px;'); layout.addWidget(label)
        heading('② 입력 확인')
        self.selected_label = QLabel('선택된 영상 없음'); self.selected_label.setWordWrap(True); self.selected_label.setObjectName('muted'); layout.addWidget(self.selected_label)
        self.inspect_button = QPushButton('입력영상 확인'); self.inspect_button.clicked.connect(self.request_inspection); layout.addWidget(self.inspect_button)
        self.inspect_button.setToolTip('구름 제거 전 영상과 밴드·좌표·해상도·보정값을 확인합니다.')
        heading('③ 전처리 미리보기')
        self.threshold = QSpinBox(); self.threshold.setRange(0,100); self.threshold.setValue(40); self.threshold.setSuffix(' %'); self.threshold.valueChanged.connect(self.controls_changed)
        self.threshold.setToolTip(TIPS['threshold'])
        row = QHBoxLayout(); row.addWidget(QLabel('구름 확률 기준')); row.addWidget(self.threshold,1); row.addWidget(self.help_button('threshold')); layout.addLayout(row)
        self.probability_note = QLabel(); self.probability_note.setWordWrap(True); self.probability_note.setObjectName('muted'); layout.addWidget(self.probability_note)
        self.cloud = QCheckBox('구름 영역을 결과에서 제외'); self.cloud.setChecked(True); self.cloud.toggled.connect(self.controls_changed); self.cloud.setToolTip(TIPS['cloud'])
        row = QHBoxLayout(); row.addWidget(self.cloud,1); row.addWidget(self.help_button('cloud')); layout.addLayout(row)
        advanced = self.fold(layout,'추가 설정 · 선명화 / 밴드 / 일괄 적용')
        self.sand = QCheckBox('Landsat 모래·포말 오인 완화'); self.sand.toggled.connect(self.controls_changed)
        self.pan = QCheckBox('PAN 밴드로 선명화'); self.pan.toggled.connect(self.controls_changed)
        for widget,topic in [(self.sand,'sand'),(self.pan,'pan')]:
            widget.setToolTip(TIPS[topic]); row = QHBoxLayout(); row.addWidget(widget,1); row.addWidget(self.help_button(topic)); advanced.addLayout(row)
        self.edit_bands_button = QPushButton('밴드·보정 설정 수정'); self.edit_bands_button.clicked.connect(self.edit_bands); advanced.addWidget(self.edit_bands_button)
        self.apply_all_button = QPushButton('현재 설정을 전체 영상에 적용'); self.apply_all_button.clicked.connect(self.apply_all); advanced.addWidget(self.apply_all_button)
        help_button = QPushButton('설정 상세설명'); help_button.clicked.connect(lambda:self.show_settings_help()); advanced.addWidget(help_button)
        self.preview_button = QPushButton('미리보기 갱신'); self.preview_button.setObjectName('primary'); self.preview_button.clicked.connect(self.request_preview); layout.addWidget(self.preview_button)
        hint = QLabel('설정을 바꾼 뒤 눌러주세요.'); hint.setObjectName('muted'); layout.addWidget(hint)
        ai = self.fold(layout,'AI 구름·그림자 비교 · 시험 기능')
        ai_note = QLabel('기존 판정과 AI 판정을 비교합니다.\n일반 저장 결과에는 적용하지 않습니다.'); ai_note.setWordWrap(True); ai.addWidget(ai_note)
        self.ai_button = QPushButton('AI 비교 미리보기'); self.ai_button.clicked.connect(self.request_ai_preview); ai.addWidget(self.ai_button)
        self.ai_download_button = QPushButton('AI 모델 받기 · 약 58MB'); self.ai_download_button.clicked.connect(self.request_ai_download); ai.addWidget(self.ai_download_button)
        heading('④ 결과 저장')
        destination = self.fold(layout,'저장 위치 확인·변경')
        self.output = QLineEdit(str(self.root/'results')); self.output.setToolTip(self.output.text()); destination.addWidget(self.output)
        self.browse_output = QPushButton('저장 폴더 선택'); self.browse_output.clicked.connect(self.choose_output); destination.addWidget(self.browse_output)
        self.save_button = QPushButton('선택 영상 저장'); self.save_button.clicked.connect(lambda:self.request_export(False)); layout.addWidget(self.save_button)
        self.save_all_button = QPushButton('전체 영상 순서대로 저장'); self.save_all_button.clicked.connect(lambda:self.request_export(True)); layout.addWidget(self.save_all_button)
        note = QLabel('GeoTIFF · 마스크 · 미리보기 · 처리 기록'); note.setWordWrap(True); note.setObjectName('muted'); layout.addWidget(note)
        self.stop_button = QPushButton('현재 작업 중지'); self.stop_button.setObjectName('stop'); self.stop_button.clicked.connect(self.cancel_job); layout.addWidget(self.stop_button)
        layout.addStretch()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(panel)
        self.right_dock = self.dock('단계별 작업',scroll,Qt.DockWidgetArea.RightDockWidgetArea)
        self.right_dock.setMinimumWidth(315); self.right_dock.setMaximumWidth(370)

    def build_logs(self):
        tabs = QTabWidget(); self.log_tabs = tabs
        self.queue_rows = []; self.batch_report = None
        pane = QWidget(); box = QVBoxLayout(pane)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.queue_table = QTableWidget(0,3); self.queue_table.setHorizontalHeaderLabels(['장면','상태','현재 / 마지막 단계'])
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.queue_table.itemSelectionChanged.connect(self.show_queue_details)
        self.stage_details = QPlainTextEdit(); self.stage_details.setReadOnly(True)
        self.stage_details.setPlaceholderText('미리보기 또는 순차 전처리를 실행하면 실제 처리 단계·수치·오류가 여기에 표시됩니다.')
        split.addWidget(self.queue_table); split.addWidget(self.stage_details); box.addWidget(split)
        buttons = QHBoxLayout()
        expand = QPushButton('단계별 상세 크게 보기'); expand.clicked.connect(self.expand_stage_details); buttons.addWidget(expand)
        output = QPushButton('선택 장면 결과 폴더'); output.clicked.connect(self.open_queue_result); buttons.addWidget(output)
        report = QPushButton('전체 처리 기록 폴더'); report.clicked.connect(self.open_queue_report); buttons.addWidget(report)
        box.addLayout(buttons); tabs.addTab(pane,'전처리 상세 · 순차 진행')
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2500)
        self.log.appendPlainText('CoastSat Studio 준비 완료. 로컬 파일 처리는 Google 로그인이 필요하지 않습니다.')
        self.results = QListWidget(); self.results.itemDoubleClicked.connect(lambda item:QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.ItemDataRole.UserRole))))
        tabs.addTab(self.log,'진행 로그'); tabs.addTab(self.results,'저장 결과 · 더블클릭으로 폴더 열기')
        self.log_dock = self.dock('작업 기록',tabs,Qt.DockWidgetArea.BottomDockWidgetArea)
        self.log_dock.setMinimumHeight(110)

    def update_queue(self, state):
        if 'queue' not in state: return
        self.batch_report = state.get('batch_report')
        if self.queue_rows == state['queue']: return
        selected = self.queue_table.currentRow()
        self.queue_rows = copy.deepcopy(state['queue'])
        self.queue_table.blockSignals(True); self.queue_table.setRowCount(len(self.queue_rows))
        for i,row in enumerate(self.queue_rows):
            for j,text in enumerate([row['name'],row['state'],row.get('stage','')]):
                cell = QTableWidgetItem(text); cell.setToolTip(text); self.queue_table.setItem(i,j,cell)
        if self.queue_rows:
            self.queue_table.selectRow(min(max(0,selected),len(self.queue_rows)-1))
        self.queue_table.blockSignals(False); self.show_queue_details()

    def show_queue_details(self):
        index = self.queue_table.currentRow()
        if not 0 <= index < len(self.queue_rows): return
        row = self.queue_rows[index]
        summary = f'최종 유효 픽셀 {row["valid_percent"]:.2f}%' if 'valid_percent' in row else row.get('message','')
        lines = [f'{row["name"]} · {row["state"]}',summary,'']
        for event in row.get('events',[]):
            lines.extend([f'[{event["state"]}] {event["stage"]}',event['message'],''])
        scroll = self.stage_details.verticalScrollBar(); old = scroll.value(); at_end = old == scroll.maximum()
        self.stage_details.setPlainText('\n'.join(lines)); scroll.setValue(scroll.maximum() if at_end else old)
        if hasattr(self,'expanded_details'):
            expanded_scroll = self.expanded_details.verticalScrollBar(); previous = expanded_scroll.value()
            self.expanded_details.setPlainText('\n'.join(lines)); expanded_scroll.setValue(previous)

    def expand_stage_details(self):
        if not hasattr(self,'stage_window'):
            self.stage_window = QDialog(self); self.stage_window.setWindowTitle('선택 장면 · 전처리 단계별 상세')
            self.stage_window.resize(850,680)
            layout = QVBoxLayout(self.stage_window)
            layout.addWidget(QLabel('하단 순차 진행 목록에서 선택한 장면의 실제 처리 기록입니다.'))
            self.expanded_details = QPlainTextEdit(); self.expanded_details.setReadOnly(True)
            self.expanded_details.setStyleSheet('font-size:14px; padding:12px;'); layout.addWidget(self.expanded_details)
            close = QPushButton('닫기'); close.clicked.connect(self.stage_window.close); layout.addWidget(close)
        self.show_queue_details(); self.stage_window.show(); self.stage_window.raise_()

    def open_queue_result(self):
        index = self.queue_table.currentRow()
        if 0 <= index < len(self.queue_rows):
            row = self.queue_rows[index]
            if row['state'] == '완료' and row.get('folder'):
                QDesktopServices.openUrl(QUrl.fromLocalFile(row['folder']))

    def open_queue_report(self):
        if self.batch_report:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.batch_report).parent)))

    def choose_batch_files(self):
        if self.job: return
        paths,_ = QFileDialog.getOpenFileNames(self,'각각의 촬영 장면인 위성영상 여러 개 선택','','위성영상 (*.tif *.tiff *.TIF *.TIFF *.jp2 *.JP2)')
        if paths:
            dialog = BatchImportDialog(paths,self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.add_scenes(dialog.scenes)

    def move_scene(self, direction):
        if self.job: return
        old = self.scenes.currentRow(); new = old + direction
        if old < 0 or not 0 <= new < len(self.entries): return
        self.scenes.blockSignals(True)
        self.entries.insert(new,self.entries.pop(old))
        self.scenes.insertItem(new,self.scenes.takeItem(old)); self.scenes.setCurrentRow(new)
        self.scenes.blockSignals(False); self.select_scene(new)

    def selected_entry(self):
        row = self.scenes.currentRow()
        return self.entries[row] if 0 <= row < len(self.entries) else None

    def configured(self,entry):
        scene = copy.deepcopy(entry['base'])
        scene.update(cloud_threshold=entry['settings']['threshold'],apply_cloud_mask=entry['settings']['cloud'],cloud_mask_issue=entry['settings']['sand'])
        if not entry['settings']['pan']:
            scene.pop('pan',None)
        return scene

    def add_scenes(self,scenes):
        start = len(self.entries)
        for scene in scenes:
            self.entries.append({'base':copy.deepcopy(scene),'preview':None,'settings':{
                'threshold':scene.get('cloud_threshold',40),'cloud':scene.get('apply_cloud_mask',True),
                'sand':scene.get('cloud_mask_issue',False),'pan':bool(scene.get('pan'))}})
            item = QListWidgetItem(f"{scene['name']}\n{scene.get('satellite','OTHER')}  ·  {len(scene['bands'])}개 밴드")
            item.setToolTip(scene['bands'][0]['path']); self.scenes.addItem(item)
        self.count.setText(f'{len(self.entries)}개 장면')
        if scenes:
            self.scenes.setCurrentRow(start)
            self.log.appendPlainText(f'{len(scenes)}개 장면을 추가했습니다.')
        self.update_enabled()

    def choose_files(self):
        if self.job:
            return
        paths,_ = QFileDialog.getOpenFileNames(self,'같은 촬영 장면의 영상 파일 선택','','위성영상 (*.tif *.tiff *.TIF *.TIFF *.jp2 *.JP2)')
        if paths:
            try:
                dialog = BandDialog(paths,self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    self.add_scenes([dialog.scene])
            except Exception as error:
                self.show_error(error)

    def choose_coastsat(self):
        if self.job:
            return
        folder = QFileDialog.getExistingDirectory(self,'L5/L7/L8/L9/S2 폴더를 포함하는 사이트 폴더')
        if folder:
            self.load_coastsat(folder)

    def load_coastsat(self,folder):
        try:
            scenes = scan_coastsat(folder,pansharpen=True)
            # Keep available PAN references while defaulting its use to off.
            self.add_scenes(scenes)
            for entry in self.entries[-len(scenes):]:
                entry['settings']['pan'] = False
            self.select_scene(self.scenes.currentRow())
        except Exception as error:
            self.show_error(error)

    def remove_scene(self):
        if self.job:
            return
        row = self.scenes.currentRow()
        if row >= 0:
            self.scenes.blockSignals(True)
            self.entries.pop(row); self.scenes.takeItem(row)
            self.scenes.blockSignals(False)
            self.count.setText(f'{len(self.entries)}개 장면'); self.select_scene(self.scenes.currentRow())

    def edit_bands(self):
        entry = self.selected_entry()
        if not entry or self.job or entry['base'].get('coastsat'):
            return
        base = entry['base']
        paths = list(dict.fromkeys(b['path'] for b in [*base['bands'],base.get('qa'),base.get('probability'),base.get('pan')] if b))
        try:
            dialog = BandDialog(paths,self,initial=base)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                entry['base'] = dialog.scene
                entry['settings']['pan'] = bool(dialog.scene.get('pan'))
                item = self.scenes.currentItem()
                item.setText(f"{dialog.scene['name']}\n{dialog.scene.get('satellite','OTHER')}  ·  {len(dialog.scene['bands'])}개 밴드")
                self.select_scene(self.scenes.currentRow())
        except Exception as error:
            self.show_error(error)

    def select_scene(self,row):
        entry = self.selected_entry()
        self._loading = True
        if entry:
            base,settings = entry['base'],entry['settings']
            self.selected_label.setText(f"{base['name']}\n{base.get('satellite','OTHER')} · {len(base['bands'])}개 밴드")
            self.threshold.setValue(settings['threshold']); self.cloud.setChecked(settings['cloud'])
            self.sand.setChecked(settings['sand']); self.pan.setChecked(settings['pan'])
        else:
            self.selected_label.setText('선택된 장면 없음')
        self._loading = False
        self.refresh_preview(); self.update_enabled()

    def controls_changed(self,*args):
        if self._loading:
            return
        entry = self.selected_entry()
        if entry:
            entry['settings'] = {'threshold':self.threshold.value(),'cloud':self.cloud.isChecked(),
                                 'sand':self.sand.isChecked(),'pan':self.pan.isChecked()}
            self.update_stale()

    def apply_all(self):
        current = self.selected_entry()
        if not current:
            return
        for entry in self.entries:
            entry['settings'] = copy.deepcopy(current['settings'])
            if not entry['base'].get('pan'):
                entry['settings']['pan'] = False
        self.log.appendPlainText('현재 설정을 전체 장면에 적용했습니다. 각 장면의 미리보기를 갱신해 확인하세요.')
        self.update_stale()

    def update_enabled(self):
        if not hasattr(self,'import_actions'):
            return
        idle,entry = self.job is None,self.selected_entry()
        self.import_button.setEnabled(idle)
        self.stop_button.setVisible(not idle)
        for action in self.import_actions:
            action.setEnabled(idle)
        self.scenes.setEnabled(idle); self.empty_open.setEnabled(idle)
        self.remove_button.setEnabled(idle and entry is not None)
        self.move_up.setEnabled(idle and self.scenes.currentRow() > 0)
        self.move_down.setEnabled(idle and 0 <= self.scenes.currentRow() < len(self.entries)-1)
        self.edit_bands_button.setEnabled(idle and entry is not None and not entry['base'].get('coastsat'))
        self.inspect_button.setEnabled(idle and entry is not None)
        from desktop.ai_models import runtime_available
        available = runtime_available()
        self.ai_button.setEnabled(idle and entry is not None)
        self.ai_download_button.setEnabled(idle and available)
        self.ai_button.setToolTip('모델 준비 후 로컬 CPU로 실행합니다.' if available else 'AI 실행 환경을 포함한 배포 버전이 필요합니다.')
        for button in (self.preview_button,self.save_button,self.apply_all_button):
            button.setEnabled(idle and entry is not None)
        self.save_all_button.setVisible(len(self.entries) > 1)
        self.save_all_button.setEnabled(idle and bool(self.entries)); self.stop_button.setEnabled(not idle)
        base = entry['base'] if entry else {}
        self.threshold.setEnabled(idle and bool(base.get('probability')))
        self.cloud.setEnabled(idle and bool(base.get('qa') or base.get('probability')))
        self.pan.setEnabled(idle and bool(base.get('pan')))
        self.sand.setEnabled(idle and base.get('qa',{}).get('kind') == 'landsat_qa_pixel')
        self.probability_note.setText('기준보다 높은 확률을 구름 후보로 판정합니다. 별도 품질정보가 있으면 그 판정도 합쳐집니다.' if base.get('probability') else '이 장면에는 구름 확률 정보가 없습니다. 확률 기준은 적용되지 않습니다.')

    def refresh_preview(self):
        entry = self.selected_entry(); preview = entry.get('preview') if entry else None
        self.empty_title.setText('입력한 영상을 먼저 확인하세요' if entry else '분석할 영상을 불러오세요')
        self.empty_hint.setText('오른쪽에서 설정을 조절하고 ‘미리보기 갱신’을 누르면 결과를 비교할 수 있습니다.' if entry else 'CoastSat 자료는 상단 메뉴에서 ‘CoastSat 폴더’를 선택하세요.')
        self.empty_open.setText('입력영상 확인' if entry else '영상 파일 불러오기')
        if preview:
            self.stack.setCurrentIndex(1)
            folder = Path(preview['folder'])
            self.before.set_images(folder/'before.png',folder/'mask.png'); self.after.set_images(folder/'after.png',folder/'mask.png')
            self.update_overlay()
            values = [f"{preview['valid_percent']:.1f}%",'정보 없음' if preview['cloud_percent'] is None else f"{preview['cloud_percent']:.1f}%",f"{preview['unknown_percent']:.1f}%",f"{preview['nodata_percent']:.1f}%"]
            for label,value in zip(self.metrics,values):
                label.setText(value)
            scene = preview['scene']; threshold = str(scene.get('cloud_threshold',40))+'%' if scene.get('probability') else '미사용'
            self.details.setText(f"표시된 결과: {scene['name']} · 구름 기준 {threshold} · 구름 제외 {'켜짐' if scene.get('apply_cloud_mask',True) else '꺼짐'} · 선명화 {'켜짐' if scene.get('pan') else '꺼짐'}")
        else:
            self.stack.setCurrentIndex(0)
            self.details.setText('장면을 선택하고 오른쪽의 미리보기 갱신을 누르세요.' if entry else '구름 제외 · 밴드 정렬 · 선명화 · GeoTIFF 저장')
            for label in self.metrics:
                label.setText('—')
        self.update_stale()

    def update_stale(self):
        entry = self.selected_entry(); preview = entry.get('preview') if entry else None
        stale = False
        if preview:
            try:
                stale = scene_signature(self.configured(entry)) != preview['signature']
            except (OSError,ValueError):
                stale = True
            text = '설정 또는 입력이 바뀌었습니다. 이전 결과이므로 미리보기를 갱신하세요.' if stale else '현재 설정과 일치하는 미리보기입니다.'
            if not preview['can_export']:
                text += ' 남는 픽셀이 없습니다. 설정을 조정하세요.'
        else:
            text = '아직 미리보기가 없습니다. 설정을 확인하고 미리보기 갱신을 누르세요.' if entry else '파일을 추가하거나 CoastSat 폴더를 선택해 시작하세요.'
        self.notice.setText(text)
        object_name = 'stale' if stale else 'notice'
        if self.notice.objectName() != object_name:
            self.notice.setObjectName(object_name); self.notice.style().unpolish(self.notice); self.notice.style().polish(self.notice)

    def update_overlay(self,*args):
        alpha = self.opacity.value()/100 if self.overlay.isChecked() else 0
        self.before.mask.setOpacity(alpha); self.after.mask.setOpacity(alpha)
        self.opacity_label.setText(f'{self.opacity.value()}%'); self.opacity.setEnabled(self.overlay.isChecked())

    def sync_views(self,view):
        if self.link_views.isChecked():
            (self.after if view is self.before else self.before).sync_from(view)

    def fit_images(self):
        self.before.fit_image(); self.after.fit_image()

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self,'결과 저장 폴더',self.output.text())
        if folder:
            self.output.setText(folder); self.output.setToolTip(folder)

    def google_dialog(self):
        if self.job:
            return
        if not hasattr(self, 'collection_dialog'):
            self.collection_dialog = DownloadDialog(self.root,self.project,self)
        dialog = self.collection_dialog
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.project = dialog.spec['project']; self.start_job(dialog.spec)

    def request_preview(self):
        entry = self.selected_entry()
        if entry and not self.job:
            try:
                scene = self.configured(entry)
                self.start_job({'mode':'preview','scene':scene,'signature':scene_signature(scene),'preview_context':'native'},entry)
            except Exception as error:
                self.show_error(error)

    def request_inspection(self):
        entry = self.selected_entry()
        if entry and not self.job:
            self.start_job({'mode':'inspect','scene':self.configured(entry)},entry)

    def request_ai_download(self):
        if not self.job:
            self.start_job({'mode':'ai_download'})

    def request_ai_preview(self):
        from desktop.ai_models import runtime_available, model_dir, verify_models
        entry = self.selected_entry()
        if not entry or self.job:
            return
        if not runtime_available():
            QMessageBox.information(self,'AI 실행 환경 필요','이 배포본에는 AI 실행 환경이 없습니다. AI 포함 버전을 사용해 주세요. 기본 전처리는 계속 사용할 수 있습니다.')
            return
        try:
            verify_models(model_dir())
        except ValueError as error:
            QMessageBox.information(self,'AI 모델 준비',str(error)+'\nAI 모델 받기를 누르면 공식 저장소에서 약 58MB를 받습니다. 영상은 업로드하지 않습니다.')
            return
        self.start_job({'mode':'ai_preview','scene':self.configured(entry)},entry)

    def request_export(self,all_scenes=False):
        if self.job:
            return
        entries = self.entries if all_scenes else [self.selected_entry()]
        entries = [e for e in entries if e]
        if not entries:
            return
        if not self.output.text().strip():
            self.show_error(ValueError('저장 폴더를 선택해 주세요.')); return
        self.start_job({'mode':'process','scenes':[self.configured(e) for e in entries],'output':self.output.text().strip()})

    def start_job(self,spec,entry=None):
        if self.job:
            return
        try:
            self.job = jobs.start(spec)
            if spec['mode'] in ('process','preview'):
                scenes = spec.get('scenes') or [spec['scene']]
                self.update_queue({'queue':[{'name':s['name'],'state':'대기','stage':'','message':'','events':[]} for s in scenes]})
                self.log_tabs.setCurrentIndex(0)
                # Detailed trace remains available without shrinking the preview.
            self._job_entry = entry; self._log_offset = 0; self._cancelled = False
            self.log.appendPlainText('\n작업 시작: '+{'inspect':'1단계 입력 점검','preview':'미리보기','process':'전처리 저장','authenticate':'Google 로그인','check':'연결 확인','download':'영상 수집'}.get(spec['mode'],spec['mode']))
            self.progress.setRange(0,0); self.statusBar().showMessage('처리 중 · 큰 영상은 시간이 걸릴 수 있습니다.')
            self.update_enabled()
        except Exception as error:
            self.show_error(error)

    def read_log(self):
        path = Path(self.job['folder'])/'job.log'
        if path.exists():
            with path.open(encoding='utf-8',errors='replace') as stream:
                stream.seek(self._log_offset); chunk = stream.read(32000); self._log_offset = stream.tell()
            if chunk.strip():
                self.log.appendPlainText(chunk.strip())

    def poll_job(self):
        if not self.job:
            return
        self.read_log()
        try:
            state = jobs.status(self.job)
        except (OSError,json.JSONDecodeError):
            return
        self.statusBar().showMessage(state.get('message','처리 중'))
        self.update_queue(state)
        progress = state.get('progress',0)
        if progress > 0:
            self.progress.setRange(0,100); self.progress.setValue(int(progress*100))
        if self.job['process'].poll() is None:
            return
        job,entry = self.job,self._job_entry
        self.job = None; self._job_entry = None; self.last_result = state
        self.progress.setRange(0,100)
        if self._cancelled:
            for row in state.get('queue',[]):
                if row['state'] in ('대기','처리 중'):
                    row['state'] = '중지'; row['message'] = '사용자가 작업을 중지했습니다.'
            state.update(state='cancelled',message='사용자가 작업을 중지했습니다.')
            if state.get('batch_report'):
                from desktop.worker import save
                save(Path(state['batch_report']),state)
                save(Path(job['folder'])/'status.json',state)
            self.update_queue(state)
            self.log.appendPlainText('사용자가 작업을 중지했습니다. 미완료 결과는 사용하지 마세요.')
            self.statusBar().showMessage('작업 중지'); self.progress.setValue(0)
        elif state['state'] == 'done':
            self.progress.setValue(100)
            if state.get('ai_models'):
                QMessageBox.information(self,'AI 모델 준비 완료','모델 다운로드와 파일 검증을 완료했습니다. AI 비교 미리보기를 실행할 수 있습니다.')
            if state.get('ai_comparison'):
                from desktop.native_ai import AIComparisonDialog
                if hasattr(self,'ai_dialog'):
                    self.ai_dialog.close(); self.ai_dialog.deleteLater()
                self.ai_dialog = AIComparisonDialog(state['ai_comparison'],self)
                self.ai_dialog.show()
                self.log.appendPlainText('AI 비교 완료: '+state['ai_comparison']['folder'])
            if state.get('input_review'):
                if hasattr(self,'input_review_dialog'):
                    self.input_review_dialog.close(); self.input_review_dialog.deleteLater()
                self.input_review_dialog = InputReviewDialog(state['input_review'],self)
                self.input_review_dialog.show()
                self.log.appendPlainText('입력 점검 완료: '+state['input_review']['folder'])
            if state.get('preview') and entry is not None:
                entry['preview'] = state['preview']; self.refresh_preview()
                for warning in state['preview']['warnings']:
                    self.log.appendPlainText('안내: '+warning)
            if state.get('site'):
                self.log.appendPlainText('수집 완료: '+state['site']); self.load_coastsat(state['site'])
            if job['mode'] in ('authenticate','check'):
                self.log.appendPlainText('연결 확인 완료. Google 수집 창을 다시 열어 영상을 수집하세요.')
            self.statusBar().showMessage('완료' if not state.get('failed') else '일부 장면 실패 · 로그를 확인하세요')
            self.log.appendPlainText('작업 완료')
        else:
            self.progress.setValue(0); self.log.appendPlainText('오류: '+state.get('message','작업 실패'))
            self.statusBar().showMessage('작업 실패 · 아래 진행 로그를 확인하세요')
        for result in state.get('results',[]):
            item = QListWidgetItem(result['folder']); item.setData(Qt.ItemDataRole.UserRole,result['folder']); self.results.addItem(item)
            self.log.appendPlainText('저장 완료: '+result['folder'])
            for warning in result.get('warnings',[]): self.log.appendPlainText('안내: '+warning)
        for failed in state.get('failed',[]):
            self.log.appendPlainText(f"실패 · {failed['name']}: {failed['error']}")
        if state.get('failed') or state.get('state') == 'error':
            self.log_dock.show()
        self.update_enabled()

    def cancel_job(self):
        if self.job and self.job['process'].poll() is None:
            self._cancelled = True; self.job['process'].terminate(); self.stop_button.setEnabled(False)

    def closeEvent(self,event):
        if self.job and self.job['process'].poll() is None:
            self.job['process'].terminate()
            try:
                self.job['process'].wait(timeout=3)
            except Exception:
                self.job['process'].kill()
        self.timer.stop(); self.stale_timer.stop(); event.accept()

    def show_error(self,error):
        self.log.appendPlainText('오류: '+str(error))
        QMessageBox.warning(self,'입력 확인',str(error))

    def show_help(self):
        QMessageBox.information(self,'사용 안내',
            '1. 파일 추가 또는 CoastSat 폴더로 장면을 불러옵니다.\n'
            '2. 일반 파일은 영상별 밴드를 직접 지정합니다.\n'
            '3. 오른쪽에서 설정을 조절하고 미리보기 갱신을 누릅니다.\n'
            '4. 휠로 확대하고 드래그로 이동하며 결과를 비교합니다.\n'
            '5. 저장 폴더를 정하고 선택 장면 또는 전체 장면을 저장합니다.\n\n'
            '구름 확률 기준은 s2cloudless 정보가 있을 때만 적용됩니다.\n'
            '구름 정보가 없는 픽셀은 보라색 미확인으로 표시합니다.\n'
            '현재 버전은 입력·출력 영상당 1,200만 픽셀까지 지원합니다.\n'
            'Google 로그인이 필요한 경우에만 기본 브라우저가 열립니다.')

    def help_button(self, topic):
        button = QPushButton('?')
        button.setFixedSize(28,28)
        button.setStyleSheet('padding:0; border-radius:14px; color:#007d88;')
        button.setToolTip(TIPS[topic] + '\n클릭하면 상세설명을 엽니다.')
        button.setAccessibleName({'threshold':'구름 확률 기준','cloud':'구름 픽셀 제외',
            'overlay':'마스크 겹쳐 보기','sand':'모래·포말 오인 완화','pan':'PAN 선명화'}[topic] + ' 도움말')
        button.setObjectName('help_' + topic)
        button.clicked.connect(lambda: self.show_settings_help(topic))
        return button

    def show_settings_help(self, topic='threshold'):
        if not hasattr(self, 'settings_help_dialog'):
            self.settings_help_dialog = SettingsHelpDialog(self)
        self.settings_help_dialog.open_topic(topic)
