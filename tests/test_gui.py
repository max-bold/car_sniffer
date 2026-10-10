import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
from PySide6 import QtCore
from PySide6.QtWidgets import QApplication
from desktop.gui import MainWindow, FrameModel, FrameFilter
from desktop import protocol as p

def pump(app,seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end:app.processEvents();time.sleep(.005)

def test_model_filters_and_tx():
    app=QApplication.instance() or QApplication([])
    model=FrameModel(capacity=3)
    def row(fid,ide=0,rtr=0):return {'frame_id':fid,'id':fid,'ide':ide,'rtr':rtr,'event':False,'cells':['']*10}
    model.append([row(1),row(2,1),row(3,0,1),row(4)])
    assert model.rowCount()==3 and model.evicted==1
    model.update_tx(3,1,1);assert model.data(model.index(1,8))=='1'
    proxy=FrameFilter();proxy.setSourceModel(model);proxy.set_ids('2-3');assert proxy.rowCount()==2
    proxy.ide=1;proxy.invalidate();assert proxy.rowCount()==1
    model.clear();assert proxy.rowCount()==0

def test_gui_demo_stop_clear_and_load(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    app=QApplication.instance() or QApplication([])
    w=MainWindow(demo=True,demo_fps=12000);w.show();pump(app,.4)
    w.send(p.Command.CAN_CONFIG,b'\0'+(500000).to_bytes(4,'little'))
    w.send(p.Command.CAN_CONFIG,b'\1'+(500000).to_bytes(4,'little'))
    w.send(p.Command.BRIDGE,b'\1');w.send(p.Command.CAPTURE,b'\1');pump(app,1.2)
    assert all(panel.model.rowCount()>1000 for panel in w.can)
    assert all(len(points)>=50 for points in w.analog)
    assert w.last_status[5:7]==(1,1)
    w.time_window.setValue(2.5);pump(app,.15)
    left,right=w.plots[0].viewRange()[0]
    assert abs(right-left-2.5)<.01
    # Mouse zoom on any linked channel changes the live window persistently.
    view=w.plots[3].getViewBox();view.setXRange(-1,0,padding=0)
    view.sigRangeChangedManually.emit([True,False]);pump(app,.15)
    assert abs(w.time_span-1)<.01
    left,right=w.plots[0].viewRange()[0];assert abs(right-left-1)<.01
    w.can[0].scroll.setChecked(False);w.can[1].scroll.setChecked(True)
    w.can[0].ids.setText('100-105');pump(app,.2)
    assert w.can[0].proxy.rowCount()<w.can[0].model.rowCount()
    w.send(p.Command.CAPTURE,b'\0');pump(app,.3)
    w.plots[2].setXRange(-5,-4,padding=0);pump(app,.15)
    left,right=w.plots[0].viewRange()[0]
    assert abs(left+5)<.01 and abs(right+4)<.01
    counts=[panel.model.rowCount() for panel in w.can];pump(app,.25)
    # Periodic diagnostics remain permitted after stop; external frame count is frozen.
    frame_counts=[sum(not r['event'] for r in panel.model.rows) for panel in w.can];pump(app,.2)
    assert frame_counts==[sum(not r['event'] for r in panel.model.rows) for panel in w.can]
    assert w.last_status[5]==1
    w.clear_results();assert all(panel.model.rowCount()==0 for panel in w.can)
    w.send(p.Command.CAPTURE,b'\1');pump(app,.3);assert all(panel.model.rowCount()>0 for panel in w.can)
    assert w.worker.dropped==0 and not w.worker.error
    w.grab().save(str(tmp_path/'gui.png'))
    w.close();pump(app,.05)
