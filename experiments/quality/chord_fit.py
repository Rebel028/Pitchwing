"""Late-window line fit of stationary low chords through one or more live renderers.

usage: python3 experiments/quality/chord_fit.py <renderer> [<renderer> ...]  (run from the repo root)
Prints the fitted energy fraction at -7 and +7 per renderer (evaluate.fit_lines).
"""
import sys, numpy as np, subprocess
sys.path.insert(0, 'experiments/transport')
import evaluate as ev
fs=ev.SAMPLE_RATE; clock=np.arange(round(1.5*fs))/fs
N=ev.NOTES; second=[N["E1"],2*N["B0"],N["E2"]]
bins=sys.argv[1:]
for name,freqs in (('E1+B1+E2',second),('E1 alone',[N['E1']]),('B1 alone',[2*N['B0']]),('E2 alone',[N['E2']]),('B1+E2',second[1:]),('E1+B1',second[:2]),('first chord',[N["B0"],N["F#1"],2*N["B0"]])):
    src=ev.harmonic_sound(clock,freqs,1.0); src*=0.5/np.abs(src).max()
    src.astype('<f8').tofile('/tmp/pw-s3/t.f64')
    out=[]
    for b in bins:
        for st in (-7,7):
            r=2**(st/12)
            subprocess.run([b,'/tmp/pw-s3/t.f64','/tmp/pw-s3/to.f64',str(fs),str(st),'32'],check=True,capture_output=True)
            y=np.fromfile('/tmp/pw-s3/to.f64')[479:479+len(src)]
            lines=[]
            for f in sorted(f*h*r for f in freqs for h in range(1,9)):
                if not lines or f-lines[-1]>0.001: lines.append(f)
            out.append(round(ev.fit_lines(y[int(0.95*fs):int(1.2*fs)],lines)['fitted_ac_energy_fraction'],3))
    print(f'{name:11s}', out)
