"""Offline explanations of the preprocessing controls."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QComboBox, QTextBrowser, QDialogButtonBox


TOPICS = [
    ('threshold', '구름 확률 기준'), ('cloud', '구름 픽셀 제외'),
    ('overlay', '마스크 겹쳐 보기 · 투명도'), ('sand', 'Landsat 모래·포말 오인 완화'),
    ('pan', 'PAN 밴드로 선명화'), ('automatic', '자동 처리 · 구름 정보 없음'),
    ('workflow', '조절 순서 · 결과 저장'),
]

TIPS = {
    'threshold': '각 픽셀의 구름 판정 기준입니다. 낮추면 구름 후보가 늘고, 높이면 줄어듭니다. 구름 확률 정보가 있을 때만 적용됩니다.',
    'cloud': '켜면 구름으로 판정된 픽셀을 저장 결과에서 제외합니다. 구름 아래 지표를 복원하는 기능은 아닙니다.',
    'overlay': '주황은 구름, 회색은 결측, 보라는 구름 미확인입니다. 색 표시와 투명도는 저장할 영상값을 바꾸지 않습니다.',
    'sand': '밝은 모래나 포말을 구름으로 잘못 잡을 때 마스크의 작은 덩어리·가는 부분을 정리합니다. 실제 작은 구름도 놓칠 수 있습니다.',
    'pan': '지원 Landsat 영상의 고해상도 PAN 밴드를 이용해 세부 윤곽을 선명하게 합니다. 저장 결과의 픽셀값도 달라집니다.',
}

HELP_HTML = '''
<html><head><style>
body { color:#20374d; font-size:14px; line-height:1.6; }
h2 { color:#007d88; margin-top:28px; }
td,th { padding:9px; } th { background:#e4f4f3; }
</style></head><body>
<h1>전처리 설정 상세설명</h1>
<p><b>구름 확률 기준은 구름을 판단하는 설정이고, 구름 픽셀 제외는 그 부분을 결과에서 빼는 설정입니다.</b>
픽셀은 영상을 구성하는 작은 한 칸입니다. 위 목록에서 궁금한 항목을 선택하세요.</p>
<h2 id="threshold"><a name="threshold"></a>1. 구름 확률 기준</h2>
<p>영상에 포함된 구름 확률 정보를 이용해 어느 정도부터 구름으로 판단할지 정합니다.
예를 들어 기준이 <b>40%</b>라면 다음처럼 최초 판정합니다.</p>
<table border="1" cellspacing="0" cellpadding="7"><tr><th>픽셀의 구름 확률</th><th>최초 판정</th></tr>
<tr><td>20%</td><td>구름 후보 아님</td></tr><tr><td>40%</td><td>구름 후보 아님 (기준과 같음)</td></tr>
<tr><td>50% 또는 90%</td><td>구름 후보</td></tr></table>
<p>현재 처리는 기준을 <b>초과하는</b> 픽셀을 후보로 잡고 작은 점이나 가느다란 영역을 정리해 최종 마스크를 만듭니다.</p>
<ul><li><b>낮추면:</b> 더 많은 영역을 구름 후보로 잡습니다. 흐릿한 구름을 잡을 수 있지만 밝은 모래나 파도까지 잡힐 수 있습니다.</li>
<li><b>높이면:</b> 구름 후보가 줄어듭니다. 지표면은 더 남지만 실제 구름도 남을 수 있습니다.</li></ul>
<p><b>40%는 영상의 40%를 제거한다는 뜻이 아닙니다.</b> 각 픽셀의 판정 기준입니다.
기본값 40%가 모든 영상에 최적인 것도 아닙니다.</p>
<p>구름 확률 데이터(s2cloudless)가 있는 영상에서만 적용됩니다. 일반 GeoTIFF에 그 정보가 없으면 이 설정은 비활성화됩니다.
별도의 품질정보(QA)가 있으면 그 구름 판정도 합쳐집니다. 따라서 기준을 높여도 QA에서 구름으로 판정한 부분은 남을 수 있습니다.</p>
<h2 id="cloud"><a name="cloud"></a>2. 구름 픽셀 제외</h2>
<ul><li><b>켜짐:</b> 구름으로 판정된 부분을 분석에 사용하지 않도록 유효한 값 없음(NaN)으로 저장합니다.</li>
<li><b>꺼짐:</b> 구름 부분의 영상값도 결과에 남깁니다. 구름 판정 위치는 마스크로 계속 확인할 수 있습니다.</li></ul>
<p><b>구름 아래의 땅이나 바다를 복원하지 않습니다.</b> 구름에 가려진 부분을 결과에서 제외하는 기능입니다.
원본 파일은 바뀌지 않습니다. 원래 데이터가 없는 결측 부분은 이 설정을 꺼도 제외됩니다.</p>
<h2 id="overlay"><a name="overlay"></a>3. 마스크 겹쳐 보기 · 투명도</h2>
<p>마스크는 구름이나 결측 등으로 판정한 위치를 기록한 지도입니다. 영상 위에 색으로 겹쳐 판정 위치를 확인합니다.</p>
<ul><li><b>주황색:</b> 구름으로 판정된 곳</li><li><b>회색:</b> 영상 데이터가 없는 곳</li>
<li><b>보라색:</b> 구름 정보가 없어 판단하지 못한 곳 (구름이라는 뜻은 아님)</li></ul>
<p>슬라이더 값이 높을수록 색이 진해지고, 낮을수록 밑의 영상이 잘 보입니다.
<b>겹쳐 보기와 투명도는 화면 표시만 바꿉니다.</b> 저장되는 GeoTIFF의 영상값이나 구름 제외 여부는 바뀌지 않습니다.
저장 PNG에도 이 화면용 색 겹침은 들어가지 않습니다. 마스크는 별도 파일로 저장됩니다.</p>
<p>구름 픽셀 제외를 끄고 마스크만 켜면 영상값을 남긴 채 판정 위치를 비교할 수 있습니다.</p>
<h2 id="sand"><a name="sand"></a>4. Landsat 모래·포말 오인 완화</h2>
<p>밝은 모래사장이나 하얀 파도 거품이 구름으로 잘못 잡힐 때 사용합니다.
켜면 구름 마스크에서 작은 덩어리나 가느다란 부분을 더 강하게 정리합니다.</p>
<p><b>실제 작은 구름도 함께 놓칠 수 있습니다.</b> 해변이 주황색으로 과하게 표시될 때 켜고 전후를 비교하세요.
Landsat QA_PIXEL 품질정보를 사용하는 장면에서만 활성화됩니다.</p>
<h2 id="pan"><a name="pan"></a>5. PAN 밴드로 선명화</h2>
<p>별도로 제공되는 고해상도 흑백 영상인 PAN 밴드를 활용해 색 영상의 세부 윤곽을 더 선명하게 만듭니다.
현재 지원 대상은 PAN 밴드와 필요한 5개 다중분광 밴드를 갖춘 Landsat 7·8·9 장면입니다.</p>
<p>구름 제거와 별개이며, 단순 화면 확대와 달리 <b>저장 결과의 픽셀값도 달라집니다.</b>
PAN 자료가 없으면 사용할 수 없습니다. 선명화 전후의 경계와 색 표현을 비교하세요.</p>
<h2 id="automatic"><a name="automatic"></a>6. 자동 처리 · 구름 정보 없음</h2>
<ul><li><b>결측 처리:</b> 원래 데이터가 없는 곳은 항상 제외합니다.</li>
<li><b>밴드 정렬:</b> 밴드마다 픽셀 크기나 위치가 다르면 같은 위치를 가리키도록 맞춥니다.
기본적으로 파랑 밴드를 기준으로 하며, PAN 선명화 시에는 PAN 격자에 맞춥니다.</li></ul>
<p><b>구름 정보가 전혀 없는 영상:</b> 색 영상만 보고 자동으로 구름을 추정하지 않습니다.
구름 미확인으로 표시하고, 결측 외의 영상값은 남깁니다.</p>
<p><b>구름 정보가 일부만 있는 영상:</b> 구름 픽셀 제외가 켜져 있으면 구름 정보가 없는 부분도 제외합니다.
끄면 그 부분은 남지만, 결측 부분은 여전히 제외됩니다.</p>
<h2 id="workflow"><a name="workflow"></a>7. 조절 순서 · 결과 저장</h2>
<ol><li>영상을 불러오고 구름 확률 정보가 있는지 확인합니다.</li>
<li>기본값 40%에서 <b>미리보기 갱신</b>을 누릅니다.</li>
<li>마스크를 켜고 해변과 구름 경계를 확대해 확인합니다.</li>
<li>구름이 남으면 기준을 낮춰 보고, 정상적인 해변이 과하게 잡히면 높여 봅니다.
Landsat에서는 모래·포말 오인 완화도 비교할 수 있습니다.</li>
<li>설정을 바꿀 때마다 <b>미리보기 갱신</b>을 눌러 결과를 확인한 뒤 저장합니다.</li></ol>
<p>설정을 바꿔도 이전 미리보기는 자동으로 다시 계산되지 않습니다. 변경 안내가 표시되면 갱신하세요.
마스크 표시와 투명도는 즉시 반영되므로 갱신할 필요가 없습니다.</p>
<p><b>현재 설정을 전체 장면에 적용:</b> 선택 장면의 설정을 다른 장면에도 복사합니다.
각 장면의 자료에 따라 지원되는 기능만 적용됩니다. 모든 장면의 미리보기를 자동으로 만들지는 않습니다.</p>
<p><b>저장 결과:</b> 좌표정보를 유지한 GeoTIFF, 마스크, PNG 미리보기, 처리 기록입니다.
저장은 장면별 현재 설정으로 처리하므로 이전 미리보기와 설정이 다르면 저장 결과도 달라집니다.</p>
<p>화면의 남는 픽셀·구름·구름 미확인·결측 비율은 전체 픽셀 수 기준입니다.
일부 항목은 겹칠 수 있으므로 네 수치의 합이 반드시 100%인 것은 아닙니다.</p>
</body></html>
'''


class SettingsHelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('전처리 설정 상세설명')
        self.resize(780, 690)
        self.setMinimumSize(480, 380)
        layout = QVBoxLayout(self)
        self.topics = QComboBox()
        self.topics.setAccessibleName('설명할 설정 선택')
        for key, label in TOPICS:
            self.topics.addItem(label, key)
        layout.addWidget(self.topics)
        self.body = QTextBrowser()
        self.body.setHtml(HELP_HTML)
        self.body.setOpenExternalLinks(False)
        layout.addWidget(self.body)
        self.topics.currentIndexChanged.connect(lambda: self.body.scrollToAnchor(self.topics.currentData()))
        buttons = QDialogButtonBox()
        buttons.addButton('닫기', QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def open_topic(self, topic='threshold'):
        index = self.topics.findData(topic)
        self.topics.setCurrentIndex(max(0, index))
        self.show()
        self.body.scrollToAnchor(self.topics.currentData())
        self.raise_()
        self.activateWindow()
