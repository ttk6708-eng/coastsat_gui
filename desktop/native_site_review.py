"""Selectable regional inventory and map of raster footprints."""
import json
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QPointF
from PySide6.QtGui import QColor, QPen, QBrush, QPolygonF, QPainter
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,
    QFileDialog,QMessageBox,QComboBox,QTableWidget,QTableWidgetItem,QAbstractItemView,
    QHeaderView,QGraphicsView,QGraphicsScene,QSplitter,QWidget,QPlainTextEdit)
from desktop.site_review import inventory, inspect_row, compare


class HeaderWorker(QThread):
    ready=Signal(object)
    def __init__(self, rows, parent=None):
        super().__init__(parent); self.rows=rows
    def run(self):
        results=[]
        for row in self.rows:
            if self.isInterruptionRequested(): break
            try: results.append(inspect_row(row))
            except Exception as error: results.append(dict(row,headers={},issues=[*row['issues'],str(error)]))
        self.ready.emit(results)


class SiteReviewDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('지역·촬영 범위 점검 · CoastSat S2'); self.resize(1200,820)
        self.rows=[]; self.results={}; self.worker=None; self.references={}
        layout=QVBoxLayout(self)
        title=QLabel('① 지역 폴더 추가 → ② 장면 선택·정보 점검 → ③ 기준 영상과 범위 비교')
        title.setWordWrap(True); title.setObjectName('sectionTitle'); layout.addWidget(title)
        note=QLabel('파일 목록은 전체를 표시합니다. 선택한 장면만 영상 정보를 읽으며 픽셀 전처리와 원본 수정은 하지 않습니다.')
        note.setWordWrap(True); layout.addWidget(note)
        bar=QHBoxLayout()
        self.add=QPushButton('지역 폴더 추가'); self.add.clicked.connect(self.choose_folder);bar.addWidget(self.add)
        self.site=QComboBox();self.site.setMinimumWidth(250);self.site.currentIndexChanged.connect(self.refresh);bar.addWidget(self.site,1)
        self.sample=QPushButton('처음·중간·마지막 3장 선택');self.sample.clicked.connect(self.select_samples);bar.addWidget(self.sample)
        self.inspect=QPushButton('선택 장면 정보 점검');self.inspect.setObjectName('primary');self.inspect.clicked.connect(self.inspect_selected);bar.addWidget(self.inspect)
        layout.addLayout(bar)
        self.summary=QLabel('CoastSat의 S2 폴더를 포함하는 지역 폴더를 선택하세요.');layout.addWidget(self.summary)
        self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(['장면 / 촬영 시각','파일 구성','영상 크기','좌표계','점검 상태'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for col in range(1,5):self.table.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeMode.ResizeToContents)
        self.table.currentCellChanged.connect(self.show_comparison)
        split=QSplitter(Qt.Orientation.Vertical); split.addWidget(self.table)
        pane=QWidget(); box=QVBoxLayout(pane); reference_bar=QHBoxLayout()
        reference_bar.addWidget(QLabel('이 지역의 기준 영상'))
        self.reference=QComboBox();self.reference.currentIndexChanged.connect(self.reference_changed);reference_bar.addWidget(self.reference,1);box.addLayout(reference_bar)
        self.canvas=QGraphicsView();self.canvas.setScene(QGraphicsScene(self));self.canvas.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.canvas.setMinimumHeight(200);box.addWidget(self.canvas,1)
        legend=QLabel('파랑: 기준 영상  ·  주황: 선택 영상  ·  두 영역이 겹치는 곳이 공통 범위입니다. 좌표에 맞춘 외곽도이며 RGB 영상이 아닙니다.')
        legend.setWordWrap(True);box.addWidget(legend)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);self.detail.setMaximumHeight(125);box.addWidget(self.detail)
        split.addWidget(pane);split.setSizes([260,400]);layout.addWidget(split,1)
        bottom=QHBoxLayout(); save=QPushButton('점검 기록 저장');save.clicked.connect(self.save_report);bottom.addWidget(save)
        bottom.addStretch();close=QPushButton('닫기');close.clicked.connect(self.close);bottom.addWidget(close);layout.addLayout(bottom)

    def choose_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'S2 폴더가 포함된 지역 선택')
        if folder:
            try:self.add_folder(folder)
            except Exception as e:QMessageBox.warning(self,'지역 불러오기',str(e))

    def add_folder(self, folder):
        root=str(Path(folder).resolve())
        if self.site.findData(root)>=0:
            self.site.setCurrentIndex(self.site.findData(root));return
        rows=inventory(root);self.rows.extend(rows)
        self.site.addItem(Path(root).name+' · '+root,root);self.site.setCurrentIndex(self.site.count()-1)

    def current_rows(self):
        return [r for r in self.rows if r['site']==self.site.currentData()]

    def key(self,row):return (row['site'],row['name'])

    def refresh(self,*args):
        rows=self.current_rows();self.table.setRowCount(0)
        for r in rows:
            result=self.results.get(self.key(r)); issues=result['issues'] if result else r['issues']; h=result.get('headers',{}).get('ms') if result else None
            values=[r['name'],' / '.join(f'{k}:{len(r["files"].get(k,[]))}' for k in ('ms','swir','mask','meta')),
                    f'{h["width"]} × {h["height"]}' if h else '—',str(h['crs']) if h else '—',
                    '; '.join(issues) if issues else ('정보 점검 완료' if result else '미점검')]
            i=self.table.rowCount();self.table.insertRow(i)
            for j,v in enumerate(values):
                item=QTableWidgetItem(v);item.setToolTip(v);self.table.setItem(i,j,item)
        self.summary.setText(f'{len(rows)}개 장면 · 파일 구성 확인 필요 {sum(bool(r["issues"]) for r in rows)}개 · 영상 정보 점검 {sum(self.key(r) in self.results for r in rows)}개')
        self.reference.blockSignals(True);self.reference.clear()
        for r in rows:
            res=self.results.get(self.key(r))
            if res and res.get('headers',{}).get('ms'):self.reference.addItem(r['name'],r['name'])
        previous=self.references.get(self.site.currentData());index=self.reference.findData(previous)
        if index>=0:self.reference.setCurrentIndex(index)
        self.reference.blockSignals(False);self.reference_changed()
        if rows:self.table.setCurrentCell(0,0)

    def select_samples(self):
        n=self.table.rowCount();self.table.clearSelection()
        for i in sorted({0,n//2,n-1}) if n else []:
            for j in range(self.table.columnCount()):self.table.item(i,j).setSelected(True)

    def inspect_selected(self):
        if self.worker and self.worker.isRunning():return
        rows=self.current_rows();selected=[rows[i.row()] for i in self.table.selectionModel().selectedRows()]
        if not selected:
            QMessageBox.information(self,'장면 선택','점검할 행을 선택하세요. Ctrl 또는 Shift로 여러 장을 선택할 수 있습니다.');return
        for control in (self.add,self.site,self.inspect,self.sample):control.setEnabled(False)
        self.summary.setText(f'선택한 {len(selected)}개 장면의 영상 정보 점검 중…')
        self.worker=HeaderWorker(selected,self);self.worker.ready.connect(self.accept_results)
        self.worker.finished.connect(self.finished);self.worker.start()

    def accept_results(self,results):
        for row in results:self.results[self.key(row)]=row
        self.refresh()

    def finished(self):
        for control in (self.add,self.site,self.inspect,self.sample):control.setEnabled(True)

    def reference_changed(self,*args):
        self.references[self.site.currentData()]=self.reference.currentData()
        reference=self.results.get((self.site.currentData(),self.reference.currentData()))
        for index,row in enumerate(self.current_rows()):
            result=self.results.get(self.key(row))
            if not result or not reference:continue
            try:
                label=compare(reference,result)['status']
            except Exception as error:label=str(error)
            text='; '.join([*result['issues'],label])
            self.table.item(index,4).setText(text);self.table.item(index,4).setToolTip(text)
        self.show_comparison()

    def show_comparison(self,*args):
        self.canvas.scene().clear();self.detail.clear()
        rows=self.current_rows();index=self.table.currentRow()
        if not 0<=index<len(rows):return
        candidate=self.results.get(self.key(rows[index]));reference=self.results.get((self.site.currentData(),self.reference.currentData()))
        if not candidate or not reference:
            self.detail.setPlainText('선택한 장면과 기준 장면의 영상 정보를 먼저 점검하세요.');return
        try:
            result=compare(reference,candidate)
            # Local origin avoids loss of graphics precision for large map coordinates.
            origin=reference['headers']['ms']['points'][0]
            for row,color in ((reference,'#2474bc'),(candidate,'#df761c')):
                points=[QPointF(x-origin[0],-(y-origin[1])) for x,y in row['headers']['ms']['points']]
                pen=QPen(QColor(color));pen.setWidth(2);pen.setCosmetic(True)
                fill=QColor(color);fill.setAlpha(50)
                self.canvas.scene().addPolygon(QPolygonF(points),pen,QBrush(fill))
            self.fit()
            self.detail.setPlainText(f'{result["status"]}\n기준 영상 범위 중 겹치는 비율: {result["reference_coverage_percent"]:.2f}%\n선택 영상 범위 중 겹치는 비율: {result["candidate_coverage_percent"]:.2f}%\n'+result['note']+'\n'+('; '.join(candidate['issues']) or '파일 정보 점검에서 특이사항 없음. 실제 픽셀 품질을 보증하지 않습니다.'))
        except Exception as e:self.detail.setPlainText(str(e))

    def fit(self):
        rect=self.canvas.scene().itemsBoundingRect()
        if not rect.isEmpty():self.canvas.fitInView(rect.adjusted(-30,-30,30,30),Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'canvas'):self.fit()

    def save_report(self):
        path,_=QFileDialog.getSaveFileName(self,'점검 기록 저장','site-review.json','JSON (*.json)')
        if not path:return
        try:
            comparisons=[]
            for row in self.results.values():
                ref=self.results.get((row['site'],self.references.get(row['site'])))
                if ref:
                    try:comparisons.append({'site':row['site'],'name':row['name'],'reference':ref['name'],**compare(ref,row)})
                    except Exception as e:comparisons.append({'site':row['site'],'name':row['name'],'error':str(e)})
            payload={'note':'선택 영상의 헤더 정보만 점검. 픽셀 처리·위치 교정 미실행.', 'inventory':self.rows,'inspected':list(self.results.values()),'comparisons':comparisons}
            Path(path).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
            QMessageBox.information(self,'저장 완료',path)
        except Exception as e:QMessageBox.warning(self,'저장 실패',str(e))

    def reject(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'점검 중','선택 장면의 정보 점검이 끝난 뒤 닫아주세요.');return
        super().reject()

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():event.ignore();return
        super().closeEvent(event)
