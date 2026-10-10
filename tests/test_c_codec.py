import ctypes as c
from pathlib import Path
import random
import pytest
from desktop import protocol as p

def test_c_python_codec_vectors():
    dll=Path('tmp/codec.dll').resolve()
    if not dll.exists():pytest.skip('Run scripts/test-native.ps1 to build the C codec DLL')
    lib=c.CDLL(str(dll));lib.cs_encode.restype=c.c_size_t
    lib.cs_encode.argtypes=[c.c_void_p,c.c_uint8,c.c_uint32,c.c_void_p,c.c_uint16]
    class Parser(c.Structure):
        _fields_=[('buffer',c.c_uint8*1038),('used',c.c_uint16),('has_seq',c.c_uint8),('last_seq',c.c_uint32),('bad_crc',c.c_uint32),('bad_header',c.c_uint32),('gaps',c.c_uint32)]
    callback=c.CFUNCTYPE(None,c.c_uint8,c.c_uint32,c.c_void_p,c.c_uint16,c.c_void_p)
    seen=[]
    @callback
    def receive(kind,seq,data,length,ctx):seen.append((kind,seq,c.string_at(data,length)))
    lib.cs_feed.argtypes=[c.POINTER(Parser),c.c_void_p,c.c_size_t,callback,c.c_void_p]
    parser=Parser();rng=random.Random(47);out=c.create_string_buffer(1038)
    stream=bytearray()
    expected=[]
    for seq in range(60):
        data=rng.randbytes(seq*13%1025);kind=1+seq%9
        length=lib.cs_encode(out,kind,seq,data,len(data))
        assert out.raw[:length]==p.encode(kind,seq,data)
        stream.extend(out.raw[:length]);expected.append((kind,seq,data))
    stream[:0]=b'junkCS\x01\x03\xff\xff\0\0\0\0'
    while stream:
        n=rng.randrange(1,80);chunk=bytes(stream[:n]);del stream[:n];lib.cs_feed(c.byref(parser),chunk,len(chunk),receive,None)
    assert seen==expected and parser.bad_header==1 and parser.gaps==0
    broken=bytearray(p.encode(3,60,b'bad'));broken[-1]^=1
    data=bytes(broken)+p.encode(3,61,b'good');lib.cs_feed(c.byref(parser),data,len(data),receive,None)
    assert seen[-1]==(3,61,b'good') and parser.bad_crc==1 and parser.gaps==1
