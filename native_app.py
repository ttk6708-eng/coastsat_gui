"""Native Qt application entrypoint. Does not start any HTTP server."""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-test',action='store_true')
    parser.add_argument('--render',help='Offscreen UI render for layout verification')
    args = parser.parse_args()
    state = Path(os.environ.get('COASTSAT_STATE_DIR',str(Path.home()/'Documents'/'CoastSatDesktop')))
    state.mkdir(parents=True,exist_ok=True)
    os.environ['MPLCONFIGDIR'] = str(state/'matplotlib')
    os.environ['MPLBACKEND'] = 'Agg'
    os.environ['PYTHONUTF8'] = '1'
    if args.smoke_test or args.render:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    log = (state/'native-launcher.log').open('a',encoding='utf-8')
    sys.stdout = sys.stderr = log
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        from desktop.native_window import MainWindow
        from desktop.native_style import configure_application
        application = QApplication(sys.argv[:1])
        configure_application(application)
        window = MainWindow()
        window.show()
        result = {'healthy':True,'application':'Qt Widgets','streamlit_loaded':'streamlit' in sys.modules,
                  'webview_loaded':'webview' in sys.modules,'python':sys.executable}
        if args.smoke_test or args.render:
            def finish():
                try:
                    if args.render:
                        destination = Path(args.render).resolve()
                        destination.parent.mkdir(parents=True,exist_ok=True)
                        if not window.grab().save(str(destination)):
                            raise RuntimeError('화면 렌더링 저장 실패')
                    (state/'native-smoke-test.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                    window.close(); application.quit()
                except Exception:
                    traceback.print_exc(); application.exit(1)
            QTimer.singleShot(500,finish)
        return application.exec()
    except Exception as error:
        traceback.print_exc()
        if not args.smoke_test and not args.render:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,f'{error}\n\n실행 기록: {state / "native-launcher.log"}','CoastSat 실행 오류',16)
        return 1
    finally:
        log.flush()


if __name__ == '__main__':
    raise SystemExit(main())
