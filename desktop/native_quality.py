from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QSlider,QCheckBox,QPlainTextEdit,QPushButton
from desktop.native_widgets import ImageView


class QualityDialog(QDialog):
    def __init__(self,preview,parent=None):
        super().__init__(parent);self.preview=preview
        self.setWindowTitle('구름·결측 단계별 확인');self.resize(1000,850)
        layout=QVBoxLayout(self)
        title=QLabel(preview['scene']['name']);title.setTextFormat(Qt.TextFormat.PlainText);title.setWordWrap(True);layout.addWidget(title)
        note=QLabel('갱신한 미리보기의 고정 결과입니다. 설정 변경은 메인 화면에서 한 뒤 미리보기를 다시 갱신하세요.');note.setWordWrap(True);layout.addWidget(note)
        self.stage=QComboBox();self.stage.addItems(['① 처리 전 비교 영상','② 결측 영역','③ 구름·미확인 판정','④ 실제 제외 영역','⑤ 최종 처리 영상'])
        self.stage.currentIndexChanged.connect(self.show_stage);layout.addWidget(self.stage)
        self.view=ImageView();layout.addWidget(self.view,1)
        bar=QHBoxLayout();bar.addWidget(QLabel('색상 진하기'))
        self.opacity=QSlider(Qt.Orientation.Horizontal);self.opacity.setRange(0,100);self.opacity.setValue(55)
        self.opacity.valueChanged.connect(lambda v:self.view.mask.setOpacity(v/100));bar.addWidget(self.opacity)
        self.common=QCheckBox('공통 영역만 통계 보기');self.common.setEnabled(preview['quality']['common'] is not None)
        self.common.toggled.connect(self.show_stats);bar.addWidget(self.common);layout.addLayout(bar)
        legend=QLabel('회색: 결측 · 주황: 구름 · 보라: 미확인 · 파랑: 기준 범위 밖(참고 표시). 통계 선택은 영상 자체를 자르지 않습니다.')
        legend.setWordWrap(True);layout.addWidget(legend)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);self.detail.setMaximumHeight(200);layout.addWidget(self.detail)
        close=QPushButton('닫기');close.clicked.connect(self.close);layout.addWidget(close)
        self.show_stage();self.show_stats()

    def show_stage(self,*args):
        index=self.stage.currentIndex();root=Path(self.preview['folder'])
        overlays=['quality-empty.png','quality-nodata.png','mask.png','quality-excluded.png','quality-empty.png']
        self.view.set_images(root/('after.png' if index==4 else 'before.png'),root/overlays[index])
        self.view.mask.setOpacity(self.opacity.value()/100)
        self.show_stats()

    def show_stats(self,*args):
        quality=self.preview['quality'];stats=quality['common'] if self.common.isChecked() else quality['whole']
        def value(k):
            p=stats['percent'][k]
            return f'{stats["counts"][k]:,} 픽셀 / {p:.2f}%' if p is not None else '계산 불가 (공통 픽셀 없음)'
        scene=self.preview['scene']
        notes=['처리 전 비교 영상은 밴드 정렬·값 변환 후, 구름 제외·PAN 선명화 전입니다.',
               '결측에는 원래 NoData와 밴드 정렬·품질정보·PAN에서 확인한 결측이 포함됩니다.',
               '판정 색상은 제외 설정과 별개입니다. 미확인은 맑음으로 판정됐다는 뜻이 아닙니다.',
               '실제 제외된 픽셀만 표시합니다. 구름 제외를 껐다면 구름 판정 픽셀도 결과에 남습니다.',
               '현재 설정을 적용한 최종 영상입니다. 아래 통계는 축소 화면이 아닌 전체 처리 격자에서 계산합니다.']
        lines=[notes[self.stage.currentIndex()],f'구름 제외: {"켜짐" if scene.get("apply_cloud_mask",True) else "꺼짐"} · 확률 기준: {scene.get("cloud_threshold",40) if scene.get("probability") else "미사용"}',
               f'{"공통 영역" if self.common.isChecked() else "전체 영상"} 분모: {stats["pixels"]:,} 픽셀',
               '판정 — 결측 '+value('nodata')+' · 구름 '+value('cloud')+' · 미확인 '+value('unknown'),
               '실제 제외 — 구름 '+value('excluded_cloud')+' · 미확인 '+value('excluded_unknown'),
               '최종 남는 픽셀 '+value('valid'),quality['note']]
        if quality['reference']:lines.append('기준 파일: '+quality['reference'])
        lines.extend(self.preview['warnings']);self.detail.setPlainText('\n'.join(lines))
