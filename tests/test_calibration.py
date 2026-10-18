import numpy as np
import pytest
from desktop.calibration import Profile,ProfileStore,dc_point,sine_profile
from desktop.calibration import LinearProfile,linear_profile,profile_command

def test_profiles_and_no_extrapolation(tmp_path):
    p=Profile(1,1,1,[[100,0],[1000,2],[3000,14]]).validate()
    v,out=p.convert([50,550,2000,3500])
    assert np.isnan(v[0]) and np.isnan(v[-1]) and out.tolist()==[True,False,False,True]
    assert v[1]==1 and v[2]==8
    store=ProfileStore(tmp_path/'cal.json');store.save('board-A',[p])
    assert store.load('board-A')==[p]
    settings={'channels':[{'enabled':True,'range':1} for _ in range(8)],'rates':[500000,250000]}
    store.save_settings('board-A',settings);assert store.load('board-A')==[p]
    store.save('board-A',[p]);assert store.settings('board-A')==settings
    with pytest.raises(ValueError):store.load('board-B')
    for points in ([[100,1],[100,2]],[[100,2],[200,1]],[[100,float('nan')],[200,2]]):
        with pytest.raises(ValueError):Profile(0,0,1,points).validate()

def test_dc_rejects_unstable_and_clipped():
    assert dc_point([1000]*160,2)==[1000.,2.]
    with pytest.raises(ValueError):dc_point([4095]*160,3.3)
    with pytest.raises(ValueError):dc_point([1000,1102]*80,2)

def test_dc_accepts_sample_noise_but_rejects_drifting_mean():
    # 3x measured bench noise, rounded up; mean drift is checked separately.
    noisy=np.tile([970,1030],800)
    assert dc_point(noisy,0)==[1000.,0.]
    with pytest.raises(ValueError,match='raw std'):
        dc_point(np.tile([969,1031],800),0)
    # A 14-count block span from the owner's bench must be accepted too.
    assert dc_point(np.repeat(np.linspace(993,1007,10),160),0)==[1000.,0.]
    drifting=np.repeat(np.linspace(957.5,1042.5,10),160)
    assert drifting.std()<30
    with pytest.raises(ValueError,match='block mean span'):
        dc_point(drifting,0)
    profile=linear_profile(0,1,noisy,noisy+2000,10)
    assert profile.zero==1000 and profile.gain==.005

def test_sine_nonlinearity_phase_delay_noise():
    rng=np.random.default_rng(123)
    t=np.arange(0,2,1/1600)
    v=1.5+np.sin(2*np.pi*5*(t-.013)+.7)
    raw=200+850*v+80*v*v+rng.normal(0,.5,len(v))
    p=sine_profile(t*1e6,raw,5,1,'peak',1.5,0,0)
    pred,out=p.convert(raw)
    assert np.nanmax(abs(pred-v))<.025
    clipped=raw.copy();clipped[50]=4095
    with pytest.raises(ValueError,match='Clipping'):sine_profile(t*1e6,clipped,5,1,'peak',1.5,0,0)
    with pytest.raises(ValueError):sine_profile(t*1e6,raw,5,1,'peak',0,0,0)
    with pytest.raises(ValueError):sine_profile(t[:100]*1e6,raw[:100],5,1,'peak',1.5,0,0)
    bad=raw+200*np.cos(2*np.pi*5*t+.7)
    # A constant delay can be fitted, but time-varying hysteresis cannot.
    bad+=180*np.sin(2*np.pi*5*t+.7)**2*np.sign(np.cos(2*np.pi*5*t+.7))
    with pytest.raises(ValueError):sine_profile(t*1e6,bad,5,1,'peak',1.5,0,0)

def test_sample_transform_precedes_average():
    p=Profile(0,0,1,[[0,0],[1000,1],[2000,3]])
    values,_=p.convert([500,1500])
    center,_=p.convert([1000])
    assert values.mean()==1.25 and center[0]==1

def test_linear_offset_gain_and_device_report(tmp_path):
    import struct
    from desktop.protocol import Command
    p=linear_profile(3,1,[300,301]*800,[2300,2301]*800,10.02,42)
    assert p.zero==300.5 and p.gain==10.02/2000
    values,outside=p.convert([299.5,300.5,2300.5,3300.5])
    assert np.allclose(values,[-p.gain,0,10.02,15.03]) and not outside.any()
    command,payload=profile_command(p)
    assert command==Command.LINEAR_PROFILE
    ch,r,version,zero,gain=struct.unpack('<BBIff',payload)
    assert (ch,r,version,zero)==(3,1,42,300.5) and abs(gain-p.gain)<1e-8
    store=ProfileStore(tmp_path/'report.json');store.save('board',[p]);assert store.load('board')==[p]
    with pytest.raises(ValueError):linear_profile(0,0,[0]*160,[2000]*160,2)
    with pytest.raises(ValueError):linear_profile(0,0,[300]*160,[350]*160,2)
