import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import struct
import time
from PySide6.QtWidgets import QApplication
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
                for r in range(2):
                    values.append(p.COEFFICIENTS.pack(self.request,ch,r,*self.coefficients.get((ch,r),(0,0,(1.47,6.17)[r]*3.3/4095,-1.551))))
            self.packets.append(p.Packet(p.Kind.COEFFICIENTS,0,b''.join(values)))
        return self.request
    def drain(self):
        result=self.packets;self.packets=[];return result
    def close(self):pass


def test_three_step_wizard_and_acknowledged_flash_save(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    app=QApplication.instance() or QApplication([])
    w=CalibrationWindow();w.show();w.uid='test-board';w.boot=1;w.worker=Bench(w);w.ready=True;w.duration_ms=200
    def finish():
        deadline=time.monotonic()+15
        while w.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.002)
        assert not w.busy and w.ready,w.info.text()
    w.initialize();finish()
    assert len(w.current)==16
    assert abs(float(w.table.item(0,1).text())-1.47)<1e-6
    assert abs(float(w.table.item(0,2).text())+1.551)<1e-6
    w.show_stage()
    for stage,volts in enumerate((0,2.012,10.025)):
        assert w.stage==stage
        if stage:w.reference.setValue(volts)
        w.start_stage();finish()
    assert w.stage==3 and len(w.profiles)==16
    assert w.profiles[0].zero==400.5 and abs(w.profiles[0].gain-2.012/2000)<1e-9
    assert not list(tmp_path.rglob('*.json'))
    w.save_device();finish()
    assert sum(cmd==p.Command.LINEAR_PROFILE for cmd,_ in w.worker.sent)==16
    assert any(cmd==p.Command.SAVE_CALIBRATION for cmd,_ in w.worker.sent)
    assert w.worker.sent[-1][0]==p.Command.READ_COEFFICIENTS
    assert list(tmp_path.rglob('calibration-report-*.json'))
    assert all(v[0]==1 for v in w.current.values())
    assert abs(float(w.table.item(0,1).text())-2.012/2000*4095/3.3)<1e-6
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
