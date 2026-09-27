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
