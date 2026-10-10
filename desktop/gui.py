from collections import deque
from pathlib import Path
import math
import os
import struct
import time
import numpy as np
import pyqtgraph as pg
import serial.tools.list_ports
from PySide6 import QtCore, QtGui, QtWidgets as W
from . import protocol as p
from .backend import DeviceWorker
from .calibration import Profile, ProfileStore, dc_point, sine_profile

EVENT_NAMES = {1:'LEC',2:'CAN state',3:'RX overflow',4:'TX queue overflow',5:'Delivery expired',6:'USB loss',
               7:'Recovery',8:'Bridge stopped',9:'Range change',10:'DMA loss',11:'Capture',12:'Loopback',13:'Reconfigure RX loss'}
LEC_NAMES = {1:'stuff',2:'form',3:'ACK',4:'bit recessive',5:'bit dominant',6:'CRC'}
DISPLAY_ROLE=int(QtCore.Qt.ItemDataRole.DisplayRole)
FOREGROUND_ROLE=int(QtCore.Qt.ItemDataRole.ForegroundRole)
EVENT_COLOR=QtGui.QColor('#efba73')

DARK_STYLE = '''
QWidget { background: #171d25; color: #dce5ef; font-family: "Segoe UI"; font-size: 12px; }
QLabel { background: transparent; }
QLabel#channelValue { color: #87d8ef; font-size: 12px; }
QLabel#notice { color: #9aaabc; font-size: 11px; }
QWidget#channelControls { background: #1b232e; border-radius: 4px; }
QScrollArea { border: 1px solid #303c4b; border-radius: 4px; }
QPushButton, QComboBox, QLineEdit, QDoubleSpinBox { background: #253140; border: 1px solid #405066; border-radius: 4px; padding: 4px 6px; min-height: 18px; }
QPushButton:hover, QComboBox:hover { background: #304155; border-color: #6591ad; }
QPushButton:pressed { background: #1e5266; }
QPushButton#captureButton { background: #17617a; border-color: #3c9eb7; font-weight: 600; }
QPushButton#captureButton:hover { background: #217b95; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView { background: #253140; selection-background-color: #315a73; }
QCheckBox { spacing: 6px; background: transparent; }
QCheckBox::indicator { width: 12px; height: 12px; border: 1px solid #728399; border-radius: 3px; background: #131b24; }
QCheckBox::indicator:checked { background: #58c5df; border: 2px solid #253d4d; }
QCheckBox::indicator:hover { border-color: #8bdcf0; }
QGroupBox { border: 1px solid #354254; border-radius: 4px; margin-top: 9px; padding-top: 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #b8cfdf; }
QTableView { background: #141b23; alternate-background-color: #1b2531; color: #dce5ef; gridline-color: #2a3645; selection-background-color: #28546d; selection-color: #ffffff; border: 1px solid #344153; font-family: "Consolas"; font-size: 11px; }
QHeaderView::section { background: #263343; color: #cbdbe9; border: none; border-right: 1px solid #3a4859; border-bottom: 1px solid #405066; padding: 5px 3px; font-weight: 600; }
QTableCornerButton::section { background: #263343; border: none; }
QSplitter::handle { background: #303c4b; }
QSplitter::handle:hover { background: #56829a; }
QStatusBar { background: #111820; border-top: 1px solid #354254; }
QStatusBar::item { border: none; }
QScrollBar:vertical { background: #171d25; width: 10px; margin: 0; }
QScrollBar:horizontal { background: #171d25; height: 10px; margin: 0; }
QScrollBar::handle { background: #46566a; border-radius: 4px; min-width: 20px; min-height: 20px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QToolTip { background: #2b3a4b; color: #ffffff; border: 1px solid #658299; padding: 4px; }
'''


class FrameModel(QtCore.QAbstractTableModel):
    headers = ['Time MCU, s','ID / event','IDE','RTR','DLC','DATA','CRC_OK','ACK_RX','TX_ACK','Forward']
    def __init__(self, capacity=20000):
        super().__init__()
        self.rows = []
        self.row_index = {}
        self.capacity = capacity
        self.evicted = 0

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self.headers)

    def headerData(self, section, orientation, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if role == QtCore.Qt.ItemDataRole.DisplayRole and orientation == QtCore.Qt.Orientation.Horizontal:
            return self.headers[section]

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if role!=DISPLAY_ROLE and role!=FOREGROUND_ROLE:
            return None
        if not index.isValid():return None
        row = self.rows[index.row()]
        if role == DISPLAY_ROLE:
            return row['cells'][index.column()]
        if row['event']:
            return EVENT_COLOR

    def append(self, rows):
        if not rows:
            return
        # Batched insert/remove retains scroll position and avoids resets on every tick.
        if len(rows) > self.capacity:
            self.evicted += len(rows) - self.capacity
            rows = rows[-self.capacity:]
        remove = max(0, len(self.rows) + len(rows) - self.capacity)
        if remove:
            self.beginRemoveRows(QtCore.QModelIndex(), 0, remove - 1)
            del self.rows[:remove]
            self.endRemoveRows()
            self.evicted += remove
        self.beginInsertRows(QtCore.QModelIndex(), len(self.rows), len(self.rows) + len(rows) - 1)
        self.rows.extend(rows)
        self.endInsertRows()
        if remove:
            self.row_index = {r['frame_id']: i for i, r in enumerate(self.rows) if not r['event']}
        else:
            for i,r in enumerate(rows,start=len(self.rows)-len(rows)):
                if not r['event']:self.row_index[r['frame_id']]=i

    def update_tx(self, frame_id, state, ack):
        i = self.row_index.get(frame_id)
        if i is not None:
            self.rows[i]['cells'][8] = {-1:'N/A',0:'0',1:'1',2:'pending'}.get(ack, '?')
            self.rows[i]['cells'][9] = p.TxState(state).name.lower()
            self.dataChanged.emit(self.index_at(i, 8), self.index_at(i, 9))

    def index_at(self, row, col):
        return self.createIndex(row, col)

    def clear(self):
        self.beginResetModel(); self.rows.clear(); self.row_index.clear(); self.evicted = 0; self.endResetModel()

class FrameFilter(QtCore.QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.ranges = []
        self.ide = self.rtr = -1
        self.frames = self.events = True

    def set_ids(self, value):
        ranges = []
        for token in value.replace(' ', '').split(','):
            if not token:
                continue
            pair = token.split('-')
            if len(pair) > 2:
                raise ValueError('Invalid ID range')
            lo, hi = int(pair[0], 16), int(pair[-1], 16)
            if not 0 <= lo <= hi <= 0x1fffffff:
                raise ValueError('Invalid CAN ID')
            ranges.append((lo, hi))
        self.ranges = ranges
        self.invalidate()

    def filterAcceptsRow(self, row, parent):
        r = self.sourceModel().rows[row]
        if r['event']:
            return self.events
        return (self.frames and (not self.ranges or any(lo <= r['id'] <= hi for lo,hi in self.ranges))
                and (self.ide < 0 or self.ide == r['ide']) and (self.rtr < 0 or self.rtr == r['rtr']))

class CanPanel(W.QWidget):
    def __init__(self, side):
        super().__init__()
        layout = W.QVBoxLayout(self); layout.setContentsMargins(3,3,3,3)
        layout.addWidget(W.QLabel(f'CAN {side} — incoming RX / errors'))
        self.controls = W.QGroupBox(f'CAN {side} filters'); bar = W.QVBoxLayout(self.controls)
        self.ids = W.QLineEdit(); self.ids.setPlaceholderText('ID hex: 100,200-2FF')
        self.ide, self.rtr = W.QComboBox(), W.QComboBox()
        self.ide.addItems(['IDE any','IDE 0','IDE 1']); self.rtr.addItems(['RTR any','RTR 0','RTR 1'])
        self.frames, self.events, self.scroll = W.QCheckBox('Frames'), W.QCheckBox('Errors'), W.QCheckBox('Auto scroll')
        for c in (self.frames, self.events, self.scroll): c.setChecked(True)
        for w in (self.ids,self.ide,self.rtr,self.frames,self.events,self.scroll): bar.addWidget(w)
        self.model = FrameModel(); self.proxy = FrameFilter()
        self.table = W.QTableView(); self.table.setModel(self.model); self.table.setAlternatingRowColors(True)
        self.table.setFont(QtGui.QFont('Consolas',9))
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setWordWrap(False); self.table.verticalHeader().hide(); self.table.verticalHeader().setDefaultSectionSize(20)
        for col, width in enumerate([88,96,32,32,32,170,55,55,65,75]): self.table.setColumnWidth(col,width)
        self.table.horizontalHeader().moveSection(5,2)
        layout.addWidget(self.table)
        self.ids.textChanged.connect(self.apply_filter)
        for w in (self.ide,self.rtr): w.currentIndexChanged.connect(self.apply_filter)
        for w in (self.frames,self.events): w.toggled.connect(self.apply_filter)

    def apply_filter(self, *_):
        try:
            self.proxy.set_ids(self.ids.text()); self.ids.setStyleSheet('')
        except ValueError:
            self.ids.setStyleSheet('background:#5b2c36; color:#ffe2e6'); return
        self.proxy.ide, self.proxy.rtr = self.ide.currentIndex()-1, self.rtr.currentIndex()-1
        self.proxy.frames, self.proxy.events = self.frames.isChecked(), self.events.isChecked()
        self.proxy.invalidate()
        filtered=bool(self.proxy.ranges) or self.proxy.ide>=0 or self.proxy.rtr>=0 or not self.proxy.frames or not self.proxy.events
        if filtered and self.proxy.sourceModel() is None:self.proxy.setSourceModel(self.model)
        desired=self.proxy if filtered else self.model
        if self.table.model() is not desired:self.table.setModel(desired)
        if not filtered:self.proxy.setSourceModel(None)

class CalibrationDialog(W.QDialog):
    def __init__(self, window):
        super().__init__(window); self.window = window; self.setWindowTitle('Calibration — raw ADC and reference voltage'); self.resize(780,650)
        self.samples = []; self.points = []; self.collecting = False
        self.raw_start_timer=QtCore.QTimer(self);self.raw_start_timer.setSingleShot(True)
        self.raw_start_timer.timeout.connect(self.start_raw)
        self.raw_finish_timer=QtCore.QTimer(self);self.raw_finish_timer.setSingleShot(True);self.raw_finish_timer.timeout.connect(self.finish)
        layout = W.QVBoxLayout(self)
        form = W.QFormLayout(); layout.addLayout(form)
        self.channel, self.range = W.QComboBox(), W.QComboBox(); self.channel.addItems([f'AIN {i+1}' for i in range(8)]); self.range.addItems(['0–3.3 V','0–15 V'])
        self.reference = W.QDoubleSpinBox(); self.reference.setDecimals(5); self.reference.setRange(0,15)
        self.duration = W.QDoubleSpinBox(); self.duration.setRange(.2,10); self.duration.setValue(2); self.duration.setSuffix(' s')
        for name,w in [('Channel',self.channel),('Range',self.range),('Voltmeter reference, V',self.reference),('Raw collection duration',self.duration)]: form.addRow(name,w)
        row = W.QHBoxLayout(); layout.addLayout(row)
        for label, callback in [('Collect raw',self.collect),('Add DC point',self.add_dc),('Remove selected point',self.remove_point),('Upload and save',self.save)]:
            b=W.QPushButton(label);b.clicked.connect(callback);row.addWidget(b)
        self.table=W.QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['Raw ADC','Reference, V']);layout.addWidget(self.table)
        sine=W.QGroupBox('Known sine — phase fit, both branches checked'); sf=W.QFormLayout(sine);layout.addWidget(sine)
        self.frequency=W.QDoubleSpinBox();self.frequency.setRange(.1,20);self.frequency.setValue(5)
        self.amplitude=W.QDoubleSpinBox();self.amplitude.setRange(.01,15);self.amplitude.setValue(1)
        self.definition=W.QComboBox();self.definition.addItems(['peak','peak-to-peak','RMS'])
        self.offset=W.QDoubleSpinBox();self.offset.setRange(0,15);self.offset.setValue(1.5)
        sr=W.QHBoxLayout()
        for w in (self.frequency,self.amplitude,self.definition,self.offset):sr.addWidget(w)
        sf.addRow('Hz / amplitude / definition / DC offset, V',sr)
        fit=W.QPushButton('Identify monotonic sine table');fit.clicked.connect(self.fit_sine);sf.addRow(fit)
        self.plot=pg.PlotWidget();layout.addWidget(self.plot)
        self.info=W.QLabel('Use a stable source and external voltmeter. Raw stream is limited to one channel, 1600 samples/s, 10 s.');self.info.setWordWrap(True);layout.addWidget(self.info)
        self.channel.currentIndexChanged.connect(self.load_profile);self.range.currentIndexChanged.connect(self.load_profile)
        self.load_profile()

    def load_profile(self):
        self.collecting=False;self.samples=[]
        p_=self.window.profiles.get((self.channel.currentIndex(),self.range.currentIndex()))
        self.points=list(p_.points) if p_ else [];self.redraw()

    def redraw(self):
        self.table.setRowCount(len(self.points))
        for i,point in enumerate(self.points):
            for j,value in enumerate(point):self.table.setItem(i,j,W.QTableWidgetItem(f'{value:.5f}'))
        self.plot.clear()
        if self.points:
            a=np.array(self.points);self.plot.plot(a[:,0],a[:,1],symbol='o',pen='#55c8ed')
            self.info.setText(f'Calibrated interval: raw {a[0,0]:.1f}…{a[-1,0]:.1f}; {a[0,1]:.4f}…{a[-1,1]:.4f} V. No extrapolation.')

    def collect(self):
        if not self.window.worker or not self.window.device_id:
            self.info.setText('Connect a device first');return
        ch,r=self.channel.currentIndex(),self.range.currentIndex();self.samples=[];self.collecting=True
        self.channel.setEnabled(False);self.range.setEnabled(False);self.duration.setEnabled(False)
        self.window.channels[ch][1].setChecked(bool(r))
        self.window.send(p.Command.CHANNEL,bytes([ch,1,r]))
        # Allow switching transient to settle before raw session.
        duration=round(self.duration.value()*1000)
        self.raw_arguments=struct.pack('<BH',ch,duration)
        self.raw_start_timer.start(100);self.raw_finish_timer.start(duration+200)
        self.info.setText('Collecting raw samples…')

    def start_raw(self):
        self.window.send(p.Command.RAW,self.raw_arguments)

    def closeEvent(self,event):
        self.raw_start_timer.stop();self.raw_finish_timer.stop()
        if self.collecting:self.window.send(p.Command.RAW,struct.pack('<BH',self.channel.currentIndex(),0))
        self.collecting=False;event.accept()

    def finish(self):
        self.collecting=False
        self.channel.setEnabled(True);self.range.setEnabled(True);self.duration.setEnabled(True)
        if self.samples:
            a=np.array([v[3] for v in self.samples]);self.info.setText(f'{len(a)} samples; mean {a.mean():.3f}; std {a.std():.3f}; min/max {a.min():.0f}/{a.max():.0f}; clipping {bool(a.min()<=2 or a.max()>=4093)}')

    def add_dc(self):
        try:
            self.points.append(dc_point([v[3] for v in self.samples],self.reference.value()));self.points.sort();self.redraw()
        except ValueError as exc:self.info.setText(str(exc))

    def remove_point(self):
        row=self.table.currentRow()
        if row>=0:del self.points[row];self.redraw()

    def fit_sine(self):
        try:
            profile=sine_profile([v[0] for v in self.samples],[v[3] for v in self.samples],self.frequency.value(),self.amplitude.value(),self.definition.currentText(),self.offset.value(),self.channel.currentIndex(),self.range.currentIndex())
            self.points=profile.points;self.redraw()
        except ValueError as exc:self.info.setText(str(exc))

    def save(self):
        try:
            ch,r=self.channel.currentIndex(),self.range.currentIndex();old=self.window.profiles.get((ch,r))
            points=[[float(self.table.item(i,0).text()),float(self.table.item(i,1).text())] for i in range(self.table.rowCount())]
            profile=Profile(ch,r,old.version+1 if old else 1,points).validate()
            # Firmware stores raw breakpoints as uint16; validate again after rounding.
            profile.points=[[round(raw),volts] for raw,volts in profile.points];profile.validate()
            self.window.upload_profile(profile,save=True)
            self.info.setText('Upload requested; profile is saved only after device acknowledgement.')
        except (ValueError,AttributeError) as exc:self.info.setText(str(exc))

class AnalogViewBox(pg.ViewBox):
    def wheelEvent(self,event,axis=None):
        # AxisItem explicitly supplies X/Y; the plot surface defaults to voltage.
        super().wheelEvent(event,axis=1 if axis is None else axis)


class MainWindow(W.QMainWindow):
    def showEvent(self,event):
        super().showEvent(event)
        if os.name!='nt' or W.QApplication.platformName()!='windows':return
        import ctypes
        from ctypes import wintypes
        dwm=ctypes.WinDLL('dwmapi')
        apply=dwm.DwmSetWindowAttribute
        apply.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
        apply.restype=ctypes.c_long
        # DWM colors use COLORREF (0x00BBGGRR); unsupported attributes are ignored.
        for attribute,color in ((20,1),(35,0x251d17),(36,0xefe5dc),(34,0x251d17)):
            value=wintypes.DWORD(color)
            apply(int(self.winId()),attribute,ctypes.byref(value),ctypes.sizeof(value))

    def __init__(self, demo=False, demo_fps=2000):
        super().__init__()
        # Qt's offscreen plugin on Windows has no system font database; keep QA renders readable.
        if not QtGui.QFontDatabase.families():
            for name in ('segoeui.ttf','consola.ttf'):
                font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name
                if font.exists():QtGui.QFontDatabase.addApplicationFont(str(font))
        W.QApplication.instance().setFont(QtGui.QFont('Segoe UI',9))
        pg.setConfigOptions(background='#151c24',foreground='#c8d3df',antialias=False)
        self.setWindowTitle('Car Sniffer | CAN A / CAN B + 8 analog inputs');self.resize(1700,1000)
        self.worker=None;self.demo_fps=demo_fps;self.device_id=None;self.boot=None;self.profiles={};self.profile_pending={}
        self.calibration=None;self.last_status=None;self.pending={};self.host_cleared_t=0;self.update_count=0;self.max_update_ms=0
        self.analog=[deque(maxlen=6000) for _ in range(8)];self.analog_evicted=0
        self.time_span=20.0
        container=W.QWidget();self.setCentralWidget(container);layout=W.QVBoxLayout(container);layout.setContentsMargins(6,6,6,6)
        body=W.QHBoxLayout();layout.addLayout(body,1)
        self.content_splitter=W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.content_splitter.setChildrenCollapsible(False);body.addWidget(self.content_splitter,1)
        self.control_scroll=W.QScrollArea();self.control_scroll.setWidgetResizable(True)
        self.control_scroll.setFixedWidth(190);self.control_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        control_widget=W.QWidget();toolbar=W.QVBoxLayout(control_widget);toolbar.setContentsMargins(8,8,8,8)
        self.control_scroll.setWidget(control_widget);body.addWidget(self.control_scroll)
        toolbar.addWidget(W.QLabel('Device'))
        self.port=W.QComboBox();self.port.setMinimumWidth(0);self.port.setSizePolicy(W.QSizePolicy.Policy.Ignored,W.QSizePolicy.Policy.Fixed)
        self.port.setToolTip('Select USB serial port or simulated device');self.refresh_ports();toolbar.addWidget(self.port)
        b=W.QPushButton('Refresh');b.clicked.connect(self.refresh_ports);toolbar.addWidget(b)
        self.connect_button=W.QPushButton('Connect');self.connect_button.clicked.connect(self.toggle_connection);toolbar.addWidget(self.connect_button)
        self.rates=[]
        for side in range(2):
            toolbar.addWidget(W.QLabel(f'CAN {"AB"[side]} bitrate'))
            cb=W.QComboBox()
            for label,rate in [('Auto',0),('83.333 kbit/s',83333),('100 kbit/s',100000),('125 kbit/s',125000),('250 kbit/s',250000),('500 kbit/s',500000),('1000 kbit/s',1000000)]:cb.addItem(label,rate)
            cb.setCurrentIndex(5);self.rates.append(cb);toolbar.addWidget(cb)
            b=W.QPushButton('Apply');b.clicked.connect(lambda checked=False,s=side:self.apply_bitrate(s));toolbar.addWidget(b)
        self.bridge=W.QCheckBox('Bridge');self.bridge.toggled.connect(lambda v:self.send(p.Command.BRIDGE,bytes([v])));toolbar.addWidget(self.bridge)
        self.capture=W.QPushButton('Start capture');self.capture.setObjectName('captureButton');self.capture.clicked.connect(self.toggle_capture);toolbar.addWidget(self.capture)
        b=W.QPushButton('Clear results');b.clicked.connect(self.clear_results);toolbar.addWidget(b)
        b=W.QPushButton('Calibration…');b.clicked.connect(self.open_calibration);toolbar.addWidget(b)
        toolbar.addWidget(W.QLabel('Time window'))
        self.time_window=W.QDoubleSpinBox();self.time_window.setRange(.1,60);self.time_window.setDecimals(2)
        self.time_window.setSuffix(' s');self.time_window.setValue(self.time_span)
        self.time_window.setToolTip('Wheel over the time axis zooms time; wheel over a plot zooms voltage. Drag to browse after capture stops. Buffer: up to 60 s per channel.')
        self.time_window.valueChanged.connect(self.set_time_window);toolbar.addWidget(self.time_window)
        analog_widget=W.QWidget();al=W.QGridLayout(analog_widget);al.setContentsMargins(0,0,0,0);al.setSpacing(3)
        self.channels=[];self.curves=[];self.plots=[]
        for ch in range(8):
            controls=W.QWidget();controls.setObjectName('channelControls');row=W.QVBoxLayout(controls);row.setContentsMargins(3,2,3,2);row.setSpacing(2)
            controls.setFixedWidth(112)
            en=W.QCheckBox(f'AIN {ch+1}');en.setChecked(True)
            cb=W.QCheckBox('0–15 V');cb.setChecked(True);cb.setToolTip('Checked: 0–15 V (1:5). Unchecked: 0–3.3 V (unity).')
            label=W.QLabel('— V\nuncalibrated');label.setObjectName('channelValue');label.setWordWrap(True)
            for w in (en,cb,label):row.addWidget(w)
            row.addStretch();self.channels.append((en,cb,label))
            en.toggled.connect(lambda v,c=ch:self.channel_change(c));cb.toggled.connect(lambda v,c=ch:self.channel_change(c))
            plot=pg.PlotWidget(viewBox=AnalogViewBox());plot.setMinimumHeight(65);plot.setYRange(0,15,padding=0);plot.showGrid(x=True,y=True,alpha=.12)
            plot.getAxis('left').setWidth(38)
            if ch<7:plot.getAxis('bottom').setStyle(showValues=False);plot.getAxis('bottom').setHeight(5)
            if ch:plot.setXLink(self.plots[0])
            plot.getViewBox().setLimits(minXRange=.1,maxXRange=60)
            plot.getViewBox().sigRangeChangedManually.connect(lambda axes,v=plot.getViewBox():self.manual_time_range(v,axes))
            self.plots.append(plot);self.curves.append(plot.plot(pen=pg.mkPen('#55c8ed',width=1),connect='finite'))
            al.addWidget(controls,ch,0);al.addWidget(plot,ch,1);al.setRowStretch(ch,1)
        al.setColumnStretch(1,1);self.content_splitter.addWidget(analog_widget)
        right=W.QSplitter(QtCore.Qt.Orientation.Horizontal);right.setChildrenCollapsible(False)
        self.can=[CanPanel('A'),CanPanel('B')]
        for w in self.can:right.addWidget(w);toolbar.addWidget(w.controls)
        right.setSizes([500,500]);toolbar.addStretch()
        self.content_splitter.addWidget(right)
        self.content_splitter.setStretchFactor(0,1);self.content_splitter.setStretchFactor(1,1)
        self.content_splitter.setSizes([750,750])
        self.status=W.QLabel('Disconnected');self.status.setWordWrap(True)
        self.notice=W.QLabel('Apply both bitrates before enabling bridge. Range control defaults low (1:5); reset is Hi-Z.');self.notice.setWordWrap(True);self.notice.setObjectName('notice')
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().setFixedHeight(48)
        status_widget=W.QWidget();status_layout=W.QVBoxLayout(status_widget);status_layout.setContentsMargins(3,0,3,0);status_layout.setSpacing(0)
        status_layout.addWidget(self.status);status_layout.addWidget(self.notice);self.statusBar().addWidget(status_widget,1)
        self.setStyleSheet(DARK_STYLE)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(40);self.timer.timeout.connect(self.update_data);self.timer.start()
        if demo:self.port.setCurrentIndex(0);self.toggle_connection()

    def refresh_ports(self):
        current=self.port.currentData() if hasattr(self,'port') else None
        self.port.clear();self.port.addItem('DEMO — simulated device','DEMO')
        for port in serial.tools.list_ports.comports():self.port.addItem(f'{port.device} — {port.description}',port.device)
        index=self.port.findData(current)
        if index>=0:self.port.setCurrentIndex(index)

    def manual_time_range(self,view,axes):
        if not axes[0]:return
        left,right=view.viewRange()[0]
        self.time_span=max(.1,min(60,right-left))
        self.time_window.blockSignals(True);self.time_window.setValue(self.time_span);self.time_window.blockSignals(False)

    def set_time_window(self,seconds):
        self.time_span=seconds
        left,right=self.plots[0].viewRange()[0]
        if self.last_status and self.last_status[6]:
            right=max((points[-1][0] for points in self.analog if points),default=right)
        else:
            right=(left+right)/2+seconds/2
        self.plots[0].setXRange(right-seconds,right,padding=0)

    def send(self, command, args=b''):
        if not self.worker or not self.worker.connected:
            self.notice.setText('Device is not connected');return None
        try:
            request=self.worker.send(command,args);self.pending[request]=(command,time.monotonic());return request
        except Exception as exc:self.notice.setText(str(exc));return None

    def toggle_connection(self):
        if self.worker:
            self.worker.close();self.worker=None;self.connect_button.setText('Connect');self.device_id=None;self.last_status=None;return
        self.boot=None;self.device_id=None;self.profiles={};self.pending.clear();self.profile_pending.clear()
        self.worker=DeviceWorker(self.port.currentData(),self.demo_fps);self.worker.start();self.connect_button.setText('Disconnect')
        QtCore.QTimer.singleShot(200,lambda:self.send(p.Command.STATUS))

    def toggle_capture(self):
        active=bool(self.last_status and self.last_status[6])
        self.send(p.Command.CAPTURE,bytes([not active]));self.send(p.Command.STATUS)

    def channel_change(self,ch):
        en,cb,_=self.channels[ch];self.plots[ch].setYRange(0,(3.3,15)[int(cb.isChecked())],padding=0)
        # Break the trace at the range command even before the settling samples arrive.
        if self.analog[ch]:self.analog[ch].append((self.analog[ch][-1][0],math.nan))
        self.send(p.Command.CHANNEL,bytes([ch,en.isChecked(),int(cb.isChecked())]))
        self.save_settings()

    def save_settings(self):
        if not self.device_id:return
        settings={'channels':[{'enabled':en.isChecked(),'range':int(cb.isChecked())} for en,cb,_ in self.channels],
                  'rates':[cb.currentData() for cb in self.rates]}
        try:self.store().save_settings(self.device_id,settings)
        except (ValueError,OSError) as exc:self.notice.setText(str(exc))

    def apply_bitrate(self,side):
        self.send(p.Command.CAN_CONFIG,struct.pack('<BI',side,self.rates[side].currentData()));self.save_settings()

    def clear_results(self):
        for panel in self.can:panel.model.clear()
        for points in self.analog:points.clear()
        self.analog_evicted=0
        for curve in self.curves:curve.setData([],[])
        # Clear is display-only. Preserve pending responses and calibration traffic.

    def store(self):
        base=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'CarSniffer'
        return ProfileStore(base / f'calibration-{self.device_id}.json')

    def upload_profile(self,profile,save=False):
        payload=struct.pack('<BBIB',profile.channel,profile.range,profile.version,len(profile.points))+b''.join(struct.pack('<Hf',int(raw),volts) for raw,volts in profile.points)
        request=self.send(p.Command.PROFILE,payload)
        if request is not None:self.profile_pending[request]=(profile,save)

    def open_calibration(self):
        self.calibration=CalibrationDialog(self);self.calibration.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose);self.calibration.destroyed.connect(lambda:self.clear_calibration());self.calibration.show()

    def clear_calibration(self):self.calibration=None

    def handle_status(self,values):
        t,boot,loss,generation,uid,bridge,capture,mode_a,mode_b,rate_a,rate_b,*counters=values
        if boot!=self.boot:
            if self.boot is not None:self.notice.setText('MCU reset: new boot ID; capture results cleared for a new time axis')
            self.clear_results();self.boot=boot;self.device_id=uid.hex();self.profiles={};self.profile_pending.clear()
            try:saved=self.store().settings(self.device_id)
            except (ValueError,OSError) as exc:saved={};self.notice.setText(str(exc))
            for side,rate in enumerate(saved.get('rates',[500000,500000])):
                self.rates[side].setCurrentIndex(self.rates[side].findData(rate))
            for ch,(en,cb,_) in enumerate(self.channels):
                setting=saved.get('channels',[{'enabled':True,'range':1}]*8)[ch]
                enabled,range_=setting['enabled'],setting['range']
                en.blockSignals(True);cb.blockSignals(True);en.setChecked(enabled);cb.setChecked(bool(range_));en.blockSignals(False);cb.blockSignals(False)
                self.plots[ch].setYRange(0,(3.3,15)[range_],padding=0)
                self.send(p.Command.CHANNEL,bytes([ch,enabled,range_]))
            try:
                for profile in self.store().load(self.device_id):self.upload_profile(profile)
            except (ValueError,OSError) as exc:self.notice.setText(str(exc))
        self.last_status=values
        self.bridge.blockSignals(True);self.bridge.setChecked(bool(bridge));self.bridge.blockSignals(False)
        self.capture.setText('Stop capture' if capture else 'Start capture')
        state=[]
        for s,mode_ in enumerate((mode_a,mode_b)):
            c=counters[s*8:s*8+8]
            error_state='bus-off' if mode_&64 else 'passive' if mode_&32 else 'warning' if mode_&16 else 'active'
            state.append(f'{"AB"[s]} {("silent","normal","loopback")[mode_&3]}/{error_state} {values[9+s]/1000:g}k RX {c[0]} TX {c[1]} errors {c[2]} drop {c[3]+c[4]+c[5]} TEC/REC {c[6]}/{c[7]}')
        w=self.worker
        evicted=sum(panel.model.evicted for panel in self.can)
        self.status.setText(f'USB connected | bridge {"ON" if bridge else "OFF"} | '+ ' | '.join(state)+f' | USB loss {loss} | seq gaps {w.parser.gaps} | host loss {w.dropped} | old rows removed {evicted} | ADC removed {self.analog_evicted}')

    def update_data(self):
        start=time.perf_counter();self.update_count+=1
        if not self.worker:return
        if self.worker.error:self.notice.setText(self.worker.error)
        rows=[[],[]];tx=[]
        try:
            for packet in self.worker.drain():
                kind,data=packet.kind,packet.payload
                if kind==p.Kind.STATUS:
                    for values in p.records(p.STATUS,data):
                        if self.boot is not None and values[1]!=self.boot:rows=[[],[]];tx=[]
                        self.handle_status(values)
                elif kind==p.Kind.CAN_RX:
                    for t,fid,id_,side,ide,rtr,dlc,crc,raw in p.records(p.CAN,data):
                        if side>1:continue
                        rows[side].append({'frame_id':fid,'id':id_,'ide':ide,'rtr':rtr,'event':False,
                                           'cells':[f'{t/1e6:.6f}',f'{id_:08X}' if ide else f'{id_:03X}',str(ide),str(rtr),str(dlc),'' if rtr else raw[:min(dlc,8)].hex(' ').upper(),str(crc),'N/A','N/A','N/A']})
                elif kind==p.Kind.TX_STATUS:tx.extend(p.records(p.TX,data))
                elif kind==p.Kind.EVENT:
                    for t,side,code,detail,tec,rec in p.records(p.EVENT,data):
                        name=EVENT_NAMES.get(code,f'Event {code}');description=LEC_NAMES.get(detail,str(detail)) if code==1 else str(detail)
                        for s in ([side] if side<2 else [0,1]):rows[s].append({'frame_id':0,'event':True,'cells':[f'{t/1e6:.6f}',name,'','','',f'{description}; TEC/REC {tec}/{rec}','','','','']})
                        if code==9:
                            ch=detail>>8
                            if ch<8 and self.analog[ch]:self.analog[ch].append((t/1e6,math.nan))
                elif kind==p.Kind.ADC:
                    for t,ch,range_,q,raw,std,volts,version in p.records(p.ADC,data):
                        if ch>=8 or range_>1:continue
                        if len(self.analog[ch])==6000:self.analog_evicted+=1
                        invalid=q & (p.Quality.SETTLING|p.Quality.OUTSIDE_PROFILE|p.Quality.DMA_LOSS|p.Quality.CLIPPING)
                        if self.analog[ch] and t/1e6-self.analog[ch][-1][0]>.015:
                            self.analog[ch].append((self.analog[ch][-1][0]+.005,math.nan))
                        self.analog[ch].append((t/1e6,math.nan if invalid else volts))
                        flags=[flag.name.lower() for flag in p.Quality if flag & q]
                        self.channels[ch][2].setText(f'{volts:.4f} V\n'+(', '.join(flags) if flags else f'cal v{version}'))
                elif kind==p.Kind.RAW:
                    if self.calibration and self.calibration.collecting:
                        for value in p.records(p.RAW,data):
                            if value[1]==self.calibration.channel.currentIndex() and value[2]==self.calibration.range.currentIndex() and len(self.calibration.samples)<16000:self.calibration.samples.append(value)
                elif kind==p.Kind.AUTO:
                    for t,side,stage,rate in p.records(p.AUTO,data):self.notice.setText(f'CAN {"AB"[side]} Auto: '+(f'trying {rate/1000:g} kbit/s' if stage==0 else f'found {rate/1000:g} kbit/s' if stage==1 else 'not determined — no valid traffic; check bitrate, wiring and ACK from another node'))
                elif kind==p.Kind.RESPONSE:
                    if len(data)!=14:raise ValueError('Malformed response')
                    request,command,result,t=struct.unpack('<IBBQ',data);self.pending.pop(request,None)
                    profile=self.profile_pending.pop(request,None)
                    if result:self.notice.setText(f'Command {p.Command(command).name} rejected (code {result})')
                    elif profile:
                        value,save=profile;self.profiles[value.channel,value.range]=value
                        if save:self.store().save(self.device_id,list(self.profiles.values()));self.notice.setText('Calibration acknowledged and saved for this device')
            for s in range(2):self.can[s].model.append(rows[s])
            for t,fid,side,state,ack in tx:
                if side<2:self.can[side^1].model.update_tx(fid,state,ack)
            for panel in self.can:
                if panel.scroll.isChecked():panel.table.scrollToBottom()
            latest=0
            for ch,points in enumerate(self.analog):
                if points:
                    a=np.asarray(points);self.curves[ch].setData(a[:,0],a[:,1]);latest=max(latest,a[-1,0])
            if latest and self.last_status and self.last_status[6]:
                self.plots[0].setXRange(latest-self.time_span,latest,padding=0)
            for request,(command,sent) in list(self.pending.items()):
                if time.monotonic()-sent>3:self.pending.pop(request);self.notice.setText(f'Command {command.name} timed out');self.profile_pending.pop(request,None)
        except (ValueError,struct.error,OSError) as exc:self.notice.setText(str(exc))
        self.max_update_ms=max(self.max_update_ms,(time.perf_counter()-start)*1000)

    def closeEvent(self,event):
        if self.worker:self.worker.close()
        event.accept()
