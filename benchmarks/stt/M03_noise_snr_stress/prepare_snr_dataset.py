#!/usr/bin/env python3

import argparse
import csv
import hashlib
import math
import sys
import wave
from array import array
from pathlib import Path


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[3]

VOICEBANK_DIR = (
    REPO_ROOT
    / "data/stt/voicebank_demand/prepared_15"
)

SOURCE_MANIFEST = VOICEBANK_DIR / "manifest.tsv"

NOISE_WAV = (
    REPO_ROOT
    / "data/stt/ms_snsd/source/MS-SNSD/noise_test/AirConditioner_1.wav"
)

OUTPUT_DIR = (
    REPO_ROOT
    / "data/stt/ms_snsd/mixed"
    / "voicebank_prepared_15"
    / "airconditioner"
)

SNR_LEVELS = [20, 10, 5, 0]


def read_wav(path):
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        sample_width = wf.getsampwidth()
        nframes = wf.getnframes()

        if channels != 1:
            raise RuntimeError(
                "{}: expected mono, got {} channels".format(
                    path, channels
                )
            )

        if sample_rate != 16000:
            raise RuntimeError(
                "{}: expected 16000 Hz, got {}".format(
                    path, sample_rate
                )
            )

        if sample_width != 2:
            raise RuntimeError(
                "{}: expected 16-bit PCM".format(path)
            )

        raw = wf.readframes(nframes)

    samples = array("h")
    samples.frombytes(raw)

    if sys.byteorder != "little":
        samples.byteswap()

    return list(samples), sample_rate


def write_wav(path, samples, sample_rate):
    path.parent.mkdir(parents=True, exist_ok=True)

    pcm = array("h", samples)

    if sys.byteorder != "little":
        pcm.byteswap()

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def remove_dc(samples):
    if not samples:
        return []

    mean = sum(samples) / float(len(samples))

    return [
        float(x) - mean
        for x in samples
    ]


def rms(samples):
    if not samples:
        return 0.0

    return math.sqrt(
        sum(x * x for x in samples)
        / float(len(samples))
    )


def choose_noise_segment(
    noise,
    required_samples,
    sample_id,
):
    """
    Chọn đoạn noise deterministic theo sample_id.

    Cùng một speech sample sẽ dùng chính xác cùng một
    đoạn noise ở SNR 20/10/5/0 dB.
    """

    if not noise:
        raise RuntimeError("Noise WAV is empty")

    if len(noise) < required_samples:
        repeat_count = int(
            math.ceil(
                required_samples / float(len(noise))
            )
        )

        noise = (
            noise * repeat_count
        )[:required_samples]

        return noise, 0

    max_offset = len(noise) - required_samples

    digest = hashlib.sha256(
        sample_id.encode("utf-8")
    ).hexdigest()

    offset = (
        int(digest[:16], 16)
        % (max_offset + 1)
    )

    return (
        noise[offset:offset + required_samples],
        offset,
    )


def mix_at_snr(
    speech,
    noise,
    snr_db,
):
    if len(speech) != len(noise):
        raise RuntimeError(
            "Speech/noise length mismatch"
        )

    # Remove tiny DC components before power measurement.
    speech_ac = remove_dc(speech)
    noise_ac = remove_dc(noise)

    speech_rms = rms(speech_ac)
    noise_rms = rms(noise_ac)

    if speech_rms <= 0.0:
        raise RuntimeError("Speech RMS is zero")

    if noise_rms <= 0.0:
        raise RuntimeError("Noise RMS is zero")

    # SNR = 20 * log10(speech_rms / noise_rms)
    target_noise_rms = (
        speech_rms
        / (10.0 ** (snr_db / 20.0))
    )

    noise_scale = (
        target_noise_rms
        / noise_rms
    )

    mixed = [
        s + noise_scale * n
        for s, n in zip(
            speech_ac,
            noise_ac,
        )
    ]

    # Prevent clipping using one global gain.
    # Scaling the whole mixture preserves SNR.
    peak = max(
        abs(x)
        for x in mixed
    )

    mix_gain = 1.0

    if peak > 32767.0:
        mix_gain = (
            32767.0 / peak
        )

        mixed = [
            x * mix_gain
            for x in mixed
        ]

    output = []

    for x in mixed:
        value = int(round(x))

        value = max(
            -32768,
            min(32767, value),
        )

        output.append(value)

    measured_snr_db = (
        20.0
        * math.log10(
            speech_rms
            / (noise_rms * noise_scale)
        )
    )

    return {
        "samples": output,
        "speech_rms": speech_rms,
        "noise_rms": noise_rms,
        "noise_scale": noise_scale,
        "mix_gain": mix_gain,
        "measured_snr_db": measured_snr_db,
    }


def snr_dir_name(snr_db):
    if snr_db < 0:
        return "snr_m{:02d}".format(
            abs(snr_db)
        )

    return "snr{:02d}".format(
        snr_db
    )


def load_manifest():
    rows = []

    with SOURCE_MANIFEST.open(
        "r",
        newline="",
    ) as f:
        reader = csv.DictReader(
            f,
            delimiter="\t",
        )

        required = {
            "sample_id",
            "clean_file",
            "reference",
        }

        fields = set(
            reader.fieldnames or []
        )

        missing = required - fields

        if missing:
            raise RuntimeError(
                "Manifest missing columns: {}".format(
                    ", ".join(sorted(missing))
                )
            )

        for row in reader:
            rows.append(row)

    if not rows:
        raise RuntimeError(
            "Manifest contains no samples"
        )

    return rows


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only generate first N clean samples",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing existing generated WAV files",
    )

    args = parser.parse_args()

    if not SOURCE_MANIFEST.is_file():
        raise RuntimeError(
            "Missing manifest: {}".format(
                SOURCE_MANIFEST
            )
        )

    if not NOISE_WAV.is_file():
        raise RuntimeError(
            "Missing noise: {}".format(
                NOISE_WAV
            )
        )

    manifest_rows = load_manifest()

    if args.limit > 0:
        manifest_rows = manifest_rows[
            :args.limit
        ]

    noise_samples, noise_rate = read_wav(
        NOISE_WAV
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_manifest = (
        OUTPUT_DIR / "manifest.tsv"
    )

    generated_rows = []

    print(
        "========================================"
    )
    print(
        " M03 Controlled SNR Dataset Preparation"
    )
    print(
        "========================================"
    )
    print(
        "Speech samples :",
        len(manifest_rows),
    )
    print(
        "Noise          :",
        NOISE_WAV.name,
    )
    print(
        "Noise duration : {:.3f} s".format(
            len(noise_samples)
            / float(noise_rate)
        )
    )
    print(
        "SNR levels     :",
        SNR_LEVELS,
    )
    print()

    for row in manifest_rows:
        sample_id = row["sample_id"]

        clean_path = (
            VOICEBANK_DIR
            / row["clean_file"]
        )

        speech_samples, speech_rate = (
            read_wav(clean_path)
        )

        if speech_rate != noise_rate:
            raise RuntimeError(
                "Sample rate mismatch"
            )

        noise_segment, noise_offset = (
            choose_noise_segment(
                noise_samples,
                len(speech_samples),
                sample_id,
            )
        )

        for snr_db in SNR_LEVELS:
            result = mix_at_snr(
                speech_samples,
                noise_segment,
                snr_db,
            )

            output_path = (
                OUTPUT_DIR
                / snr_dir_name(snr_db)
                / clean_path.name
            )

            if (
                output_path.exists()
                and not args.overwrite
            ):
                raise RuntimeError(
                    "Output already exists: {}\n"
                    "Use --overwrite to regenerate."
                    .format(output_path)
                )

            write_wav(
                output_path,
                result["samples"],
                speech_rate,
            )

            generated_rows.append({
                "sample_id": sample_id,
                "reference": row["reference"],
                "snr_db": snr_db,
                "noise_type": "AirConditioner",
                "clean_file": str(
                    clean_path.relative_to(
                        REPO_ROOT
                    )
                ),
                "noise_file": str(
                    NOISE_WAV.relative_to(
                        REPO_ROOT
                    )
                ),
                "noise_offset_frames":
                    noise_offset,
                "noise_offset_seconds":
                    "{:.6f}".format(
                        noise_offset
                        / float(noise_rate)
                    ),
                "mixed_file": str(
                    output_path.relative_to(
                        REPO_ROOT
                    )
                ),
                "noise_scale":
                    "{:.10f}".format(
                        result["noise_scale"]
                    ),
                "mix_gain":
                    "{:.10f}".format(
                        result["mix_gain"]
                    ),
                "measured_snr_db":
                    "{:.6f}".format(
                        result[
                            "measured_snr_db"
                        ]
                    ),
            })

            print(
                "{} | {:2d} dB | "
                "measured={:.3f} dB | "
                "noise_scale={:.5f} | "
                "gain={:.5f}".format(
                    sample_id,
                    snr_db,
                    result[
                        "measured_snr_db"
                    ],
                    result["noise_scale"],
                    result["mix_gain"],
                )
            )

    fields = [
        "sample_id",
        "reference",
        "snr_db",
        "noise_type",
        "clean_file",
        "noise_file",
        "noise_offset_frames",
        "noise_offset_seconds",
        "mixed_file",
        "noise_scale",
        "mix_gain",
        "measured_snr_db",
    ]

    with output_manifest.open(
        "w",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            delimiter="\t",
        )

        writer.writeheader()
        writer.writerows(
            generated_rows
        )

    print()
    print(
        "========================================"
    )
    print(
        " DONE"
    )
    print(
        "========================================"
    )
    print(
        "Generated WAV :",
        len(generated_rows),
    )
    print(
        "Output        :",
        OUTPUT_DIR,
    )
    print(
        "Manifest      :",
        output_manifest,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            "ERROR:",
            exc,
            file=sys.stderr,
        )
        sys.exit(1)
