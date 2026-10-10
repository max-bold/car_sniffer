import numpy as np
import pytest
from desktop.calibration import Profile,ProfileStore,dc_point,sine_profile

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
    with pytest.raises(ValueError):dc_point([1000,1100]*80,2)

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
