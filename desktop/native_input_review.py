"""First extension checkpoint: inspect inputs before running cloud algorithms."""
from pathlib import Path
from PySide6.QtCore import Qt,QUrl
from PySide6.QtGui import QPixmap,QDesktopServices
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QSplitter,
    QPlainTextEdit,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QPushButton,QTabWidget,QWidget)
from desktop.native_widgets import ImageView


class InputReviewDialog(QDialog):
    def __init__(self, report, parent=None):
        super().__init__(parent)
        self.report = report
        self.setWindowTitle('1단계 · 입력 영상 점검과 미리보기')
        self.resize(1120,780); self.setMinimumSize(800,620)
        layout = QVBoxLayout(self)
        title = QLabel('1단계  입력 점검  →  선택 기능: AI 비교는 메인 화면에서 실행')
        title.setObjectName('sectionTitle'); title.setWordWrap(True); layout.addWidget(title)
        name = QLabel(report['name']); name.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(name)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs,1)
        overview = QWidget(); summary = QVBoxLayout(overview)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.preview = ImageView(); self.preview.mask.setVisible(False)
        if report.get('preview_path'):
            pixmap = QPixmap(report['preview_path']); self.preview.base.setPixmap(pixmap)
            self.preview.scene().setSceneRect(self.preview.base.boundingRect()); self.preview.fit_image()
        split.addWidget(self.preview)
        self.findings = QPlainTextEdit(); self.findings.setReadOnly(True)
        c = report['capabilities']
        lines = ['현재 지정된 입력',
            '· 기존 구름 판정: '+('구름 자료 지정됨 (아래 점검 결과 확인)' if c['basic_cloud'] else '정보 없음'),
            '· 구름 확률 조절: '+('확률 밴드 지정됨' if c['cloud_probability'] else '확률 자료 없음'),
            '· 근적외선(NIR): '+('지정됨' if c['nir_assigned'] else '미지정'),
            '· PAN 선명화: '+('선택됨 (지원 위성·밴드 확인 필요)' if c['pan_selected'] else '선택하지 않음'),
            '· AI 구름 판정: 다음 단계에서 선택형 비교 실행 (이 점검에는 미적용)','', '확인할 사항']
        lines += [f'• {message}' for message in report['issues']]
        if report.get('preview_error'): lines += ['', '미리보기 생성 불가: '+report['preview_error']]
        lines += ['', '이 점검은 밴드 선택의 과학적 타당성을 자동 보증하지 않습니다.',
                  '화면을 확인한 뒤 필요하면 메인 화면의 “밴드·보정 설정 수정”에서 수정하고 다시 점검하세요.']
        self.findings.setPlainText('\n'.join(lines)); split.addWidget(self.findings)
        split.setSizes([550,460]); summary.addWidget(split,1)
        note = QLabel(report.get('preview_note') or '입력을 수정한 뒤 다시 점검하면 미리보기를 생성할 수 있습니다.')
        note.setWordWrap(True); summary.addWidget(note)
        self.tabs.addTab(overview,'RGB 미리보기 · 점검 결과')
        self.band_details = QPlainTextEdit(); self.band_details.setReadOnly(True)
        self.tabs.addTab(self.band_details,'선택 밴드 상세')
        stat = QLabel(report['statistics_note']); stat.setWordWrap(True); layout.addWidget(stat)
        self.table = QTableWidget(len(report['bands']),7)
        self.table.setHorizontalHeaderLabels(['역할 / 파일 밴드','영상 크기','픽셀 크기','좌표 정렬','표본 결측','적용 scale / offset','상태'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMaximumHeight(220); self.table.setMinimumHeight(140)
        for i,row in enumerate(report['bands']):
            values = [f'{row["role"]} / {row["band"]}번']
            if row['error']:
                values += ['—']*5+[row['error']]
            else:
                values += [f'{row["width"]}×{row["height"]}',
                    f'{row["pixel_size"][0]:g} × {row["pixel_size"][1]:g} {row["unit"]}',row['alignment'],
                    f'{row["sampled_invalid_percent"]:.2f}%',f'{row["scale"]:g} / {row["offset"]:g}','읽기 완료']
            for j,text in enumerate(values):
                item = QTableWidgetItem(text); item.setToolTip(row['path'] if j == 0 else text); self.table.setItem(i,j,item)
        self.table.itemSelectionChanged.connect(self.select_band)
        self.table.itemDoubleClicked.connect(lambda:self.tabs.setCurrentIndex(1))
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        fit = QPushButton('영상 전체 보기'); fit.clicked.connect(self.preview.fit_image); actions.addWidget(fit)
        details = QPushButton('선택 밴드 상세 보기'); details.clicked.connect(lambda:self.tabs.setCurrentIndex(1)); actions.addWidget(details)
        folder = QPushButton('점검 기록 폴더'); folder.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(report['folder']))); actions.addWidget(folder)
        close = QPushButton('확인 후 닫기'); close.clicked.connect(self.close); actions.addWidget(close); layout.addLayout(actions)
        if report['bands']: self.table.selectRow(0)

    def select_band(self):
        index = self.table.currentRow()
        if index < 0: return
        row = self.report['bands'][index]
        def value_range(values):
            return '유효 표본 없음' if values is None else ' / '.join(f'{v:.8g}' for v in values)
        lines = [f'{row["role"]} · {row["band"]}번 밴드', row['path'],'']
        if row['error']: lines.append(row['error'])
        else:
            lines += [f'밴드 설명: {row["description"] or "없음"}',f'저장 자료형: {row["dtype"]}',
                f'좌표계: {row["crs"]}',f'영상 크기: {row["width"]} × {row["height"]}',
                f'좌표 변환: {row["transform"]}',f'정렬: {row["alignment"]}',
                f'NoData 지정값: {row["nodata"]}',f'표본 수: {row["sample_count"]:,}',
                f'표본 결측 비율: {row["sampled_invalid_percent"]:.2f}%',
                f'표본 원값 최솟값 / 최댓값: {value_range(row["raw_range"])}',
                f'보정 후 표본 최솟값 / 최댓값: {value_range(row["calibrated_range"])}',
                f'적용 계산식: 원값 × {row["scale"]} + {row["offset"]}',
                f'보정값 출처: {row["calibration_source"]}',
                f'처리 수준 메타데이터: {row["processing_level"]}',
                f'Processing baseline 메타데이터: {row["processing_baseline"]}',
                '', '표본 통계는 전체 영상 통계가 아닙니다. TOA/지표반사율 여부는 값의 범위만으로 확정할 수 없습니다.']
        self.band_details.setPlainText('\n'.join(lines))
