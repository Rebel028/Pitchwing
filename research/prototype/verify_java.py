"""Optional comparison to the author's original compiled Java executable.

The third-party JAR is NOT copied into this prototype deliverable. Obtain the
author's reference archive separately; pass --jar /path/to/PitchShiftOcean.jar.
The local Java executable may require --java and --java-lib arguments.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import wave
import numpy as np
from ocean_numpy import render

def read(path):
    with wave.open(str(path)) as handle:
        if handle.getsampwidth()!=2 or handle.getnchannels()!=1:
            raise ValueError("expected mono PCM16")
        return np.frombuffer(handle.readframes(handle.getnframes()),"<i2").astype(float)/32768

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--jar",required=True)
    parser.add_argument("--java",default="java")
    parser.add_argument("--java-lib",default=None)
    args=parser.parse_args()
    root=Path(__file__).resolve().parent/"results"
    root.mkdir(exist_ok=True)
    input_path=root/"reference_input.wav"
    x=np.random.default_rng(81).normal(0,.05,12032)
    with wave.open(str(input_path),"wb") as handle:
        handle.setparams((1,2,48000,0,"NONE","not compressed"))
        handle.writeframes((x*32767).astype("<i2").tobytes())
    x=read(input_path)
    environment=dict(os.environ)
    if args.java_lib:
        environment["LD_LIBRARY_PATH"]=args.java_lib
    rows=[]
    for semitone,pad in [(5,2),(-5,4),(1,8)]:
        ratio=2**(semitone/12)
        output_path=root/f"reference_java_{semitone}_{pad}.wav"
        command=[args.java,"-jar",args.jar,"-i",str(input_path),"-r",str(ratio),
                 "-o",str(output_path),"-b","512","-v","8","-m",str(pad)]
        completed=subprocess.run(command,env=environment,capture_output=True,text=True,check=True)
        j=read(output_path)
        y,_=render(x,ratio,n=512,hop=64,pad=pad)
        y=y[:len(j)]
        error=j-y
        row={"semitones":semitone,"pad":pad,"sample_count":len(j),
             "max_absolute_error":float(np.max(np.abs(error))),
             "rms_error":float(np.sqrt(np.mean(error**2))),
             "correlation":float(np.corrcoef(j,y)[0,1]),
             "java_output_precision":"16-bit PCM", "pcm16_lsb":1/32768}
        rows.append(row)
        # Java arithmetic uses float32, prototype float64; output PCM truncates.
        assert row["max_absolute_error"] < 2/32768, row
    (root/"java_equivalence.json").write_text(json.dumps(rows,indent=2)+"\n")
    print(json.dumps(rows,indent=2))

if __name__=="__main__":
    main()
