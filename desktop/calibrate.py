"""Standalone two-step DC calibration wizard. Run: python -m desktop.calibrate."""
import json
import os
from pathlib import Path
import struct
import sys
import time
import numpy as np
import serial.tools.list_ports
from PySide6 import QtCore, QtGui, QtWidgets as W
from .backend import DeviceWorker
from .calibration import ProfileStore, dc_point, linear_profile, profile_command
from .gui import DARK_STYLE
from . import protocol as p


class CalibrationWindow(W.QWidget):
    def __init__(self):
        super().__init__()
        if not QtGui.QFontDatabase.families():
            font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'segoeui.ttf'
            if font.exists():QtGui.QFontDatabase.addApplicationFont(str(font))
        self.setWindowTitle('Car Sniffer — калибровка аналоговых входов');self.resize(780,650)
        self.setStyleSheet(DARK_STYLE)
        self.worker=None;self.uid=None;self.boot=None;self.pending={};self.stage=0;self.busy=False
        self.samples={};self.references={};self.profiles=[];self.jobs=[];self.active=None
        self.current={};self.read_received=set();self.read_request=None;self.read_ack=False;self.read_done=None;self.read_started=0
        self.raw=[];self.raw_since=None;self.duration_ms=1000;self.collect_at=None;self.ready=False
        layout=W.QVBoxLayout(self)
        row=W.QHBoxLayout();layout.addLayout(row)
        self.port=W.QComboBox();row.addWidget(self.port,1)
        self.refresh=W.QPushButton('Обновить');self.refresh.clicked.connect(self.refresh_ports);row.addWidget(self.refresh)
        self.connect=W.QPushButton('Подключить');self.connect.clicked.connect(self.connect_device);row.addWidget(self.connect)
        intro=W.QLabel('Калибровка всех 8 входов. Закройте основное приложение, чтобы освободить COM-порт.\n'
                       'Источник подключайте к AIN 1–8, общий провод — к GND платы. '
                       'Постоянный диапазон 0–15 В. Делитель 10 кОм должен быть подключён к GND.');intro.setWordWrap(True);layout.addWidget(intro)
        self.instruction=W.QLabel();self.instruction.setWordWrap(True);layout.addWidget(self.instruction)
        form=W.QFormLayout();layout.addLayout(form)
        self.reference=W.QDoubleSpinBox();self.reference.setDecimals(4);self.reference.setSuffix(' V')
        form.addRow('Фактическое напряжение по мультиметру:',self.reference)
        self.table=W.QTableWidget(8,3);self.table.setHorizontalHeaderLabels(['Вход','a','b, В'])
        self.table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        for ch in range(8):self.table.setItem(ch,0,W.QTableWidgetItem(f'AIN {ch+1}'))
        self.coefficient_title=W.QLabel('y = a*x + b; x = raw ADC × 3.3/4095 В, y — напряжение AIN, В. До подключения показаны factory defaults.')
        self.coefficient_title.setWordWrap(True);layout.addWidget(self.coefficient_title)
        layout.addWidget(self.table,1)
        self.progress=W.QProgressBar();layout.addWidget(self.progress)
        row=W.QHBoxLayout();layout.addLayout(row)
        self.run=W.QPushButton('Измерить');self.run.setObjectName('captureButton');self.run.clicked.connect(self.start_stage);row.addWidget(self.run)
        self.save=W.QPushButton('Записать в устройство');self.save.clicked.connect(self.save_device);row.addWidget(self.save)
        self.reset=W.QPushButton('Сбросить мастер');self.reset.clicked.connect(self.reset_wizard);row.addWidget(self.reset)
        self.factory=W.QPushButton('Заводские коэффициенты…');self.factory.clicked.connect(self.reset_factory);layout.addWidget(self.factory)
        self.info=W.QLabel('Подключите плату. Коэффициенты применяет устройство; основное приложение их не загружает.');self.info.setWordWrap(True);layout.addWidget(self.info)
        self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(25)
        self.refresh_ports();self.show_stage();self.draw_coefficients()

    def refresh_ports(self):
        self.port.clear()
        for port in serial.tools.list_ports.comports():self.port.addItem(f'{port.device} — {port.description}',port.device)

    def controls(self):
        self.run.setEnabled(self.ready and not self.busy and self.stage<2)
        self.save.setEnabled(self.ready and not self.busy and self.stage==2 and len(self.profiles)==8)
        self.reference.setEnabled(not self.busy and self.stage==1)
        self.reset.setEnabled(not self.busy)
        self.factory.setEnabled(self.ready and not self.busy)
        self.connect.setEnabled(not self.busy);self.port.setEnabled(not self.worker);self.refresh.setEnabled(not self.worker)

    def show_stage(self):
        instructions=[
            'Шаг 1/2. Подключите все 8 аналоговых входов к GND.\nНажмите «Измерить»: будет измерен ноль каждого входа.',
            'Шаг 2/2. Подключите все 8 входов к источнику примерно 10.0 В.\nВведите точное показание мультиметра и нажмите «Измерить».',
            'Все 8 профилей готовы. Отключите источник 10 В или подключите входы к GND.\nНажмите «Записать в устройство»: коэффициенты применятся сразу и сохранятся во Flash. Перезапуск не требуется.']
        self.instruction.setText(instructions[self.stage])
        if self.stage==1:self.reference.setRange(8,12);self.reference.setValue(10)
        else:self.reference.setRange(0,15);self.reference.setValue(0)
        self.controls()

    def command(self,cmd,args=b'',done=None):
        if not self.worker or not self.worker.connected:raise ValueError('Устройство не подключено')
        request=self.worker.send(cmd,args);self.pending[request]=(cmd,time.monotonic(),done)
        return request

    def sequence(self,items,done):
        items=list(items)
        def advance():
            if items:
                cmd,args=items.pop(0);self.command(cmd,args,advance)
            else:done()
        advance()

    def connect_device(self):
        if self.worker:
            self.worker.close();self.worker=None;self.uid=None;self.ready=False;self.pending.clear();self.read_request=None
            self.connect.setText('Подключить');self.controls();return
        if not self.port.currentData():return
        self.worker=DeviceWorker(self.port.currentData());self.worker.start()
        self.connect.setText('Отключить');self.boot=None;self.uid=None;self.ready=False;self.controls()

    def initialize(self):
        self.busy=True;self.controls()
        # Calibration is a bench operation: never preserve an active bridge/capture.
        commands=[(p.Command.BRIDGE,b'\0'),(p.Command.CAPTURE,b'\0'),(p.Command.RELOAD_CALIBRATION,b'')]
        commands += [(p.Command.CHANNEL,bytes([ch,1,1])) for ch in range(8)]
        def done():self.ready=True;self.busy=False;self.info.setText(f'Подключено: {self.uid}. Текущие коэффициенты считаны с платы.');self.controls()
        self.sequence(commands,lambda:self.read_coefficients(done))

    def reset_wizard(self):
        self.stage=0;self.samples={};self.references={};self.profiles=[];self.progress.setValue(0)
        self.draw_coefficients()
        self.show_stage()

    def start_stage(self):
        if not self.ready or self.busy:return
        self.busy=True;self.controls();self.references[self.stage]=self.reference.value()
        self.jobs=[(ch,1) for ch in range(8)]
        self.total=len(self.jobs);self.progress.setRange(0,self.total);self.progress.setValue(0)
        self.next_channel()

    def next_channel(self):
        if not self.jobs:
            self.sequence([(p.Command.CHANNEL,bytes([ch,1,1])) for ch in range(8)],self.finish_stage);return
        self.active=self.jobs.pop(0);ch,r=self.active;self.raw=[];self.raw_since=None
        self.info.setText(f'Измеряется AIN {ch+1}, 0–15 В. Не меняйте подключение.')
        def settled():
            if not self.busy:return
            def started():self.collect_at=time.monotonic()+(self.duration_ms+250)/1000
            self.command(p.Command.RAW,struct.pack('<BH',ch,self.duration_ms),started)
        self.command(p.Command.CHANNEL,bytes([ch,1,r]),lambda:QtCore.QTimer.singleShot(100,settled))

    def finish_channel(self):
        self.collect_at=None;ch,r=self.active
        if self.worker.parser.gaps or self.worker.dropped:raise ValueError('Потеря пакетов: повторите калибровку')
        times=np.asarray([v[0] for v in self.raw]);raw=[v[3] for v in self.raw]
        if len(times)<int(self.duration_ms*1.6*.9) or np.any(np.diff(times)!=625):
            raise ValueError('Неполный RAW поток или пропуск отсчётов')
        try:
            dc_point(raw,0 if self.stage==0 else self.references[self.stage])
        except ValueError as exc:
            raise ValueError(f'AIN {ch+1}, 0–15 В: {exc}; '
                             f'n={len(raw)}, mean={np.mean(raw):.2f}, min={min(raw)}, max={max(raw)}') from exc
        self.samples[self.stage,ch,r]=raw
        if self.stage!=0:
            profile=linear_profile(ch,r,self.samples[0,ch,r],raw,self.references[self.stage],int(time.time()))
            self.profiles.append(profile);self.draw_coefficients()
        self.progress.setValue(self.total-len(self.jobs));self.next_channel()

    def finish_stage(self):
        self.active=None;self.busy=False;self.stage+=1;self.show_stage()
        self.info.setText('Измерение завершено. Коэффициенты ещё не записаны.')

    def save_device(self):
        if not self.ready or self.busy or len(self.profiles)!=8:return
        self.busy=True;self.controls();self.info.setText('Передача 8 профилей и запись Flash… Не отключайте питание.')
        self.sequence([profile_command(profile) for profile in self.profiles]+[(p.Command.SAVE_CALIBRATION,b'')],self.saved)

    def saved(self):
        profiles=self.profiles;self.busy=False;self.profiles=[];self.controls()
        self.busy=True;self.controls()
        self.read_coefficients(self.finish_readback)
        # This audit copy is for the utility only; the acquisition app never reads it.
        try:
            base=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'CarSniffer'
            ProfileStore(base/f'calibration-report-{self.uid}.json').save(self.uid,profiles)
            self.info.setText('Калибровка применена и сохранена во Flash. Перезапуск не требуется; после включения питания она восстановится автоматически. Можно закрыть утилиту.')
        except (OSError,ValueError) as exc:self.info.setText(f'Калибровка записана в устройство, но отчёт не сохранён: {exc}')

    def finish_readback(self):
        self.busy=False;self.controls()

    def reset_factory(self):
        if not self.ready or self.busy:return
        answer=W.QMessageBox.question(self,'Сброс к заводским коэффициентам',
            'Заменить калибровку всех 8 входов заводскими коэффициентами?\n'
            'Результат сохранится во Flash и применится сразу. Измеренные коэффициенты будут заменены.',
            W.QMessageBox.StandardButton.Yes|W.QMessageBox.StandardButton.No,W.QMessageBox.StandardButton.No)
        if answer!=W.QMessageBox.StandardButton.Yes:return
        self.busy=True;self.controls();self.info.setText('Восстановление заводских коэффициентов… Не отключайте питание.')
        commands=[(p.Command.BRIDGE,b'\0'),(p.Command.CAPTURE,b'\0')]
        commands += [(p.Command.CHANNEL,bytes([ch,1,1])) for ch in range(8)]
        commands += [(p.Command.RESET_CALIBRATION,b'')]
        self.sequence(commands,lambda:self.read_coefficients(self.factory_readback))

    def factory_readback(self):
        if len(self.current)!=8 or any(source!=0 or version!=0 for source,version,_,_ in self.current.values()):
            raise ValueError('Устройство не подтвердило заводские коэффициенты')
        self.busy=False;self.reset_wizard()
        self.info.setText('Заводские коэффициенты применены и сохранены во Flash. Перезапуск не требуется.')

    def draw_coefficients(self):
        drafts={(profile.channel,profile.range):profile for profile in self.profiles}
        for ch in range(8):
            source,version,a,b=self.current.get((ch,1),(0,0,6.17*3.3/4095,-1.551))
            draft=drafts.get((ch,1))
            if draft:a,b=draft.gain,-draft.zero*draft.gain
            for offset,value in enumerate((a,b)):
                item=W.QTableWidgetItem(f'{value*(4095/3.3) if offset==0 else value:.6f}' if np.isfinite(value) else 'таблица')
                note='Новые коэффициенты; ещё не записаны' if draft else ('factory defaults' if source==0 else f'Измеренные коэффициенты, версия {version}' if source==1 else 'Нелинейный профиль: единой прямой нет')
                item.setToolTip(note)
                if draft:item.setForeground(QtGui.QColor('#efba73'))
                self.table.setItem(ch,1+offset,item)

    def read_coefficients(self,done):
        self.read_received=set();self.read_ack=False;self.read_done=done;self.read_started=time.monotonic()
        def acknowledged():self.read_ack=True;self.finish_coefficients()
        self.read_request=self.command(p.Command.READ_COEFFICIENTS,done=acknowledged)

    def finish_coefficients(self):
        if self.read_request is None or not self.read_ack or len(self.read_received)!=8:return
        self.read_request=None
        self.coefficient_title.setText('y = a*x + b; x = raw ADC × 3.3/4095 В, y — напряжение AIN, В. Текущие коэффициенты считаны с устройства; новые до записи выделены цветом.')
        self.draw_coefficients();done=self.read_done;self.read_done=None;done()

    def fail(self,message):
        self.ready=False;self.busy=False;self.active=None;self.collect_at=None;self.pending.clear();self.profiles=[];self.read_request=None
        if self.worker and self.worker.connected:
            try:
                self.worker.send(p.Command.RAW,struct.pack('<BH',0,0))
                self.worker.send(p.Command.RELOAD_CALIBRATION)
                for ch in range(8):self.worker.send(p.Command.CHANNEL,bytes([ch,1,1]))
            except Exception:pass
        self.info.setText(f'Ошибка: {message}. Отключитесь, сбросьте мастер и подключитесь заново.');self.controls()

    def poll(self):
        if not self.worker:return
        try:
            if self.worker.error:raise ValueError(self.worker.error)
            for packet in self.worker.drain():
                if packet.kind==p.Kind.STATUS:
                    for status in p.records(p.STATUS,packet.payload):
                        if self.boot is None:
                            self.boot=status[1];self.uid=status[4].hex();self.reset_wizard();self.initialize()
                        elif status[1]!=self.boot:raise ValueError('Устройство перезапущено во время сеанса')
                elif packet.kind==p.Kind.COEFFICIENTS:
                    for request,ch,r,source,version,a,b in p.records(p.COEFFICIENTS,packet.payload):
                        if request==self.read_request:
                            if r!=1:raise ValueError('Нужна прошивка для постоянного делителя. Обновите прошивку платы.')
                            if ch>=8 or source>2 or (source!=2 and (not np.isfinite([a,b]).all() or a<=0)):
                                raise ValueError('Некорректные коэффициенты устройства')
                            self.current[ch,r]=(source,version,a,b);self.read_received.add((ch,r))
                    self.finish_coefficients()
                elif packet.kind==p.Kind.RESPONSE:
                    request,cmd,result,t=struct.unpack('<IBBQ',packet.payload)
                    pending=self.pending.pop(request,None)
                    if pending:
                        if cmd!=pending[0] or result:raise ValueError(f'Команда {cmd} отклонена ({result}). Проверьте версию прошивки.')
                        if cmd==p.Command.RAW:self.raw_since=t
                        if pending[2]:pending[2]()
                elif packet.kind==p.Kind.RAW and self.active and self.raw_since is not None:
                    for value in p.records(p.RAW,packet.payload):
                        if value[1:3]==self.active and value[0]>=self.raw_since and len(self.raw)<16000:self.raw.append(value)
            if self.read_request is not None and time.monotonic()-self.read_started>8:raise ValueError('Устройство не передало все 8 коэффициентов')
            if any(time.monotonic()-sent>8 for _,sent,_ in self.pending.values()):raise ValueError('Нет подтверждения команды')
            if self.collect_at and time.monotonic()>=self.collect_at:self.finish_channel()
        except (ValueError,OSError,struct.error,KeyError) as exc:self.fail(str(exc))

    def closeEvent(self,event):
        if self.busy:
            self.info.setText('Дождитесь окончания измерения или записи перед закрытием.');event.ignore();return
        if self.worker:self.worker.close()
        event.accept()


def main():
    app=W.QApplication(sys.argv);app.setStyle('Fusion')
    window=CalibrationWindow();window.show();sys.exit(app.exec())

if __name__=='__main__':main()
