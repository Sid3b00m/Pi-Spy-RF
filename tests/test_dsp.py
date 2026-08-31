"""Demodulator tests driven by synthesised signals.

No SDR is involved: an FM or AM waveform is generated with a known tone on it,
pushed through the demodulator, and the recovered audio is checked with an FFT.
That is what makes the HackRF audio path testable on a build host and in CI.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.core.dsp import (
    AUDIO_DECIM,
    BoxcarDecimator,
    DcBlock,
    FirFilter,
    SoftDemodulator,
    boxcar_decimate,
    deemphasis_taps,
    fm_discriminate,
    iq_from_int8,
    iq_from_uint8,
    lowpass_taps,
    to_pcm16,
)

SAMPLE_RATE = 2_000_000.0
IF_DECIM = 8
TONE_HZ = 1_000.0


def _to_int8_bytes(iq: np.ndarray) -> bytes:
    """Quantise complex baseband the way hackrf_transfer hands it over."""
    inter = np.empty(iq.size * 2, dtype=np.float64)
    inter[0::2] = np.real(iq)
    inter[1::2] = np.imag(iq)
    return np.clip(np.round(inter * 120.0), -128, 127).astype(np.int8).tobytes()


def _fm_signal(seconds: float, deviation_hz: float, tone_hz: float = TONE_HZ) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    phase = (deviation_hz / tone_hz) * np.sin(2 * np.pi * tone_hz * t)
    return 0.9 * np.exp(1j * phase)


def _am_signal(seconds: float, depth: float = 0.5, tone_hz: float = TONE_HZ) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return 0.6 * (1.0 + depth * np.sin(2 * np.pi * tone_hz * t)) * np.exp(0j)


def _dominant_hz(pcm: bytes, rate: int) -> float:
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    # Drop the filter warm-up, which is not part of the steady-state tone.
    audio = audio[len(audio) // 4:]
    audio = audio - audio.mean()
    windowed = audio * np.hanning(audio.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    return float(np.fft.rfftfreq(audio.size, 1.0 / rate)[int(np.argmax(spectrum))])


class TestBuildingBlocks:
    def test_lowpass_taps_are_normalised_and_symmetric(self):
        taps = lowpass_taps(8_000.0, 250_000.0, num_taps=63)
        assert taps.size == 63
        assert np.isclose(taps.sum(), 1.0, atol=1e-6)
        assert np.allclose(taps, taps[::-1], atol=1e-7)

    def test_lowpass_tap_count_is_forced_odd(self):
        assert lowpass_taps(1_000.0, 48_000.0, num_taps=32).size == 33

    def test_lowpass_rejects_above_cutoff(self):
        rate = 250_000.0
        taps = lowpass_taps(8_000.0, rate)
        n = np.arange(4096)
        passed = np.convolve(np.sin(2 * np.pi * 1_000.0 * n / rate), taps, mode="valid")
        blocked = np.convolve(np.sin(2 * np.pi * 60_000.0 * n / rate), taps, mode="valid")
        assert passed.std() > 0.6
        assert blocked.std() < 0.02

    def test_deemphasis_has_unity_dc_gain(self):
        taps = deemphasis_taps(75e-6, 50_000.0)
        assert np.isclose(taps.sum(), 1.0, atol=1e-6)
        # It must roll off, not amplify, as frequency climbs.
        assert taps[0] > taps[-1]

    def test_deemphasis_is_bounded_in_length(self):
        assert deemphasis_taps(75e-6, 1_000_000.0, max_taps=64).size <= 64

    def test_iq_from_int8_scales_to_unit_range(self):
        raw = np.array([127, -128, 0, 64], dtype=np.int8).tobytes()
        iq = iq_from_int8(raw)
        assert iq.size == 2
        assert np.isclose(iq[0].real, 127 / 128.0, atol=1e-6)
        assert np.isclose(iq[0].imag, -1.0, atol=1e-6)

    def test_iq_from_uint8_centres_on_zero(self):
        raw = np.array([128, 128, 255, 0], dtype=np.uint8).tobytes()
        iq = iq_from_uint8(raw)
        assert abs(iq[0]) < 0.01
        assert np.isclose(iq[1].real, 1.0, atol=0.01)

    def test_iq_conversion_drops_an_unpaired_sample(self):
        assert iq_from_int8(np.array([1, 2, 3], dtype=np.int8).tobytes()).size == 1

    def test_boxcar_decimate_averages_groups(self):
        out = boxcar_decimate(np.array([1.0, 3.0, 5.0, 7.0]), 2)
        assert np.allclose(out, [2.0, 6.0])

    def test_boxcar_discards_a_partial_group(self):
        assert boxcar_decimate(np.arange(7.0), 3).size == 2

    def test_boxcar_factor_one_is_a_passthrough(self):
        data = np.arange(5.0)
        assert boxcar_decimate(data, 1) is data

    def test_streaming_boxcar_keeps_the_partial_group(self):
        data = np.arange(12.0, dtype=np.float32)

        whole = BoxcarDecimator(4, complex_input=False).process(data)
        streamed = BoxcarDecimator(4, complex_input=False)
        pieces = [streamed.process(data[i:i + 3]) for i in range(0, data.size, 3)]

        assert np.allclose(whole, np.concatenate(pieces))

    def test_streaming_boxcar_factor_one_is_a_passthrough(self):
        data = np.arange(4.0, dtype=np.float32)
        assert BoxcarDecimator(1, complex_input=False).process(data) is data

    def test_fir_chunking_matches_one_shot(self):
        taps = lowpass_taps(5_000.0, 100_000.0, num_taps=31)
        data = np.random.default_rng(7).normal(size=4096).astype(np.float32)

        whole = FirFilter(taps, complex_input=False).process(data)
        chunked = FirFilter(taps, complex_input=False)
        pieces = [chunked.process(data[i:i + 512]) for i in range(0, data.size, 512)]

        assert np.allclose(whole, np.concatenate(pieces), atol=1e-4)

    def test_fir_on_empty_input(self):
        f = FirFilter(lowpass_taps(1_000.0, 48_000.0), complex_input=False)
        assert f.process(np.zeros(0, dtype=np.float32)).size == 0

    def test_dc_block_removes_a_constant_offset(self):
        block = DcBlock(frame=256, alpha=0.5)
        data = np.full(512, 0.25, dtype=np.float32)
        for _ in range(30):
            out = block.process(data)
        assert abs(float(out.mean())) < 1e-3

    def test_dc_block_buffers_below_one_frame(self):
        block = DcBlock(frame=256)
        assert block.process(np.zeros(100, dtype=np.float32)).size == 0
        assert block.process(np.zeros(200, dtype=np.float32)).size == 256

    def test_dc_block_is_independent_of_chunking(self):
        data = (np.linspace(-1.0, 1.0, 4096) + 0.3).astype(np.float32)

        whole = DcBlock(frame=256).process(data)
        chunked = DcBlock(frame=256)
        pieces = [chunked.process(data[i:i + 300]) for i in range(0, data.size, 300)]

        assert np.allclose(whole, np.concatenate(pieces), atol=1e-6)

    def test_fm_discriminate_recovers_a_constant_rotation(self):
        rate = 250_000.0
        offset = 3_000.0
        n = np.arange(2048)
        iq = np.exp(2j * np.pi * offset * n / rate).astype(np.complex64)
        angles, last = fm_discriminate(iq, complex(iq[0]))
        recovered = float(np.median(angles)) * rate / (2 * np.pi)
        assert abs(recovered - offset) < 5.0
        assert last == complex(iq[-1])

    def test_fm_discriminate_carries_state_between_chunks(self):
        iq = np.exp(2j * np.pi * 0.01 * np.arange(64)).astype(np.complex64)
        whole, _ = fm_discriminate(iq, complex(iq[0]))
        first, carry = fm_discriminate(iq[:32], complex(iq[0]))
        second, _ = fm_discriminate(iq[32:], carry)
        assert np.allclose(whole, np.concatenate([first, second]), atol=1e-6)

    def test_to_pcm16_clips_instead_of_wrapping(self):
        pcm = np.frombuffer(to_pcm16(np.array([2.0, -2.0], dtype=np.float32)), dtype="<i2")
        assert pcm[0] == 32767
        assert pcm[1] == -32767

    def test_to_pcm16_on_empty_input(self):
        assert to_pcm16(np.zeros(0, dtype=np.float32)) == b""


class TestSoftDemodulator:
    def test_rejects_a_mode_it_cannot_handle(self):
        with pytest.raises(ValueError, match="usb"):
            SoftDemodulator(mode="usb", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM)

    def test_reports_derived_rates(self):
        demod = SoftDemodulator(mode="nbfm", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM)
        assert demod.if_rate == SAMPLE_RATE / IF_DECIM
        assert demod.audio_rate == int(SAMPLE_RATE / IF_DECIM / AUDIO_DECIM)

    def test_nbfm_recovers_the_modulating_tone(self):
        demod = SoftDemodulator(mode="nbfm", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM)
        pcm = demod.process(_to_int8_bytes(_fm_signal(0.3, deviation_hz=5_000.0)))
        assert abs(_dominant_hz(pcm, demod.audio_rate) - TONE_HZ) < 25.0

    def test_wbfm_recovers_the_modulating_tone(self):
        demod = SoftDemodulator(mode="wbfm", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM)
        pcm = demod.process(_to_int8_bytes(_fm_signal(0.3, deviation_hz=50_000.0)))
        assert abs(_dominant_hz(pcm, demod.audio_rate) - TONE_HZ) < 25.0

    def test_am_recovers_the_modulating_tone(self):
        demod = SoftDemodulator(mode="am", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM)
        pcm = demod.process(_to_int8_bytes(_am_signal(0.3)))
        assert abs(_dominant_hz(pcm, demod.audio_rate) - TONE_HZ) < 25.0

    def test_full_deviation_reaches_most_of_full_scale(self):
        """Scaling by peak deviation is what keeps the audio from being inaudible."""
        demod = SoftDemodulator(mode="nbfm", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM)
        pcm = demod.process(_to_int8_bytes(_fm_signal(0.3, deviation_hz=5_000.0)))
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
        peak = np.abs(audio[audio.size // 4:]).max() / 32767.0
        assert 0.2 < peak <= 1.0

    def test_streaming_in_chunks_matches_one_shot(self):
        """A read boundary must not lose samples, or the stream clicks."""
        raw = _to_int8_bytes(_fm_signal(0.2, deviation_hz=5_000.0))

        whole = SoftDemodulator(mode="nbfm", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM)
        streamed = SoftDemodulator(mode="nbfm", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM)

        expected = whole.process(raw)
        step = 8192
        got = b"".join(streamed.process(raw[i:i + step]) for i in range(0, len(raw), step))

        assert got == expected

    def test_odd_byte_counts_are_carried_across_chunks(self):
        """A USB read can split an I/Q pair down the middle."""
        raw = _to_int8_bytes(_fm_signal(0.05, deviation_hz=5_000.0))

        whole = SoftDemodulator(mode="nbfm", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM)
        streamed = SoftDemodulator(mode="nbfm", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM)

        expected = whole.process(raw)
        got = streamed.process(raw[:4097]) + streamed.process(raw[4097:])

        assert got == expected

    def test_empty_input_produces_no_audio(self):
        demod = SoftDemodulator(mode="nbfm", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM)
        assert demod.process(b"") == b""

    def test_a_single_byte_is_buffered_not_dropped(self):
        demod = SoftDemodulator(mode="nbfm", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM)
        assert demod.process(b"\x01") == b""

    def test_reset_clears_carried_state(self):
        raw = _to_int8_bytes(_fm_signal(0.05, deviation_hz=5_000.0))
        demod = SoftDemodulator(mode="nbfm", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM)
        demod.process(raw[:1])
        demod.reset()
        assert demod._remainder == b""
        assert demod._previous == complex(0)

    def test_unsigned_input_is_supported_for_rtl_style_iq(self):
        iq = _fm_signal(0.1, deviation_hz=5_000.0)
        inter = np.empty(iq.size * 2, dtype=np.float64)
        inter[0::2] = np.real(iq)
        inter[1::2] = np.imag(iq)
        raw = np.clip(np.round(inter * 120.0) + 127.5, 0, 255).astype(np.uint8).tobytes()

        demod = SoftDemodulator(
            mode="nbfm", sample_rate=SAMPLE_RATE, if_decim=IF_DECIM, signed=False
        )
        assert abs(_dominant_hz(demod.process(raw), demod.audio_rate) - TONE_HZ) < 30.0
