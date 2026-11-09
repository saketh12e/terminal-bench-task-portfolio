"""Strict bounded parsing of untrusted data-only rollout evidence."""

import io
import math
import zipfile
import numpy as np
from planner_evaluator import (
    ArtifactError,
    parse_json,
    read_regular,
    is_num,
    MAX_JSON,
    MAX_NPZ,
    MAX_NPZ_RAW,
)


def _keys(got, expected, where):
    missing = [key for key in expected if key not in got]
    extra = [key for key in got if key not in set(expected)]
    if missing or extra:
        raise ArtifactError(f"{where}: missing {missing[:8]} unexpected {extra[:8]}")


def _read_npy(stream, expected_shape, where):
    fmt = np.lib.format
    try:
        version = fmt.read_magic(stream)
        if version == (1, 0):
            shape, fortran, dtype = fmt.read_array_header_1_0(stream)
        elif version in ((2, 0), (3, 0)):
            shape, fortran, dtype = fmt.read_array_header_2_0(stream)
        else:
            raise ValueError(f"unsupported NPY version {version}")
    except (ValueError, TypeError, SyntaxError, EOFError) as exc:
        raise ArtifactError(f"{where}: bad NPY header ({exc})") from None
    if (
        dtype.hasobject
        or dtype.fields is not None
        or dtype.subdtype is not None
        or dtype.kind not in "iuf"
    ):
        raise ArtifactError(f"{where}: plain real numeric dtype required")
    if tuple(shape) != tuple(expected_shape):
        raise ArtifactError(f"{where}: shape must be {tuple(expected_shape)}")
    count = math.prod(expected_shape)
    size = count * dtype.itemsize
    raw = stream.read(size)
    if len(raw) != size:
        raise ArtifactError(f"{where}: truncated NPY payload")
    flat = np.frombuffer(raw, dtype=dtype, count=count)
    value = flat.reshape(expected_shape, order="F" if fortran else "C").astype(
        np.float64
    )
    if not np.isfinite(value).all():
        raise ArtifactError(f"{where}: non-finite values")
    return value


def load_evaluation(path, problem):
    data = parse_json(read_regular(path, MAX_JSON), path, ArtifactError)
    if not isinstance(data, dict):
        raise ArtifactError("top level must be an object")
    _keys(
        data,
        [
            "version",
            "mixture",
            "bounds",
            "metric_calibrations",
            "worst_case_regret",
            "selection_score",
            "regret_adversary",
            "score_adversary",
            "certificate",
        ],
        "evaluation",
    )
    if data["version"] != 9 or isinstance(data["version"], bool):
        raise ArtifactError("version must be 9")
    terms = data["mixture"]
    if not isinstance(terms, list) or not 1 <= len(terms) <= 1024:
        raise ArtifactError("mixture requires 1..1024 terms")
    merged = {}
    for term in terms:
        if not isinstance(term, dict):
            raise ArtifactError("mixture term must be an object")
        _keys(term, ["count", "policy_tree"], "mixture term")
        w = term["count"]
        tree = term["policy_tree"]
        if type(w) is not int or not 0 <= w <= problem.rollout_buckets:
            raise ArtifactError("invalid bucket count")
        if not isinstance(tree, dict):
            raise ArtifactError("policy_tree must be an object")
        _keys(tree, problem.node_ids, "policy_tree")
        for node, row in tree.items():
            if (
                not isinstance(row, list)
                or len(row) != problem.S
                or any(
                    not isinstance(t, str) or t not in problem.templates for t in row
                )
            ):
                raise ArtifactError("one known template per stratum required")
        policy = tuple(tuple(tree[node]) for node in problem.node_ids)
        merged[policy] = merged.get(policy, 0) + w
    total = sum(merged.values())
    if total != problem.rollout_buckets:
        raise ArtifactError("bucket counts must sum to rollout_buckets")
    mixture = tuple((p, w / total) for p, w in merged.items() if w > 0)
    groups = {g["id"]: g["records"] for g in problem.disclosure["exposures"]}

    def calibration(x):
        if not (
            isinstance(x, list)
            and len(x) == 2
            and all(is_num(y) for y in x)
            and min(x) >= 0
            and sum(x) <= 1
        ):
            raise ArtifactError("calibration outside joint simplex")

    for field in ["bounds", "metric_calibrations"]:
        if not isinstance(data[field], dict):
            raise ArtifactError(field + " must be an object")
        _keys(data[field], groups, field)
        for group, metrics in data[field].items():
            if not isinstance(metrics, dict):
                raise ArtifactError("metric entries must be an object")
            _keys(metrics, problem.metric_ids, field + " metrics")
            for pair in metrics.values():
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or (field == "bounds" and not all(is_num(x) for x in pair))
                ):
                    raise ArtifactError("endpoint pair requires finite numbers")
                if field == "metric_calibrations":
                    for x in pair:
                        calibration(x)
    for field in ["worst_case_regret", "selection_score"]:
        if not is_num(data[field]):
            raise ArtifactError(field + " must be finite numeric")

    def common(row):
        if not isinstance(row["exposure"], str) or row["exposure"] not in groups:
            raise ArtifactError("unknown exposure")
        calibration(row["calibration"])

    def adversary(row):
        if not isinstance(row, dict):
            raise ArtifactError("adversary must be an object")
        _keys(row, ["exposure", "calibration", "responses"], "adversary")
        common(row)
        if not isinstance(row["responses"], dict):
            raise ArtifactError("responses must be an object")
        _keys(row["responses"], groups[row["exposure"]], "record response map")
        for record, response in row["responses"].items():
            if not isinstance(response, dict):
                raise ArtifactError("response must be an object")
            _keys(response, ["path", "comparator"], "response")
            if (
                not isinstance(response["path"], str)
                or response["path"] not in problem.regret_paths
                or not isinstance(response["comparator"], str)
                or response["comparator"] not in problem.comparators
            ):
                raise ArtifactError("unknown path or comparator")
            if response["path"] not in problem.disclosure["record_paths"][record]:
                raise ArtifactError("path is not eligible for this public record")

    adversary(data["regret_adversary"])
    adversary(data["score_adversary"])
    bank = data["certificate"]
    if not isinstance(bank, dict):
        raise ArtifactError("certificate must be an object")
    _keys(bank, ["lower_bound", "regret", "safety"], "certificate")
    if not is_num(bank["lower_bound"]):
        raise ArtifactError("finite lower_bound required")
    if not isinstance(bank["regret"], list) or not 1 <= len(bank["regret"]) <= 128:
        raise ArtifactError("regret bank requires 1..128 entries")
    if not isinstance(bank["safety"], list) or len(bank["safety"]) > 128:
        raise ArtifactError("safety bank permits at most 128 entries")
    for row in bank["regret"]:
        adversary(row)
    required = {r[0] for r in problem.requirements}
    for row in bank["safety"]:
        if not isinstance(row, dict):
            raise ArtifactError("safety entry must be an object")
        _keys(row, ["exposure", "calibration", "metric"], "safety entry")
        common(row)
        if not isinstance(row["metric"], str) or row["metric"] not in required:
            raise ArtifactError("unknown safety requirement")
    return dict(data, mixture=mixture)


def load_witnesses(path, problem, evaluation):
    expected = {
        f"{g['id']}__{mid}__{side}": (problem.N, 2)
        for g in problem.disclosure["exposures"]
        for mid in problem.metric_ids
        for side in ("lo", "hi")
    }
    for name in ["selection__regret", "selection__score"]:
        expected[name] = (len(problem.forecast_order), problem.N, 2)
    expected["certificate__regret"] = (
        len(evaluation["certificate"]["regret"]),
        len(problem.forecast_order),
        problem.N,
        2,
    )
    expected["certificate__safety"] = (
        len(evaluation["certificate"]["safety"]),
        problem.N,
        2,
    )
    raw = read_regular(path, MAX_NPZ)
    out = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if sum(i.file_size for i in infos) > MAX_NPZ_RAW:
                raise ArtifactError("uncompressed archive exceeds 64 MiB")
            for info in infos:
                name = (
                    info.filename[:-4]
                    if info.filename.endswith(".npy")
                    else info.filename
                )
                if name in out or name not in expected:
                    raise ArtifactError("duplicate or unexpected NPZ member")
                with archive.open(info) as stream:
                    out[name] = _read_npy(stream, expected[name], info.filename)
    except ArtifactError:
        raise
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        OSError,
        EOFError,
        RuntimeError,
        NotImplementedError,
        ValueError,
    ) as e:
        raise ArtifactError("unreadable NPZ: " + str(e)) from None
    _keys(out, expected, "witnesses")
    return out
