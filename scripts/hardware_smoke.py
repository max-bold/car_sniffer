"""Explicit hardware verification; no external CAN transmission and no bridge enable."""
import argparse
from collections import defaultdict
import json
import struct
import time
from pathlib import Path
import serial
import serial.tools.list_ports
from desktop import protocol as p

def run(port=None):
    if not port:
        ports=[v.device for v in serial.tools.list_ports.comports() if v.vid==0x0483 and v.pid==0x5740]
        if len(ports)!=1:raise RuntimeError(f'Expected one Car Sniffer CDC device; found {ports}')
        port=ports[0]
    parser=p.Parser();request=0;received=[]
    with serial.Serial(port,115200,timeout=.02,write_timeout=.3) as stream:
        def read(duration):
            packets=[];end=time.monotonic()+duration
            while time.monotonic()<end:packets.extend(parser.feed(stream.read(max(1,min(stream.in_waiting,8192)))))
            received.extend(packets);return packets
        def command(cmd,args=b''):
            nonlocal request
            request+=1;stream.write(p.encode(p.Kind.COMMAND,request,struct.pack('<IB',request,cmd)+args))
            packets=read(.2)
            replies=[struct.unpack('<IBBQ',v.payload) for v in packets if v.kind==p.Kind.RESPONSE]
            assert any(r[0]==request and r[2]==0 for r in replies),(cmd,replies)
            return packets
        command(p.Command.STATUS)
        command(p.Command.CAPTURE,b'\1')
        packets=read(2)
        analog=defaultdict(list)
        for packet in packets:
            if packet.kind==p.Kind.ADC:
                for row in p.records(p.ADC,packet.payload):analog[row[1]].append(row)
        assert len(analog)==8
        counts={ch:len(rows) for ch,rows in analog.items()}
        for rows in analog.values():assert all(b[0]-a[0]==10000 for a,b in zip(rows,rows[1:]))
        loopback=[]
        for side in (0,1):
            packets=command(p.Command.LOOPBACK_TEST,bytes([side]))+read(.1)
            frames=[r for packet in packets if packet.kind==p.Kind.CAN_RX for r in p.records(p.CAN,packet.payload) if r[3]==side]
            assert any(r[2]==0x321 and r[-1]==b'CS\1\2\3\4\5\6' for r in frames),(side,frames)
            loopback.append(side)
        command(p.Command.CAPTURE,b'\0');packets=read(.2)
        assert not any(v.kind in (p.Kind.ADC,p.Kind.CAN_RX) for v in packets)
        status=[r for v in command(p.Command.STATUS) if v.kind==p.Kind.STATUS for r in p.records(p.STATUS,v.payload)][-1]
        assert status[5]==0 and status[6]==0 and status[7:9]==(0,0)
        assert not parser.bad_crc
        report={'port':port,'device_id':status[4].hex(),'boot_id':status[1],'adc_points_in_2s':counts,
                'adc_step_us':10000,'loopback_sides':loopback,'bridge':False,'capture_after_test':False,
                'bad_crc':parser.bad_crc,'sequence_gaps':parser.gaps,'telemetry_loss':status[2]}
        return report

if __name__=='__main__':
    arg=argparse.ArgumentParser();arg.add_argument('--port');arg.add_argument('--output');args=arg.parse_args()
    report=run(args.port);print(json.dumps(report,indent=2))
    if args.output:Path(args.output).write_text(json.dumps(report,indent=2),encoding='utf-8')
