import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import struct
import time
from PySide6.QtWidgets import QApplication, QMessageBox
from desktop import protocol as p
from desktop.calibrate import CalibrationWindow


class Bench:
    connected=True
    error=''
    dropped=0
    def __init__(self,window):
        self.window=window;self.request=0;self.packets=[];self.sent=[];self.parser=p.Parser();self.ranges=[1]*8;self.coefficients={}
    def send(self,cmd,args=b''):
        self.request+=1;self.sent.append((cmd,args));now=self.request*1000000
        self.packets.append(p.Packet(p.Kind.RESPONSE,0,struct.pack('<IBBQ',self.request,cmd,0,now)))
        if cmd==p.Command.CHANNEL:self.ranges[args[0]]=args[2]
        if cmd==p.Command.RAW:
            ch,duration=struct.unpack('<BH',args);r=self.ranges[ch]
            raw=400+r*100+ch*2
            if self.window.stage:raw+=2000
            self.packets.append(p.Packet(p.Kind.RAW,0,b''.join(p.RAW.pack(now+i*625,ch,r,raw+i%2) for i in range(int(duration*1.6)))))
        if cmd==p.Command.LINEAR_PROFILE:
            ch,r,version,zero,gain=struct.unpack('<BBIff',args)
            self.coefficients[ch,r]=(1,version,gain,-zero*gain)
        if cmd==p.Command.READ_COEFFICIENTS:
            values=[]
            for ch in range(8):
                for r in (1,):
                    values.append(p.COEFFICIENTS.pack(self.request,ch,r,*self.coefficients.get((ch,r),(0,0,6.17*3.3/4095,-1.551))))
            self.packets.append(p.Packet(p.Kind.COEFFICIENTS,0,b''.join(values)))
        if cmd==p.Command.RESET_CALIBRATION:self.coefficients.clear()
        return self.request
    def drain(self):
        result=self.packets;self.packets=[];return result
    def close(self):pass


def test_two_step_wizard_and_acknowledged_flash_save(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    app=QApplication.instance() or QApplication([])
    w=CalibrationWindow();w.show();w.uid='test-board';w.boot=1;w.worker=Bench(w);w.ready=True;w.duration_ms=200
    def finish():
        deadline=time.monotonic()+15
        while w.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.002)
        assert not w.busy and w.ready,w.info.text()
    w.initialize();finish()
    assert len(w.current)==8
    assert abs(float(w.table.item(0,1).text())-6.17)<1e-6
    assert abs(float(w.table.item(0,2).text())+1.551)<1e-6
    w.show_stage()
    for stage,volts in enumerate((0,10.025)):
        assert w.stage==stage
        if stage:w.reference.setValue(volts)
        w.start_stage();finish()
    assert w.stage==2 and len(w.profiles)==8
    assert w.profiles[0].zero==500.5 and abs(w.profiles[0].gain-10.025/2000)<1e-9
    assert not list(tmp_path.rglob('*.json'))
    w.save_device();finish()
    assert sum(cmd==p.Command.LINEAR_PROFILE for cmd,_ in w.worker.sent)==8
    assert any(cmd==p.Command.SAVE_CALIBRATION for cmd,_ in w.worker.sent)
    assert w.worker.sent[-1][0]==p.Command.READ_COEFFICIENTS
    assert list(tmp_path.rglob('calibration-report-*.json'))
    assert all(v[0]==1 for v in w.current.values())
    assert abs(float(w.table.item(0,1).text())-10.025/2000*4095/3.3)<1e-6
    w.grab().save(str(tmp_path/'calibration-wizard.png'));w.close()


def test_wizard_does_not_save_rejected_profile(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    app=QApplication.instance() or QApplication([])
    w=CalibrationWindow();w.worker=Bench(w);w.ready=True;w.uid='test';w.boot=1
    w.command(p.Command.LINEAR_PROFILE,struct.pack('<BBIff',0,0,1,300,.002))
    request=w.worker.request
    w.worker.packets=[p.Packet(p.Kind.RESPONSE,0,struct.pack('<IBBQ',request,p.Command.LINEAR_PROFILE,1,0))]
    w.poll()
    assert not w.ready and not list(tmp_path.rglob('*.json'))
    assert all(cmd!=p.Command.SAVE_CALIBRATION for cmd,_ in w.worker.sent)
    w.close()


def test_factory_reset_confirmation_and_readback(monkeypatch):
    app=QApplication.instance() or QApplication([])
    w=CalibrationWindow();w.worker=Bench(w);w.ready=True;w.uid='test';w.boot=1
    w.worker.coefficients={(ch,r):(1,42,.003,-1.2) for ch in range(8) for r in (1,)}
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.No)
    w.reset_factory();assert not w.worker.sent and not w.busy
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.Yes)
    w.reset_factory()
    assert w.busy and not w.factory.isEnabled()
    end=time.monotonic()+3
    while w.busy and time.monotonic()<end:app.processEvents();time.sleep(.002)
    assert w.ready and not w.busy and w.stage==0
    assert len(w.current)==8 and all(v[:2]==(0,0) for v in w.current.values())
    assert abs(float(w.table.item(0,1).text())-6.17)<1e-6
    commands=[cmd for cmd,_ in w.worker.sent]
    assert commands[0:2]==[p.Command.BRIDGE,p.Command.CAPTURE]
    assert commands[-2:]==[p.Command.RESET_CALIBRATION,p.Command.READ_COEFFICIENTS]
    assert p.Command.SAVE_CALIBRATION not in commands and p.Command.LINEAR_PROFILE not in commands
    assert 'Перезапуск не требуется' in w.info.text()
    w.close()


def test_wizard_rejects_old_two_range_firmware():
    app=QApplication.instance() or QApplication([])
    w=CalibrationWindow();w.worker=Bench(w);w.uid='test';w.boot=1;w.busy=True
    completed=[];w.read_coefficients(lambda:completed.append(True))
    old=p.COEFFICIENTS.pack(w.read_request,0,0,0,0,1.47*3.3/4095,-1.551)
    w.worker.packets=[p.Packet(p.Kind.COEFFICIENTS,0,old)]
    w.poll()
    assert not w.ready and not completed
    assert 'Обновите прошивку' in w.info.text()
    w.close()
