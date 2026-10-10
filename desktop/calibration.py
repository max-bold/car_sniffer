"""Per-device monotonic tables and conservative sine identification."""
from dataclasses import dataclass, asdict
import json
from pathlib import Path
import struct
import numpy as np

@dataclass
class LinearProfile:
    channel: int
    range: int
    version: int
    zero: float
    gain: float
    model: str = 'linear'

    def validate(self):
        if not 0<=self.channel<8 or self.range not in (0,1) or not 1<=self.version<=0xffffffff:
            raise ValueError('Invalid channel, range or version')
        if self.model!='linear' or not np.isfinite([self.zero,self.gain]).all() or not 2<self.zero<4093 or not 0<self.gain<=.1:
            raise ValueError('Invalid zero or gain')
        return self

    def convert(self,raw):
        self.validate();a=np.asarray(raw,dtype=float)
        return (a-self.zero)*self.gain,(a<0)|(a>4095)

def linear_profile(channel,range_,zero_raw,reference_raw,reference_volts,version=1):
    zero=dc_point(zero_raw,0)[0]
    high=dc_point(reference_raw,reference_volts)[0]
    if not 0<reference_volts<=(3.3,15)[range_] or high-zero<100:
        raise ValueError('Reference voltage or ADC span is too small/invalid')
    return LinearProfile(channel,range_,version,zero,reference_volts/(high-zero)).validate()

def profile_command(profile):
    from .protocol import Command
    profile.validate()
    if isinstance(profile,LinearProfile):
        return Command.LINEAR_PROFILE,struct.pack('<BBIff',profile.channel,profile.range,profile.version,profile.zero,profile.gain)
    return Command.PROFILE,struct.pack('<BBIB',profile.channel,profile.range,profile.version,len(profile.points))+b''.join(struct.pack('<Hf',int(raw),v) for raw,v in profile.points)

@dataclass
class Profile:
    channel: int
    range: int
    version: int
    points: list

    def validate(self):
        a = np.asarray(self.points, dtype=float)
        if not 0 <= self.channel < 8 or self.range not in (0, 1):
            raise ValueError('Invalid channel/range')
        if a.ndim != 2 or a.shape[1] != 2 or not 2 <= len(a) <= 32 or not np.isfinite(a).all():
            raise ValueError('Require 2..32 finite calibration points')
        if np.any(np.diff(a[:, 0]) < 2) or np.any(np.diff(a[:, 1]) <= 0):
            raise ValueError('Raw values must increase by at least 2 counts; voltage must increase')
        if a[0, 0] < 0 or a[-1, 0] > 4095 or a[0, 1] < 0 or a[-1, 1] > (3.3, 15.)[self.range]:
            raise ValueError('Point outside allowed range')
        if not 1 <= self.version <= 0xffffffff:
            raise ValueError('Invalid profile version')
        return self

    def convert(self, raw):
        self.validate()
        a = np.asarray(self.points)
        r = np.asarray(raw)
        volts = np.interp(r, a[:, 0], a[:, 1])
        outside = (r < a[0, 0]) | (r > a[-1, 0])
        return np.where(outside, np.nan, volts), outside

def dc_point(raw, reference_volts, max_std=3.):
    raw = np.asarray(raw, dtype=float)
    if len(raw) < 160 or not np.isfinite(raw).all():
        raise ValueError('Collect at least 160 valid raw samples')
    if raw.min() <= 2 or raw.max() >= 4093:
        raise ValueError('Clipping: point rejected')
    if raw.std() > max_std:
        raise ValueError('Unstable voltage: point rejected')
    if not np.isfinite(reference_volts) or reference_volts < 0:
        raise ValueError('Invalid reference voltage')
    return [float(raw.mean()), float(reference_volts)]

def sine_profile(times_us, raw, frequency, amplitude, definition, offset, channel, range_, version=1):
    """Identify a static monotonic transfer using known sine time/offset/amplitude.

    Phase comes from the fundamental (invariant under a static monotonic transfer).
    Delay is absorbed into phase. Rising/falling branches must agree. No extrapolation.
    """
    t = np.asarray(times_us, dtype=float) * 1e-6
    r = np.asarray(raw, dtype=float)
    peak = amplitude / 2 if definition == 'peak-to-peak' else amplitude * np.sqrt(2) if definition == 'RMS' else amplitude
    if definition not in ('peak', 'peak-to-peak', 'RMS'):
        raise ValueError('Unknown amplitude definition')
    if not 0 < frequency <= 20 or not np.isfinite([frequency, peak, offset]).all() or peak <= 0:
        raise ValueError('Sine must be 0..20 Hz with positive amplitude')
    if offset - peak < 0 or offset + peak > (3.3, 15.)[range_]:
        raise ValueError('Entire sine must remain in the input range')
    if len(t) != len(r) or len(t) < 320 or not np.isfinite(t).all() or not np.isfinite(r).all():
        raise ValueError('Insufficient or invalid samples')
    t = t - t[0]
    dt = np.diff(t)
    if np.any(dt <= 0) or np.max(abs(dt - .000625)) > .00005:
        raise ValueError('Raw stream has gaps or incorrect sample timing')
    cycles = int(t[-1] * frequency)
    if cycles < 5:
        raise ValueError('Collect at least five full periods')
    # Exclude incomplete final period so the fundamental is not biased by leakage.
    keep = t < cycles / frequency
    t, r = t[keep], r[keep]
    if r.min() <= 2 or r.max() >= 4093:
        raise ValueError('Clipping: sine rejected')
    w = 2 * np.pi * frequency * t
    design = np.column_stack([np.ones(len(t)), np.sin(w), np.cos(w)])
    coef = np.linalg.lstsq(design, r, rcond=None)[0]
    phase = np.arctan2(coef[2], coef[1])
    theta = w + phase
    reference = offset + peak * np.sin(theta)
    rising = np.cos(theta) > 0
    edges = np.linspace(np.quantile(r, .02), np.quantile(r, .98), 17)
    points, residuals = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (r >= lo) & (r < hi)
        up, down = mask & rising, mask & ~rising
        if min(up.sum(), down.sum()) < 5:
            raise ValueError('Insufficient coverage of both sine branches')
        if abs(np.mean(reference[up]) - np.mean(reference[down])) > max(.02, peak * .035):
            raise ValueError('Rising/falling mismatch: dynamic or unstable characteristic')
        points.append([float(np.mean(r[mask])), float(np.mean(reference[mask]))])
        residuals.extend(reference[mask] - np.mean(reference[mask]))
    p = Profile(channel, range_, version, points).validate()
    predicted, outside = p.convert(r)
    if np.nanstd(predicted - reference) > max(.025, peak * .035):
        raise ValueError('Noise or cycle instability too large')
    if points[-1][1] - points[0][1] < peak * 1.6:
        raise ValueError('Insufficient amplitude coverage')
    return p

class ProfileStore:
    def __init__(self, path):
        self.path = Path(path)

    def _read(self, device_id):
        if not self.path.exists():
            return {'schema':1,'device_id':device_id,'profiles':[],'settings':{}}
        d=json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(d,dict) or d.get('schema')!=1 or d.get('device_id')!=device_id:
            raise ValueError('Calibration file belongs to another device or schema')
        return d

    def _write(self, content):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(content, indent=2), encoding='utf-8')
        temp.replace(self.path)

    def save(self, device_id, profiles):
        for p in profiles:
            p.validate()
        content=self._read(device_id)
        content['profiles']=[asdict(p) for p in profiles]
        self._write(content)

    def settings(self, device_id):
        settings=self._read(device_id).get('settings',{})
        if not settings:return {}
        channels=settings.get('channels',[]);rates=settings.get('rates',[])
        if len(channels)!=8 or len(rates)!=2 or any(rate not in (0,83333,100000,125000,250000,500000,1000000) for rate in rates):
            raise ValueError('Invalid saved device settings')
        if any(not isinstance(ch,dict) or type(ch.get('enabled')) is not bool or ch.get('range') not in (0,1) for ch in channels):
            raise ValueError('Invalid saved channel settings')
        return settings

    def save_settings(self, device_id, settings):
        content=self._read(device_id);content['settings']=settings;self._write(content)

    def load(self, device_id):
        if not self.path.exists():
            return []
        d = self._read(device_id)
        if not isinstance(d.get('profiles'),list) or len(d['profiles'])>16:
            raise ValueError('Invalid profile list')
        try:profiles = [(LinearProfile(**p) if p.get('model')=='linear' else Profile(**p)).validate() for p in d['profiles']]
        except (TypeError,KeyError,OverflowError) as exc:raise ValueError('Invalid profile data') from exc
        if len({(p.channel, p.range) for p in profiles}) != len(profiles):
            raise ValueError('Duplicate profile')
        return profiles
