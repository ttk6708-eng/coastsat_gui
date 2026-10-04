"""Explicit candidate review before shoreline export."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QSpinBox,QDialogButtonBox,QPushButton,QComboBox,QListWidget,QListWidgetItem,
    QPlainTextEdit,QFileDialog,QMessageBox)
from desktop.native_region_view import RegionImageView
from desktop.shoreline import DEFAULTS,draw_overlay,export_reviewed
from desktop.shoreline_region import clip_region


class ShorelineSettingsDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('해안선 후보 추출 · 1단계');self.resize(560,360)
        layout=QVBoxLayout(self)
        note=QLabel('현재 선택한 CoastSat Sentinel-2 장면 한 장을 처리합니다.\n메인 화면의 구름 확률 기준을 사용합니다. 구름 픽셀 제외를 켜 주세요.');note.setWordWrap(True);layout.addWidget(note)
        form=QFormLayout();layout.addLayout(form);self.fields={}
        for key,title,tip,maximum in [
            ('min_beach_area','최소 모래 영역 (m²)','이보다 작은 모래·물 덩어리는 분류 잡음으로 제외합니다.',1000000),
            ('min_length_sl','최소 후보선 길이 (m)','구름·결측 주변을 제외하고 남은 각 선의 길이입니다. 짧게 설정하면 작은 경계도 남습니다.',100000),
            ('dist_clouds','구름 주변 제외 거리 (m)','구름·판정 미확인 영역에서 이 거리보다 가까운 선을 제외합니다. 결측 주변은 별도로 30m 제외합니다.',10000)]:
            spin=QSpinBox();spin.setRange(0 if key=='dist_clouds' else 1,maximum);spin.setValue(DEFAULTS[key]);spin.setToolTip(tip)
            self.fields[key]=spin;form.addRow(title,spin)
            help_label=QLabel(tip);help_label.setWordWrap(True);form.addRow(help_label)
        warning=QLabel('시험 기능: 해안선 후보를 눈으로 확인한 뒤 필요한 선만 저장합니다.\n조위 보정·침식·퇴적 판정은 아직 수행하지 않습니다.');warning.setWordWrap(True);layout.addWidget(warning)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('후보선 추출 시작')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def settings(self):
        return {key:spin.value() for key,spin in self.fields.items()}


class ShorelineReviewDialog(QDialog):
    def __init__(self,report,output,parent=None):
        super().__init__(parent);self.report=report;self.original_report=report;self.output=output;self.undo_stack=[]
        self.setWindowTitle('해안선 후보 확인 · 선택 후 저장');self.resize(1050,850)
        layout=QVBoxLayout(self)
        title=QLabel(report['scene']['name']);title.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(title)
        note=QLabel('분홍선과 숫자: 해안선 후보. 미선택 시 전체 후보를 표시합니다. 확대 확인 후 저장할 선을 체크하세요.');note.setWordWrap(True);layout.addWidget(note)
        self.stage=QComboBox();self.stage.addItems(['① 처리 전 영상','② 모래·포말·물 분류','③ 선택 후보선 겹쳐 보기']);layout.addWidget(self.stage)
        self.stage.currentIndexChanged.connect(self.refresh)
        tools=QHBoxLayout();layout.addLayout(tools)
        self.draw_button=QPushButton('해빈 영역 그리기');self.draw_button.clicked.connect(self.begin_region);tools.addWidget(self.draw_button)
        self.point_undo=QPushButton('마지막 점 취소');self.point_undo.clicked.connect(lambda:self.view.undo_point());tools.addWidget(self.point_undo)
        self.keep_button=QPushButton('영역 안만 남기기');self.keep_button.clicked.connect(lambda:self.apply_region('keep'));tools.addWidget(self.keep_button)
        self.exclude_button=QPushButton('영역 안 제외');self.exclude_button.clicked.connect(lambda:self.apply_region('exclude'));tools.addWidget(self.exclude_button)
        self.cancel_region=QPushButton('그리기 취소');self.cancel_region.clicked.connect(self.cancel_drawing);tools.addWidget(self.cancel_region)
        history=QHBoxLayout();layout.addLayout(history)
        self.undo_button=QPushButton('영역 적용 되돌리기');self.undo_button.clicked.connect(self.undo_region);history.addWidget(self.undo_button)
        self.reset_button=QPushButton('전체 후보 복원');self.reset_button.clicked.connect(self.reset_regions);history.addWidget(self.reset_button)
        self.region_status=QLabel();self.region_status.setWordWrap(True);history.addWidget(self.region_status,1)
        self.region_help=QLabel('전체 후보 중 해빈을 둘러싸도록 점을 3개 이상 찍고 적용하세요. 초록 윤곽은 최근 영역이며, 저장 대상은 분홍선입니다.');self.region_help.setWordWrap(True);layout.addWidget(self.region_help)
        row=QHBoxLayout();layout.addLayout(row,1);self.view=RegionImageView();row.addWidget(self.view,1)
        self.view.points_changed.connect(self.update_region_controls)
        self.candidates=QListWidget();self.candidates.setMaximumWidth(225);row.addWidget(self.candidates)
        self.populate_candidates([])
        self.candidates.itemChanged.connect(self.refresh)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);self.detail.setMaximumHeight(130)
        layout.addWidget(self.detail)
        bar=QHBoxLayout();layout.addLayout(bar)
        self.save_button=QPushButton('선택한 후보선 확인·저장');self.save_button.clicked.connect(self.save);bar.addWidget(self.save_button)
        close=QPushButton('닫기');close.clicked.connect(self.close);bar.addWidget(close)
        self.stage.setCurrentIndex(2);self.refresh()

    def populate_candidates(self,selected):
        self.candidates.blockSignals(True);self.candidates.clear()
        for segment in self.report['segments']:
            item=QListWidgetItem(f"후보 {segment['id']} · {segment['length_m']:.0f} m")
            item.setData(Qt.ItemDataRole.UserRole,segment['id']);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if segment['id'] in selected else Qt.CheckState.Unchecked)
            self.candidates.addItem(item)
        self.candidates.blockSignals(False)

    def begin_region(self):
        self.stage.setCurrentIndex(2)
        self.view.set_drawing(True,clear=True)

    def restore_polygon(self):
        edits=self.report.get('region_edits',[])
        self.view.set_points(edits[-1]['preview_vertices'] if edits else [])

    def cancel_drawing(self):
        self.view.set_drawing(False)
        self.restore_polygon()

    def update_region_controls(self):
        if not hasattr(self,'save_button'):return
        drawing=self.view.drawing;count=len(self.view.points)
        self.draw_button.setEnabled(not drawing)
        self.point_undo.setEnabled(drawing and count>0)
        self.keep_button.setEnabled(drawing and count>=3)
        self.exclude_button.setEnabled(drawing and count>=3)
        self.cancel_region.setEnabled(drawing)
        self.undo_button.setEnabled(not drawing and bool(self.undo_stack))
        self.reset_button.setEnabled(not drawing and bool(self.undo_stack))
        self.save_button.setEnabled(not drawing and bool(self.selected()))
        edits=len(self.report.get('region_edits',[]))
        length=sum(s['length_m'] for s in self.report['segments'])
        self.region_status.setText(f'영역 점 {count}개 · 적용 전(저장 불가)' if drawing else
                                  f'영역 적용 {edits}회 · 후보 {len(self.report["segments"])}개 · 총 {length:.0f}m')

    def apply_region(self,mode):
        if not self.view.drawing:return
        try:
            result=clip_region(self.report,self.view.points,mode)
        except (ValueError,KeyError) as error:
            QMessageBox.warning(self,'영역 확인',str(error));return
        self.undo_stack.append((self.report,self.selected()))
        self.report=result
        self.populate_candidates([s['id'] for s in result['segments']])
        self.view.set_drawing(False)
        self.stage.setCurrentIndex(2);self.refresh()

    def undo_region(self):
        if not self.undo_stack:return
        self.report,selected=self.undo_stack.pop()
        self.populate_candidates(selected);self.restore_polygon();self.refresh()

    def reset_regions(self):
        self.report=self.original_report;self.undo_stack=[]
        self.populate_candidates([]);self.restore_polygon();self.refresh()

    def reject(self):
        if self.view.drawing:
            self.cancel_drawing()
        else:
            super().reject()

    def selected(self):
        return [self.candidates.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.candidates.count())
                if self.candidates.item(i).checkState()==Qt.CheckState.Checked]

    def refresh(self,*args):
        if not hasattr(self,'save_button'):return
        selected=self.selected();root=Path(self.report['folder'])
        # Show every numbered candidate until a selection is made, then only selected lines.
        draw_overlay(self.report,selected or [s['id'] for s in self.report['segments']],root/'review-overlay.png')
        overlay=['empty.png','classes.png','review-overlay.png'][self.stage.currentIndex()]
        self.view.set_images(root/'original.png',root/overlay)
        self.detail.setPlainText('분류색: 노랑=모래 / 옅은 하늘색=포말 / 파랑=물 / 회색=제외\n'+
            f"후보 {len(self.report['segments'])}개 · 임계값 {self.report['threshold']:.4f}\n"+
            ('영역 선택 후에는 짧은 구간도 유지합니다. 전체 후보에 적용되며 남은 후보는 체크됩니다.\n' if self.report.get('region_edits') else '')+
            '\n'.join(self.report['warnings']))
        self.update_region_controls()

    def save(self):
        if self.view.drawing:return
        folder=QFileDialog.getExistingDirectory(self,'해안선 저장 폴더 선택',self.output)
        if not folder:return
        try:
            result=export_reviewed(self.report,self.selected(),folder)
            QMessageBox.information(self,'저장 완료','선택한 후보선 GeoJSON·미리보기·처리 기록을 저장했습니다.\n'+result)
        except Exception as error:
            QMessageBox.warning(self,'저장 실패',str(error))
