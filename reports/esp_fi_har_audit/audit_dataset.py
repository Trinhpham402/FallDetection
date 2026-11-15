#!/usr/bin/env python3
"""Audit the supplied ESP-Fi-HAR ZIP without executing its Python files.

Uses only the standard library. The MAT reader deliberately accepts only the
uncompressed, little-endian, real double MATLAB v5 matrices found in this ZIP;
unsupported encodings fail explicitly instead of guessing.
"""
import argparse
import array
import ast
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import struct
import sys
import zipfile


def elements(blob, start, end):
    while start < end:
        if end - start < 8:
            raise ValueError("Truncated MAT tag")
        tag, size = struct.unpack_from("<II", blob, start)
        if tag >> 16:
            count = tag >> 16
            if count > 4:
                raise ValueError("Invalid small MAT element")
            yield tag & 0xffff, blob[start + 4:start + 4 + count]
            start += 8
        else:
            stop = start + 8 + size
            if stop > end:
                raise ValueError("Truncated MAT payload")
            yield tag, blob[start + 8:stop]
            start = stop + (-size % 8)
    if start != end:
        raise ValueError("Invalid MAT padding")


def read_mat(blob):
    if len(blob) < 128 or blob[126:128] != b"IM":
        raise ValueError("Expected little-endian MATLAB v5")
    if struct.unpack_from("<H", blob, 124)[0] != 0x100:
        raise ValueError("Unsupported MAT version")
    matrices = {}
    for kind, payload in elements(blob, 128, len(blob)):
        if kind != 14:
            raise ValueError(f"Unsupported MAT element {kind}")
        fields = list(elements(payload, 0, len(payload)))
        if len(fields) != 4:
            raise ValueError("Expected one real dense matrix")
        (ft, flags), (dt, dims), (nt, name), (vt, raw) = fields
        if ft != 6 or len(flags) != 8 or dt != 5 or nt != 1 or vt != 9:
            raise ValueError("Unsupported matrix encoding")
        attributes, reserved = struct.unpack("<II", flags)
        if attributes != 6 or reserved != 0:
            raise ValueError("Expected real, nonlogical mxDOUBLE_CLASS")
        shape = struct.unpack(f"<{len(dims) // 4}i", dims)
        if len(shape) != 2 or min(shape) <= 0 or len(raw) != math.prod(shape) * 8:
            raise ValueError("Invalid dimensions/payload size")
        key = name.decode("ascii")
        if key in matrices:
            raise ValueError("Duplicate matrix name")
        values = array.array("d")
        values.frombytes(raw)
        if sys.byteorder != "little":
            values.byteswap()
        matrices[key] = (shape, values, raw)
    return matrices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with args.zip_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    result = {"source": str(args.zip_path.resolve()), "zip_sha256": digest.hexdigest(),
              "samples": [], "errors": [], "python_syntax": {}, "lfs_pointers": []}
    counts = {key: Counter() for key in ("split", "class", "shape", "variables", "scenario")}
    subject_splits = defaultdict(Counter)
    class_splits = defaultdict(Counter)
    activity_map = defaultdict(set)
    numeric_hashes = defaultdict(list)
    file_hashes = defaultdict(list)
    ids = defaultdict(list)
    loader_classes = ["arm_wave", "fall", "jump", "run", "squat", "turn", "walk"]
    readme_ids = {"run": "1", "fall": "2", "walk": "3", "turn": "4",
                  "jump": "5", "squat": "6", "arm_wave": "7"}
    readme_mismatches = 0
    nonfinite_total = negative_total = zero_total = number_total = 0
    with zipfile.ZipFile(args.zip_path) as archive:
        infos = archive.infolist()
        result["archive_entries"] = len(infos)
        result["uncompressed_bytes"] = sum(item.file_size for item in infos)
        result["duplicate_zip_names"] = [n for n, c in Counter(i.filename for i in infos).items() if c > 1]
        for info in infos:
            if info.is_dir():
                continue
            name = info.filename
            blob = archive.read(info)  # Checks ZIP CRC for every file.
            if blob.startswith(b"version https://git-lfs.github.com/spec/v1"):
                result["lfs_pointers"].append({"path": name, "content": blob.decode()})
            if name.endswith(".py"):
                try:
                    ast.parse(blob.decode("utf-8"), filename=name)
                    result["python_syntax"][name] = "ok (not executed)"
                except SyntaxError as error:
                    result["python_syntax"][name] = str(error)
            if not name.endswith(".mat"):
                continue
            try:
                path = PurePosixPath(name)
                split, label = path.parts[-3:-1]
                scenario, subject, activity, trial = path.stem.split("-")
                matrices = read_mat(blob)
                shape, values, raw = matrices["CSIamp"]
                if shape != (950, 52):
                    raise ValueError(f"Unexpected shape {shape}")
                finite = all(map(math.isfinite, values))
                if not finite:
                    nonfinite_total += sum(not math.isfinite(x) for x in values)
                    raise ValueError("Nonfinite amplitude values")
                n = len(values)
                mean = sum(values) / n
                variance = sum((x - mean) ** 2 for x in values) / n
                zeros = values.count(0.0)
                negatives = sum(x < 0 for x in values)
                # MATLAB column-major order: 950 consecutive times per subcarrier.
                constant_columns = 0
                temporal_change = 0.0
                for column in range(52):
                    offset = column * 950
                    series = values[offset:offset + 950]
                    constant_columns += min(series) == max(series)
                    temporal_change += sum(abs(series[i] - series[i - 1]) for i in range(1, 950))
                record = {"path": name, "split": split, "label": label,
                          "loader_label_index": loader_classes.index(label),
                          "scenario_id": scenario, "subject_id": subject,
                          "filename_activity_id": activity, "trial": int(trial),
                          "variables": sorted(matrices), "shape": list(shape), "dtype": "float64",
                          "min": min(values), "max": max(values), "mean": mean,
                          "std": math.sqrt(variance), "zeros": zeros, "negatives": negatives,
                          "constant_columns": constant_columns,
                          "mean_abs_temporal_change": temporal_change / (52 * 949),
                          "matrix_sha256": hashlib.sha256(raw).hexdigest()}
                result["samples"].append(record)
                for key, value in [("split", split), ("class", label), ("shape", str(shape)),
                                   ("variables", ",".join(sorted(matrices))), ("scenario", scenario)]:
                    counts[key][value] += 1
                subject_splits[split][subject] += 1
                class_splits[split][label] += 1
                activity_map[label].add(activity)
                readme_mismatches += activity != readme_ids[label]
                numeric_hashes[record["matrix_sha256"]].append(name)
                file_hashes[hashlib.sha256(blob).hexdigest()].append(name)
                ids[(scenario, subject, activity, trial)].append(name)
                number_total += n
                zero_total += zeros
                negative_total += negatives
            except (ValueError, KeyError, UnicodeError, struct.error) as error:
                result["errors"].append({"path": name, "error": str(error)})
        # Keep selected text evidence for line-specific review; never execute it.
        evidence = args.out / "source_evidence"
        evidence.mkdir(exist_ok=True)
        for source, target in [
            ("ESP-Fi-HAR-main/README.md", "README.md"),
            ("ESP-Fi-HAR-main/Model Code/dataset.py", "dataset.py"),
            ("ESP-Fi-HAR-main/Model Code/run.py", "run.py"),
            ("ESP-Fi-HAR-main/Model Code/DATA_LICENSE.txt", "DATA_LICENSE.txt"),
        ]:
            (evidence / target).write_bytes(archive.read(source))
    result["counts"] = {k: dict(v) for k, v in counts.items()}
    result["subjects_per_split"] = {k: dict(v) for k, v in subject_splits.items()}
    result["classes_per_split"] = {k: dict(v) for k, v in class_splits.items()}
    result["folder_to_filename_activity_ids"] = {k: sorted(v) for k, v in activity_map.items()}
    result["filename_readme_label_mismatches"] = readme_mismatches
    result["exact_duplicate_matrices"] = [v for v in numeric_hashes.values() if len(v) > 1]
    result["exact_duplicate_files"] = [v for v in file_hashes.values() if len(v) > 1]
    result["duplicate_trial_ids"] = [v for v in ids.values() if len(v) > 1]
    expected_ids = {(scenario, subject, activity, str(trial))
                    for scenario in counts["scenario"]
                    for subject in set().union(*(set(c) for c in subject_splits.values()))
                    for activity in set().union(*activity_map.values())
                    for trial in range(1, 11)}
    result["missing_trials_within_observed_scenarios"] = [list(k) for k in sorted(expected_ids - set(ids))]
    result["unexpected_trial_ids"] = [list(k) for k in sorted(set(ids) - expected_ids)]
    result["train_test_subject_overlap"] = sorted(set(subject_splits["train_amp"]) & set(subject_splits["test_amp"]))
    result["cross_split_duplicate_matrices"] = [v for v in result["exact_duplicate_matrices"]
        if len({PurePosixPath(p).parts[-3] for p in v}) > 1]
    result["numeric_totals"] = {"values": number_total, "zeros": zero_total,
                                "negatives": negative_total, "nonfinite": nonfinite_total}
    if result["samples"]:
        result["numeric_summary"] = {
            "min": min(s["min"] for s in result["samples"]),
            "max": max(s["max"] for s in result["samples"]),
            "sample_mean_range": [min(s["mean"] for s in result["samples"]), max(s["mean"] for s in result["samples"])],
            "sample_std_range": [min(s["std"] for s in result["samples"]), max(s["std"] for s in result["samples"])],
            "constant_samples": sum(s["std"] == 0 for s in result["samples"]),
            "samples_with_constant_columns": sum(s["constant_columns"] > 0 for s in result["samples"]),
        }
    output = args.out / "audit.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}, ensure_ascii=False, indent=2))
    print(f"Saved full per-sample audit to {output.resolve()}")


if __name__ == "__main__":
    main()
