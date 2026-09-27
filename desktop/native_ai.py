"""Read-only comparison window for a fixed AI result snapshot."""
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QCheckBox, QTextEdit, QTabWidget, QWidget, QSplitter)
from desktop.native_widgets import ImageView


class AIComparisonDialog(QDialog):
    def __init__(self, report, parent=None):
        super().__init__(parent)
        self.report = report
        self.setWindowTitle('AI 구름·그림자 비교 · 시험 기능')
        self.resize(1180,820); self.setMinimumSize(820,620)
        layout = QVBoxLayout(self)
        title = QLabel(report['name']); title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True); title.setObjectName('sectionTitle'); layout.addWidget(title)
        note = QLabel('이번 실행 결과의 비교 화면입니다. 원본과 일반 전처리 저장 설정은 바뀌지 않습니다.\n주황: 두꺼운 구름  ·  노랑: 얇은 구름  ·  파랑: 그림자  ·  회색: AI 결측/미확인')
        note.setWordWrap(True); note.setObjectName('notice'); layout.addWidget(note)
        tabs = QTabWidget(); layout.addWidget(tabs,1)
        page = QWidget(); box = QVBoxLayout(page); split = QSplitter()
        self.before = ImageView(); self.after = ImageView()
        folder = Path(report['folder'])
        for text,view,mask in [('기존 품질정보 판정 · 보라색은 미확인',self.before,'existing.png'),
                               ('AI 판정 · OmniCloudMask v4',self.after,'ai.png')]:
            pane = QWidget(); side = QVBoxLayout(pane)
            label = QLabel(text); label.setWordWrap(True); side.addWidget(label); side.addWidget(view)
            view.set_images(folder/'rgb.png',folder/mask); split.addWidget(pane)
        self.before.changed.connect(lambda v:self.after.sync_from(v))
        self.after.changed.connect(lambda v:self.before.sync_from(v))
        box.addWidget(split,1)
        bar = QHBoxLayout(); self.overlay = QCheckBox('판정 색상 표시'); self.overlay.setChecked(True)
        self.opacity = QSlider(Qt.Orientation.Horizontal); self.opacity.setRange(0,100); self.opacity.setValue(45)
        self.opacity.setMaximumWidth(180); self.alpha = QLabel('45%')
        bar.addWidget(self.overlay); bar.addWidget(self.opacity); bar.addWidget(self.alpha); bar.addStretch()
        fit = QPushButton('전체 보기'); fit.clicked.connect(self.fit); bar.addWidget(fit); box.addLayout(bar)
        self.overlay.toggled.connect(self.update_overlay); self.opacity.valueChanged.connect(self.update_overlay)
        self.update_overlay()
        p=report['percentages']; mismatch=report['disagreement_percent']
        metrics = QLabel(f"AI 유효 영역 기준 · 맑음 {p['0']:.1f}% / 두꺼운 구름 {p['1']:.1f}% / 얇은 구름 {p['2']:.1f}% / 그림자 {p['3']:.1f}%\n"
                         + ('기존 정보 없음: 비교 불가' if mismatch is None else f'두 판정의 공통 유효 영역 불일치 {mismatch:.1f}% · 정확도 점수가 아닙니다.'))
        metrics.setWordWrap(True); box.addWidget(metrics); tabs.addTab(page,'나란히 비교')
        detail = QTextEdit(); detail.setReadOnly(True)
        detail.setPlainText('\n\n'.join(report['warnings']) +
            f"\n\n분석 시간: {report['elapsed_seconds']:.1f}초\nAI 유효 픽셀: {report['ai_valid_pixels']:,}\n비교 가능 픽셀: {report['comparable_pixels']:,}\n"
            '비율은 원래 처리 격자로 계산하며 화면만 축소합니다.\n'
            'AI 비교용 TIFF와 기록은 작업 폴더에 저장됩니다. 일반 전처리 결과에 AI 마스크를 적용하는 기능은 아직 없습니다.\n'
            '설정이나 입력을 바꾼 뒤에는 창을 닫고 AI 비교를 다시 실행하세요.\n\n'
            f"모델: OmniCloudMask 4 / 라이브러리 1.7.1 / CPU\n모델 버전 고정: {report['model_revision']}")
        tabs.addTab(detail,'해석과 주의사항')
        buttons=QHBoxLayout(); open_folder=QPushButton('비교 결과 폴더 열기')
        open_folder.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(report['folder'])))
        buttons.addWidget(open_folder); buttons.addStretch(); close=QPushButton('닫기'); close.clicked.connect(self.close)
        buttons.addWidget(close); layout.addLayout(buttons)

    def update_overlay(self,*args):
        value = self.opacity.value()/100 if self.overlay.isChecked() else 0
        self.before.mask.setOpacity(value); self.after.mask.setOpacity(value)
        self.alpha.setText(f'{self.opacity.value()}%'); self.opacity.setEnabled(self.overlay.isChecked())

    def fit(self):
        self.before.fit_image(); self.after.fit_image()
