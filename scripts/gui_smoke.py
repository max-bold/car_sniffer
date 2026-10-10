import argparse
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import time
from PySide6.QtWidgets import QApplication
from desktop.gui import MainWindow
from desktop import protocol as p

def main():
    arg=argparse.ArgumentParser();arg.add_argument('--seconds',type=float,default=10);arg.add_argument('--fps',type=int,default=12000);arg.add_argument('--port',default='DEMO');args=arg.parse_args()
    app=QApplication([]);app.setStyle('Fusion');window=MainWindow(demo=args.port=='DEMO',demo_fps=args.fps);window.show()
    if args.port!='DEMO':
        window.port.setCurrentIndex(window.port.findData(args.port));window.toggle_connection()
    def pump(seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:app.processEvents();time.sleep(.002)
    pump(.5);window.send(p.Command.CAPTURE,b'\1');pump(args.seconds)
    report={'port':args.port,'requested_demo_fps':args.fps,'duration_s':args.seconds,
            'rows':[panel.model.rowCount() for panel in window.can],
            'evicted_rows':[panel.model.evicted for panel in window.can],
            'analog_points':[len(points) for points in window.analog],
            'host_dropped_packets':window.worker.dropped,'sequence_gaps':window.worker.parser.gaps,
            'max_update_ms':round(window.max_update_ms,2),'updates':window.update_count,'worker_error':window.worker.error}
    Path('docs').mkdir(exist_ok=True);window.grab().save('docs/gui-'+args.port.lower()+'.png')
    window.send(p.Command.CAPTURE,b'\0');pump(.2);window.close()
    Path('docs/gui-'+args.port.lower()+'-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
