import random
import struct
import pytest
from desktop import protocol as p

def test_fragmentation_coalescing_noise_and_crc():
    rng=random.Random(13)
    source=[p.encode(p.Kind.CAN_RX,i,bytes(rng.randrange(256) for _ in range(i%70))) for i in range(100)]
    stream=b'noise'+b''.join(source)
    parser=p.Parser();packets=[]
    while stream:
        n=rng.randrange(1,40);packets+=parser.feed(stream[:n]);stream=stream[n:]
    assert [packet.sequence for packet in packets]==list(range(100))
    assert parser.gaps==0
    damaged=bytearray(p.encode(p.Kind.STATUS,100,b'abcd'));damaged[-1]^=1
    assert [v.sequence for v in parser.feed(damaged+p.encode(p.Kind.STATUS,101,b'x'))]==[101]
    assert parser.bad_crc==1 and parser.gaps==1

def test_length_version_wrap_and_reset():
    parser=p.Parser()
    bad=p.HEADER.pack(b'CS',1,3,65535,0)+b'12345'
    packets=parser.feed(bad+p.encode(3,0xffffffff)+p.encode(3,0))
    assert len(packets)==2 and parser.bad_header==1 and parser.gaps==0
    parser.reset();assert parser.feed(p.encode(3,900))[0].sequence==900
    assert parser.gaps==0
    with pytest.raises(ValueError):p.encode(3,1,b'x'*1025)

def test_record_sizes():
    assert (p.CAN.size,p.TX.size,p.EVENT.size,p.ADC.size,p.RAW.size,p.AUTO.size,p.STATUS.size)==(29,15,22,28,12,14,108)
