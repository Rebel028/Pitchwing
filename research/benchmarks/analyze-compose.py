"""Original synthetic-signal analysis; no proprietary code needed to analyze saved .f32."""
from pathlib import Path
import json, numpy as np
root=Path(__file__).parent/'results'
m=json.loads((root/'metadata.json').read_text());sr=m['sampleRate'];rows=[]
for case in m['cases']:
    y=np.fromfile(root/case['outputFile'],dtype='<f4').astype(float)
    r=dict(case);r.update(finite=bool(np.isfinite(y).all()),peak=float(abs(y).max()))
    onset=case['inputOnsetSample']
    r['firstAboveRelativePeakSamples']={str(db):int(np.flatnonzero(abs(y)>=max(abs(y))*10**(db/20))[0]-onset) for db in [-60,-40,-20]}
    if case['type']=='impulse':
        e=y*y;c=np.cumsum(e);idx=np.flatnonzero(abs(y)>=max(abs(y))*0.001)
        r.update(onsetMinus60dB=int(idx[0]-onset),peakDelaySamples=int(np.argmax(abs(y))-onset),energyCentroidDelaySamples=float(np.dot(np.arange(len(y))-onset,e)/e.sum()),energyPercentileDelaySamples={str(p):int(np.searchsorted(c,p*c[-1])-onset) for p in [.01,.1,.5,.9,.99]},energyGainDb=float(10*np.log10(e.sum()/.25)))
    else:
        z=y[sr:2*sr];n=2**20;F=abs(np.fft.rfft(z*np.hanning(len(z)),n));f=np.fft.rfftfreq(n,1/sr)
        if case['type']=='sine110':
            peak=int(np.argmax(F));a,b,c=np.log(F[peak-1:peak+2]+1e-300);offset=.5*(a-c)/(a-2*b+c);freq=(peak+offset)*sr/n;expected=110*2**(case['shift']/12)
            coverage=(abs(f-expected)<3)
            r.update(expectedHz=expected,peakHz=float(freq),peakPitchErrorCents=float(1200*np.log2(freq/expected)),targetBandEnergyFraction=float(np.sum(F[coverage]**2)/np.sum(F**2)),steadyRms=float(np.sqrt(np.mean(z*z))))
        elif case['type']=='chord':
            targets=np.array([f0*h*2**(case['shift']/12) for f0 in [82.406889,123.470825,164.813778,207.652349,246.941651,329.627557] for h in range(1,7)])
            coverage=np.min(abs(f[:,None]-targets),axis=1)<3
            r.update(targetHarmonicBandEnergyFraction=float(np.sum(F[coverage]**2)/np.sum(F**2)),steadyRms=float(np.sqrt(np.mean(z*z))))
        else:
            peaks=[]
            for a,b in [(.6,.9),(1.6,1.9)]:
                s=y[int(a*sr):int(b*sr)];ff=abs(np.fft.rfft(s*np.hanning(len(s)),n));peaks.append(float(f[np.argmax(ff)]))
            r['prePostPeakHz']=peaks;r['transitionMaxFirstDifference']=float(np.max(abs(np.diff(y[48000:52800]))))
            r['transitionPeak']=float(np.max(abs(y[48000:52800])))
    rows.append(r)
(root/'analysis.json').write_text(json.dumps({'method':'48 kHz; impulse thresholds relative to peak, energy excludes no samples; Hann-window FFT on last 1 s, zero-padded to 2^20. Target bands +/-3 Hz; descriptive metrics only, not quality scores.', 'cases':rows},indent=2)+'\n')
for r in rows:
    if r['type']=='impulse':print(r['name'], 'onset',r['onsetMinus60dB'],'peak',r['peakDelaySamples'],'centroid',round(r['energyCentroidDelaySamples'],2),'90%',r['energyPercentileDelaySamples']['0.9'])
    elif r['type']=='sine110':print(r['name'],'Hz',round(r['peakHz'],4),'cents',round(r['peakPitchErrorCents'],3),'band',round(r['targetBandEnergyFraction'],5))
    elif r['type']=='chord':print(r['name'],'band',round(r['targetHarmonicBandEnergyFraction'],5))
    else:print(r['name'],r['prePostPeakHz'])
