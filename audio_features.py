"""Extract only audio features (NumPy required); never generates a chart or particle positions.
Input: mono 16-bit PCM WAV (macOS afconvert), optional official Roblox download.
Raw audio stays in ignored build/audio; catalog and normalized envelopes are source.
"""
import argparse
import array
import hashlib
import json
import math
from pathlib import Path
import subprocess
import urllib.request
import wave

import numpy as np




def analyze(path, step=0.1):
    with wave.open(str(path), "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise ValueError("Expected mono 16-bit PCM WAV")
        rate, total = audio.getframerate(), audio.getnframes()
        width = max(1, round(rate * step))
        rms = []
        while True:
            block = audio.readframes(width)
            if not block:
                break
            values = array.array("h", block)
            rms.append(math.sqrt(sum(v*v for v in values) / len(values)) / 32768)
    ordered = sorted(rms)
    reference = max(0.0001, ordered[min(len(ordered)-1, int(len(ordered)*0.95))])
    energy = [round(min(1, v/reference), 4) for v in rms]
    # Centered 46ms spectral windows, 20ms hops. Detect positive spectral change,
    # then local peaks above a 0.5s adaptive median; no regular beat/grid fallback.
    with wave.open(str(path), "rb") as audio:
        signal = np.frombuffer(audio.readframes(total), dtype="<i2").astype(float) / 32768
    onset_step, size = 0.02, 2048
    hop = round(rate * onset_step)
    padded = np.pad(signal, (size//2, size//2))
    window = np.hanning(size)
    previous = np.zeros(size//2+1)
    flux, local_rms = [], []
    for start in range(0, total, hop):
        block = padded[start:start+size]
        spectrum = np.log1p(np.abs(np.fft.rfft(block * window))*10)
        flux.append(float(np.maximum(0, spectrum-previous).sum()))
        local_rms.append(float(np.sqrt(np.mean(block**2))))
        previous = spectrum
    noise_floor = float(np.percentile(flux, 95)) * 0.08
    peaks = []
    for i, value in enumerate(flux):
        threshold = float(np.median(flux[max(0,i-12):i+13]))*1.5 + noise_floor
        if value <= threshold or local_rms[i] < reference*0.06:
            continue
        if value < max(flux[max(0,i-2):i+3]):
            continue
        if peaks and (i-peaks[-1])*onset_step < 0.24:
            if value > flux[peaks[-1]]:
                peaks[-1] = i
        else:
            peaks.append(i)
    onset_reference = max(0.0001, float(np.percentile([flux[i] for i in peaks],95))) if peaks else 1
    onset = [0.0]*len(flux)
    for i in peaks:
        strength = min(1,flux[i]/onset_reference)
        if strength >= 0.08:  # Ignore spectral leakage far below measured attacks.
            onset[i] = round(strength,4)
    return dict(step=step, onsetStep=onset_step, duration=total/rate,
                referenceRms=reference, energy=energy, onset=onset)



def rhythm(path):
    import librosa
    y,sr=librosa.load(str(path),sr=22050,mono=True)
    hop=256
    if len(y)<sr*2 or np.max(np.abs(y))<1e-5:
        return dict(version=1,bpm=0,confidence=0,beats=[],method='librosa 0.11.0 onset correlation/beat_track; estimated')
    envelope=librosa.onset.onset_strength(y=y,sr=sr,hop_length=hop)
    tempo,frames=librosa.beat.beat_track(onset_envelope=envelope,sr=sr,hop_length=hop,trim=False)
    times=librosa.frames_to_time(frames,sr=sr,hop_length=hop)
    intervals=np.diff(times);period=float(np.median(intervals)) if len(intervals) else 0
    consistency=float(np.mean(np.abs(intervals-period)<=period*0.1)) if period else 0
    strength=float(np.mean(np.minimum(1,envelope[frames]/max(1e-9,float(np.percentile(envelope,90)))))) if len(frames) else 0
    lag=round(period*sr/hop);v=np.maximum(0,envelope-np.mean(envelope))
    correlation=float(np.dot(v[:-lag],v[lag:])/max(1e-9,np.linalg.norm(v[:-lag])*np.linalg.norm(v[lag:]))) if 0<lag<len(v) else 0
    confidence=np.clip(consistency*.25+strength*.25+correlation*.5,0,1)
    bpm=float(np.asarray(tempo).reshape(-1)[0])
    if len(times)<8 or not 40<=bpm<=300: confidence=0
    return dict(version=1,bpm=round(bpm,3),confidence=round(float(confidence),4),
                beats=[round(float(t),5) for t in times if 0<=t<len(y)/sr],method='librosa 0.11.0 onset correlation/beat_track; estimated')

