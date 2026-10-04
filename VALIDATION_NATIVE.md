# 독립 데스크톱 버전 검증 — 2026-09-27

## 심화 1단계: 입력 점검

추가 시험 5개에서 파일 메타데이터 보정값·표본 결측 통계, 원본 파일 해시 유지,
없는 밴드의 진단 기록, 다른 격자의 정렬 필요 표시, 경위도 단위 표시,
구름 설정과 무관한 입력 RGB, 품질정보 원값 보존, 상세 화면 표시를 확인했습니다.
별도 작업 프로세스로 입력 점검을 실행하고 실제 Qt 위젯을 합성 영상으로 렌더링했습니다.
AI 구름 판정·대기보정·센서 조화·조위 보정은 이번 단계에 추가하지 않았습니다.

## 로컬 다중 영상 · 단계별 표시

기존 Qt/GEE/KML 시험 15개, 신규 순차 처리 시험 5개, 공통 과학 처리 시험 6개가 통과했습니다.
다중 영상의 명시적 밴드 지정·설정 복사·밴드 부족 거부, 순서 변경, 단계 기록 표시,
정상→실패→정상 장면의 순차 처리와 후속 진행, 중단 시 기존 결과 기록 보존을 검증했습니다.
로컬 실행 시험에서는 Earth Engine 모듈을 불러오면 실패하도록 해 로그인 경로와 분리됨을 확인했습니다.
실제 사용자 영상 대신 합성 데이터로 검증했습니다.

## GEE · KML 추가 검증

기존 Qt 시험 8개와 신규 수집 시험 7개가 통과했습니다. KML의 여러 영역 선택,
삼각형·내부 구멍 좌표 유지, 잘못된 XML·자기교차·비정상 좌표·점 전용 KML 거부,
큰 영역 수집 차단, 불러오기 실패 시 기존 선택 유지, 인증 성공·실패·취소를 확인했습니다.
공식 `ee.Authenticate(auth_mode='localhost:0', force=True)` 호출과 프로젝트 연결 확인은
모의 API로 검증했습니다. 실제 Google 계정 승인을 완료한 시험은 아닙니다.
Qt 위젯을 직접 렌더링해 로그인·KML 영역 윤곽 화면을 확인했습니다.

## 자동 시험

새 Qt 화면 시험 8개와 공통 전처리 시험 6개를 수행합니다.

- Streamlit과 pywebview가 설치되지 않은 독립 Python 환경에서 Qt 화면 구성
- 파일별 밴드 지정 및 중복 지정 거부
- 기존 밴드·스케일·오프셋을 다시 열어 수정 시 값 유지
- 미리보기 실행 → 구름 기준 변경 → 다시 비교 → 최종 저장까지 별도 프로세스로 실행
- 미리보기와 최종 마스크의 유효 픽셀 비율, 저장 PNG 일치
- 겹쳐 보기와 확대 연동은 처리 설정을 바꾸지 않음
- 장면별 설정 유지, 전체 적용, 목록에서 제거
- 앱을 닫을 때 진행 중인 작업 프로세스 종료
- Google 수집 입력 검증 (로그인·네트워크 요청 없이)
- 좌표계 보존, NoData, 해상도가 다른 마스크, 잘못된 밴드·비중첩 거부, QA60 비트, PAN 선명화

## 화면·실행 검사

Qt의 화면 밖 렌더링으로 실제 위젯 배치를 확인합니다. 한글 글꼴은 OFL 라이선스의
Noto Sans KR을 포함해 시스템 글꼴 구성에 의존하지 않게 했습니다.
새 실행 경로는 HTTP 서버·Streamlit·웹뷰를 사용하지 않습니다.

## 아직 남은 검증

- 사용자가 실제로 쓰는 위성영상의 밴드·구름 정보와 처리 품질 확인
- 실제 Google 계정 로그인과 Earth Engine 수집
- Python이 설치되지 않은 별도 PC의 일반 창 실행·파일 선택·전처리

따라서 현재는 시험 배포판입니다. 화면 캡처에 합성 시험 영상이 보이면 실제 위성영상이 아닙니다.

## 2026-09-27 UI simplification
- Native test suite: 25 passed, including preview threshold changes, overlay, sequential failure isolation, input review, and mocked GEE configuration.
- Synthetic three-scene preview and sequential export passed; 1440x900 and 1120x720 widget renders inspected. Small windows retain a scrollable settings panel.
- Windows transient status replacement conflicts now retry for at most 1.1 seconds; persistent failures still raise.
- Real satellite images and real Google authentication were not exercised in this change.

## 2026-09-27 AI comparison validation
- 31 native tests passed (including six new AI tests): band order, unmasked inference input,
  nodata exclusion, georeferencing, disagreement denominator, unknown QA, RGB fallback,
  output validation, input changes, model corruption and display-only opacity.
- Real OmniCloudMask 1.7.1 / v4 two-model CPU inference passed on synthetic 192x256 imagery through
  the actual worker and Qt comparison window. A second inference passed with socket.connect blocked.
- Synthetic imagery only: no real coastline accuracy improvement is claimed. Google login was not exercised.
- Model files: 57,805,992 bytes, pinned revision and verified SHA-256. No pickle model loading.
- Font source download URL and SHA-256 were verified. GitHub source omits the large font binary;
  download_font.py restores the exact redistributable font, and build_native.py calls it automatically.
- The AI distribution's EXE launch and packaged real-model worker were also checked separately;
  the bundled model path is used, not a developer cache. Native tests are repeated in that runtime.

## CoastSat zero-probability correction and provenance inspection
- Added five focused tests for embedded probability NoData=0, real spectral nodata,
  generic rasters and explicit masks, consistent/conflicting L2A metadata, and PASSED not being correction proof.
- Native suite: 36 tests; processing suite: six tests. Three selected real scenes only were inspected again.
- Two zero-probability samples retained more valid pixels without reducing true nodata;
  the control scene with no probability zeros retained identical cloud and valid percentages.
- Input TIFF hashes were unchanged. A correction-status Qt screenshot was inspected.
- Local input imagery, sample reports, machine-specific migration helper, runtimes and models are not published to GitHub.
# 지역·촬영 범위 점검 검증 (2026-09-27)

- 기존 기능을 포함한 native 자동 시험 41개 통과. 화면 상태 표시 변경 후 신규 시험 5개 재통과.

- 파일 목록 생성 시 래스터 미열기, 누락/중복/손상 입력, 서로 다른 지역 차단,
  동일/부분/포함/비중첩/회전 격자의 다각형 면적 계산, Qt 기준 선택을 검증합니다.
- 실제 영상은 맹방과 원평 각 3장만 헤더 점검했습니다. 목록은 각각 340/341개입니다.
- 원평 2022-12-30 표본은 2020-01-05 기준 범위의 38.89%와 겹칩니다.
  선택 영상 자체의 겹침 비율은 99.64%입니다. 구름·결측을 반영한 수치가 아닙니다.
- 표본 6개 장면의 24개 원본 파일은 점검 전후 SHA-256이 같았습니다.
- 실제 Qt 창을 두 크기로 렌더링하여 확인합니다. 전체 영상 일괄 전처리와 위치 보정은 수행하지 않았습니다.

# 구름·결측 단계별 품질 확인 (2026-09-28)

- Native 47개와 공통 전처리 6개, 총 53개 자동 시험 통과.
- 공통 영역 분모, 무겹침의 null 비율, 구름 제외 해제와 판정의 차이,
  품질정보 없음, 지역/좌표계 불일치, 기준 파일 변경 감지, 미리보기/저장 통계 일치를 검증했습니다.
- 맹방·원평 각 3장만 미리보기, 같은 표본의 확률 70/제외 해제 변형,
  한 장 최종 저장을 확인했습니다. 원본 24개 파일의 SHA-256은 변경되지 않았습니다.
- 실제 Qt 단계별 창을 렌더링하여 확인했습니다. 통계는 축소 이미지가 아닌 전체 처리 격자 기준입니다.

# 2026-10-05 · 단일 영상 해안선 후보

- Native 회귀 테스트 55개, 기존 전처리 테스트 6개 통과.
- 기본형·AI형 배포 폴더에서 새 해안선 테스트 각 8개 통과, 두 EXE 숨김 시작 점검 종료 코드 0.
  기본형의 독립 작업 프로세스로 실제 두 장면을 처리하고 선택 GeoJSON 저장까지 확인했습니다.
  테스트 전후 입력 6개 파일의 SHA-256이 동일했습니다. 세부 기록은 로컬 outputs/shoreline-validation.json에 있습니다.
- 새 테스트 8개: 구름으로 끊긴 선 분리, 분리 후 길이/결측 거리, 좌표 관례,
  같은 지수의 재현 가능한 임계값, 입력·설정 거부, 선택 저장/경위도 축/변경 입력 거부,
  UI 명시적 선택, 동봉 모델 가중치 순전파 대비 예측 일치.
- 전체 Qt 테스트에서 GDAL 임시 파일 핸들 해제가 지연되는 현상을 발견하여
  해당 테스트의 데이터셋 참조 해제와 GC 정리를 명시했습니다. 정리 오류를 무시하지 않습니다.
- 실제 자료는 맹방·원평에서 2020-01-05 장면 각 1장만 사용했습니다.
  맹방은 전체 유효 영역 Otsu 보조 방식, 원평은 모래·물 균형 Otsu 방식으로 후보가 나왔습니다.
  후보 길이는 각각 약 1122m, 4646m입니다. 해빈 길이나 위치 정확도 측정값이 아닙니다.
- 원평 미리보기에는 항만 경계도 포함됩니다. 현재 후보 단위 선택만 지원하고
  관심 해빈 부분 자르기와 기준 해안선 제한은 후속 과제입니다.
- 구름이 적은 두 장의 실행·표시 점검이며 현장 측량/조위와의 정확도 검증은 수행하지 않았습니다.
  모델 학습/실행 버전 차이 경고를 사용자에게 표시합니다.

# 2026-10-05 · 해빈 구간 다각형 선택

- Native 64개와 전처리 6개, 총 70개 자동 시험 통과.
- 기본형·AI형 배포본에서 해안선/영역 시험 각 17개 통과. 두 EXE 시작 점검 종료 코드 0.
- 신규 9개 시험: 경계 교점 보간·좌표 변환, 제외로 나뉜 선의 비연결,
  축소 미리보기 배율, 잘못된 다각형/빈 결과/점 접촉 거부, 연속 적용과 원래 후보 추적,
  잘린 GeoJSON·영역 이력 저장, 적용/되돌리기/복원, 적용 전 저장 차단과 Esc 취소,
  확대된 Qt 화면의 실제 클릭 좌표를 확인했습니다.
- 원평 2020-01-05의 기존 후보 한 장에 시험 다각형을 적용했습니다. 영상 전체 재처리는 하지 않았습니다.
  후보 길이는 약 4646m에서 2115m로 줄었으며 결과 화면과 선택 저장을 확인했습니다.
  이 영역은 UI 검증용이며 사용자가 승인한 최종 분석 범위를 뜻하지 않습니다.
- 원평 입력 3개 TIFF의 검증 전후 SHA-256이 동일했고 최초 후보 보고서도 수정하지 않았습니다.
- 수동으로 남긴 짧은 구간에는 추출 최소 길이를 다시 적용하지 않습니다.
  조위 보정·침식 판정·현장 기준 정확도 검증은 이번 기능에 포함되지 않습니다.

