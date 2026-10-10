import argparse
import sys
import json
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from .gui import MainWindow
from .protocol import Command

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--demo',action='store_true')
    parser.add_argument('--demo-fps',type=int,default=2000)
    parser.add_argument('--smoke-test',metavar='REPORT_JSON',help=argparse.SUPPRESS)
    args=parser.parse_args()
    app=QApplication(sys.argv[:1]);app.setStyle('Fusion')
    window=MainWindow(args.demo,args.demo_fps);window.show()
    if args.smoke_test:
        QTimer.singleShot(400,lambda:window.send(Command.CAPTURE,b'\1'))
        def finish():
            report={'frozen':bool(getattr(sys,'frozen',False)),'rows':[w.model.rowCount() for w in window.can],
                    'analog_points':[len(v) for v in window.analog],'error':window.worker.error if window.worker else 'no worker'}
            Path(args.smoke_test).write_text(json.dumps(report,indent=2),encoding='utf-8')
            window.close();app.quit()
        QTimer.singleShot(2200,finish)
    sys.exit(app.exec())

if __name__=='__main__':main()
