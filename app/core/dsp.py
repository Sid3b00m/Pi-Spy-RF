"""Software demodulation for radios with no rtl_fm-style helper.

rtl_fm covers RTL dongles and is what the decode path already shells out to.
A HackRF has no packaged equivalent on any distro install.sh supports, so its
IQ is pulled from hackrf_transfer and demodulated here instead.

Three things shape the design:

* The chain is two-stage. Running a real FIR at 2 Msps is far too slow in numpy
  on a Pi, so a boxcar decimation drops the rate first and the channel filter
  runs at the much lower IF rate. A boxcar's nulls land on exactly the points
  that alias when decimating by an integer, which is what makes it usable here.
* Nothing iterates in Python per sample. An IIR de-emphasis would be a
  per-sample loop at IF rate, so it is approximated by its truncated
  exponential impulse response and run as an FIR instead.
* Every stage carries its remainder across calls, so the output depends on the
  sample stream alone and not on how a USB read happened to split it. Without
  that, each read boundary loses a few samples and clicks.

Everything here is a pure function or a small stateful block, so tests drive it
with synthesised signals rather than hardware.
"""
from __future__ import annotations

import numpy as np

# Audio comes out at IF rate / AUDIO_DECIM.
AUDIO_DECIM = 5

# Broadcast FM in most of the world; 50 us in ITU region 1 is close enough that
# it is not worth a config knob for a monitoring receiver.
DEEMPHASIS_TAU_S = 75e-6

SOFT_MODES = ("nbfm", "wbfm", "am")

# Peak deviation each FM mode is scaled against, so full deviation lands at full
# scale instead of the -28 dBFS a raw discriminator would hand back.
DEVIATION_HZ = {"nbfm": 5_000.0, "wbfm": 75_000.0}


def lowpass_taps(cutoff_hz: float, sample_rate: float, num_taps: int = 63) -> np.ndarray:
    """Windowed-sinc low pass. An odd tap count keeps the delay a whole sample."""
    num_taps = int(num_taps)
    if num_taps % 2 == 0:
        num_taps += 1
    fc = max(1e-6, min(0.5 - 1e-6, float(cutoff_hz) / float(sample_rate)))
    n = np.arange(num_taps, dtype=np.float64) - (num_taps - 1) / 2.0
    taps = np.sinc(2 * fc * n) * np.hamming(num_taps)
    return (taps / np.sum(taps)).astype(np.float32)


def deemphasis_taps(tau_s: float, sample_rate: float, max_taps: int = 64) -> np.ndarray:
    """FIR standing in for the usual one-pole de-emphasis.

    Truncated where the impulse response has decayed to 1e-4, then normalised so
    the truncation does not shift DC gain.
    """
    dt = 1.0 / float(sample_rate)
    alpha = dt / (float(tau_s) + dt)
    decay = 1.0 - alpha
    if decay <= 0.0:
        return np.ones(1, dtype=np.float32)
    length = int(np.ceil(np.log(1e-4) / np.log(decay)))
    length = max(4, min(int(max_taps), length))
    taps = alpha * decay ** np.arange(length, dtype=np.float64)
    return (taps / np.sum(taps)).astype(np.float32)


def iq_from_int8(raw: bytes) -> np.ndarray:
    """hackrf_transfer writes interleaved signed 8-bit I/Q."""
    buf = np.frombuffer(raw, dtype=np.int8).astype(np.float32) / 128.0
    if buf.size % 2:
        buf = buf[:-1]
    return (buf[0::2] + 1j * buf[1::2]).astype(np.complex64)


def iq_from_uint8(raw: bytes) -> np.ndarray:
    """rtl_sdr writes interleaved unsigned 8-bit I/Q centred on 127.5."""
    buf = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 127.5) / 127.5
    if buf.size % 2:
        buf = buf[:-1]
    return (buf[0::2] + 1j * buf[1::2]).astype(np.complex64)


def boxcar_decimate(samples: np.ndarray, factor: int) -> np.ndarray:
    """Average groups of `factor`, discarding a trailing partial group."""
    factor = int(factor)
    if factor <= 1:
        return samples
    usable = (samples.size // factor) * factor
    if usable == 0:
        return samples[:0]
    return samples[:usable].reshape(-1, factor).mean(axis=1)


class BoxcarDecimator:
    """Streaming boxcar_decimate: the partial group is carried, not dropped."""

    def __init__(self, factor: int, *, complex_input: bool = True) -> None:
        self.factor = max(1, int(factor))
        self._dtype = np.complex64 if complex_input else np.float32
        self._tail = np.zeros(0, dtype=self._dtype)

    def process(self, samples: np.ndarray) -> np.ndarray:
        if self.factor <= 1:
            return samples
        data = np.concatenate([self._tail, samples]) if self._tail.size else samples
        usable = (data.size // self.factor) * self.factor
        self._tail = np.array(data[usable:], dtype=self._dtype)
        if usable == 0:
            return data[:0]
        return data[:usable].reshape(-1, self.factor).mean(axis=1)


class FirFilter:
    """Overlap-save FIR, so consecutive chunks join without a seam."""

    def __init__(self, taps: np.ndarray, *, complex_input: bool = True) -> None:
        self.taps = np.asarray(taps)
        dtype = np.complex64 if complex_input else np.float32
        self._tail = np.zeros(max(0, self.taps.size - 1), dtype=dtype)

    def process(self, samples: np.ndarray) -> np.ndarray:
        if samples.size == 0:
            return samples
        if self.taps.size <= 1:
            return samples * self.taps[0] if self.taps.size else samples
        padded = np.concatenate([self._tail, samples])
        self._tail = padded[-(self.taps.size - 1):]
        return np.convolve(padded, self.taps, mode="valid")


class DcBlock:
    """Removes the slow mean an FM discriminator leaves behind.

    Runs on fixed frames and buffers the remainder, so a given sample stream
    gives the same result however it arrives.
    """

    def __init__(self, frame: int = 1024, alpha: float = 0.25) -> None:
        self.frame = max(1, int(frame))
        self.alpha = float(alpha)
        self._mean = 0.0
        self._tail = np.zeros(0, dtype=np.float32)

    def process(self, samples: np.ndarray) -> np.ndarray:
        data = np.concatenate([self._tail, samples]) if self._tail.size else samples
        usable = (data.size // self.frame) * self.frame
        self._tail = np.array(data[usable:], dtype=np.float32)
        if usable == 0:
            return np.zeros(0, dtype=np.float32)
        frames = np.array(data[:usable], dtype=np.float32).reshape(-1, self.frame)
        out = np.empty_like(frames)
        for i in range(frames.shape[0]):
            self._mean += self.alpha * (float(frames[i].mean()) - self._mean)
            out[i] = frames[i] - self._mean
        return out.reshape(-1)


def fm_discriminate(samples: np.ndarray, previous: complex) -> tuple[np.ndarray, complex]:
    """Angle of the sample-to-sample product: the standard quadrature detector."""
    if samples.size == 0:
        return np.zeros(0, dtype=np.float32), previous
    prior = np.empty_like(samples)
    prior[0] = previous
    prior[1:] = samples[:-1]
    return np.angle(samples * np.conj(prior)).astype(np.float32), complex(samples[-1])


def to_pcm16(audio: np.ndarray, gain: float = 1.0) -> bytes:
    """Clip rather than wrap, so an overdriven signal distorts instead of tearing."""
    if audio.size == 0:
        return b""
    scaled = np.clip(np.asarray(audio, dtype=np.float32) * float(gain), -1.0, 1.0) * 32767.0
    return scaled.astype("<i2").tobytes()


class SoftDemodulator:
    """IQ bytes in, 16-bit mono PCM out, holding filter state between chunks.

    The caller picks `if_decim` so that sample_rate / if_decim lands on a usable
    IF; the audio rate then falls out as that divided by AUDIO_DECIM.
    """

    def __init__(
        self,
        *,
        mode: str,
        sample_rate: float,
        if_decim: int,
        gain: float = 1.0,
        signed: bool = True,
        deviation_hz: float | None = None,
    ) -> None:
        mode = (mode or "nbfm").lower()
        if mode not in SOFT_MODES:
            raise ValueError(f"software demodulation supports {SOFT_MODES}, not {mode!r}")
        self.mode = mode
        self.sample_rate = float(sample_rate)
        self.if_decim = max(1, int(if_decim))
        self.if_rate = self.sample_rate / self.if_decim
        self.audio_rate = int(round(self.if_rate / AUDIO_DECIM))
        self.gain = float(gain)
        self.deviation_hz = float(deviation_hz or DEVIATION_HZ.get(mode, 5_000.0))
        self._signed = bool(signed)
        self._remainder = b""
        self._previous = complex(0)

        self._if_decimator = BoxcarDecimator(self.if_decim, complex_input=True)
        # Broadcast FM occupies ~200 kHz; anything narrowband fits well inside 16.
        channel_hz = 90_000.0 if mode == "wbfm" else 8_000.0
        self._channel = FirFilter(lowpass_taps(channel_hz, self.if_rate), complex_input=True)
        self._audio_decimator = BoxcarDecimator(AUDIO_DECIM, complex_input=False)

        if mode == "am":
            audio_taps = lowpass_taps(4_000.0, self.audio_rate)
        else:
            audio_taps = deemphasis_taps(DEEMPHASIS_TAU_S, self.audio_rate)
        self._audio = FirFilter(audio_taps, complex_input=False)
        self._dc = DcBlock()

    def reset(self) -> None:
        self._remainder = b""
        self._previous = complex(0)

    def process(self, raw: bytes) -> bytes:
        data = self._remainder + raw
        # One IQ pair is two bytes; hold back a stray odd byte for the next chunk.
        usable = len(data) - (len(data) % 2)
        self._remainder = data[usable:]
        data = data[:usable]
        if not data:
            return b""

        iq = iq_from_int8(data) if self._signed else iq_from_uint8(data)
        iq = self._if_decimator.process(iq).astype(np.complex64)
        if iq.size == 0:
            return b""
        iq = self._channel.process(iq)

        if self.mode == "am":
            baseband = np.abs(iq).astype(np.float32)
        else:
            baseband, self._previous = fm_discriminate(iq, self._previous)
            # Radians per sample -> Hz -> fraction of peak deviation.
            scale = self.if_rate / (2.0 * np.pi * self.deviation_hz)
            baseband = (baseband * np.float32(scale)).astype(np.float32)

        audio = self._audio_decimator.process(baseband).astype(np.float32)
        audio = self._audio.process(audio)
        audio = self._dc.process(audio)
        return to_pcm16(audio, self.gain)
