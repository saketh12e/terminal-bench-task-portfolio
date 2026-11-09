"""Verify complete training maps, globally selected models and one-sided sensitivities."""

import json
import os
import stat
import sys
from pathlib import Path
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import build_models
from atlas_check import validate_atlas
from selection_check import validation_value
from feedback_check import (
    reconstruct,
    check_graph,
    matches_selection,
    optimum,
    directional_bundle,
    matches_response,
)

ROOT = Path(os.environ.get("ATLAS_OUTPUT", "/app"))
DATA = json.loads(
    Path(os.environ.get("ATLAS_EVIDENCE", "/tests/evidence.json")).read_text()
)


def load(name):
    path = ROOT / name
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
    assert info.st_size <= 32 * 1024 * 1024

    def pairs(items):
        obj = {}
        for k, v in items:
            if k in obj:
                raise ValueError("duplicate JSON key")
            obj[k] = v
        return obj

    def bad(value):
        raise ValueError("non-finite JSON constant")

    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))) as stream:
        obj = json.load(stream, object_pairs_hook=pairs, parse_constant=bad)
    assert (
        isinstance(obj, dict)
        and type(obj.get("version")) is int
        and obj["version"] == 2
    )
    return obj


def numeric(x, shape):
    def good(v):
        return (
            all(good(y) for y in v)
            if isinstance(v, list)
            else type(v) in (int, float) and np.isfinite(v)
        )

    assert good(x)
    a = np.asarray(x, float)
    assert a.shape == shape and np.isfinite(a).all()
    return a


def close(x, y, tol):
    x = np.asarray(x)
    y = np.asarray(y)
    assert np.max(np.abs(x - y)) <= tol * (
        1 + max(float(np.max(np.abs(x))), float(np.max(np.abs(y))))
    )


@pytest.fixture(scope="session")
def models():
    return build_models(DATA)


@pytest.fixture(scope="session")
def atlas():
    return load("atlas.json")


@pytest.fixture(scope="session")
def certified(atlas):
    return validate_atlas(DATA, atlas).fits


@pytest.fixture(scope="session")
def graph(models, certified):
    return reconstruct(DATA, models, certified)


@pytest.fixture(scope="session")
def selected(models):
    obj = load("selection.json")
    assert set(obj) == {"version", "theta", "blends", "value", "models"}
    theta = numeric(obj["theta"], (2,))
    assert np.min(theta) >= -1e-9 and np.max(theta) <= 1 + 1e-9
    obj["theta"] = np.clip(theta, 0, 1)
    numeric(obj["blends"], (4,))
    numeric(obj["value"], ())
    assert set(obj["models"]) == set(models)
    for name in models:
        numeric(obj["models"][name], (6,))
    return obj


@pytest.fixture(scope="session")
def responses(models):
    obj = load("sensitivities.json")
    assert set(obj) == {"version", "queries"}
    assert set(obj["queries"]) == {q["id"] for q in DATA["queries"]}
    for group in obj["queries"].values():
        assert isinstance(group, list) and group
        for ans in group:
            assert set(ans) == {
                "blends",
                "blend_directions",
                "weights",
                "directions",
                "validation_direction",
            }
            assert set(ans["weights"]) == set(ans["directions"]) == set(models)
            numeric(ans["blends"], (4,))
            numeric(ans["blend_directions"], (4,))
            numeric(ans["validation_direction"], ())
            for name in models:
                numeric(ans["weights"][name], (6,))
                numeric(ans["directions"][name], (6,))
    return obj["queries"]


@pytest.mark.parametrize("name", list(DATA["fits"]))
def test_complete_local_training_map(certified, name):
    """Every local model satisfies all three priorities over the internal square."""
    assert certified[name]


def test_complete_equilibrium_graph(graph, models):
    """Two-way graph inclusion checks every branch, not just external-domain coverage."""
    check_graph(load("equilibria.json"), graph, list(models))


def test_selected_model_branch(graph, selected):
    """All selected model values and blends belong to one simultaneous equilibrium."""
    assert matches_selection(
        graph, selected["theta"], selected["blends"], selected["models"]
    )


@pytest.mark.parametrize("name", list(DATA["fits"]))
def test_selected_feedback_equation(models, selected, name):
    """Each physical source readout closes the corresponding target blend equation."""
    record = DATA["feedback"][name]
    source = record["source"]
    physical = models[source].T @ np.asarray(selected["models"][source])
    actual = np.clip(
        selected["theta"][0]
        + record["offset"]
        + np.asarray(record["normal"]) @ physical,
        0,
        1,
    )
    close(selected["blends"][list(models).index(name)], actual, 1e-7)


def test_selection_value(models, selected):
    """Audit loss uses the declared separately normalized validation observations."""
    assert abs(validation_value(models, selected["models"]) - selected["value"]) <= 1e-6


def test_global_equilibrium_selection(models, graph, selected):
    """No other parameter and equilibrium branch improves loss beyond tolerance."""
    assert validation_value(models, selected["models"]) <= optimum(models, graph) + 1e-6


@pytest.mark.parametrize(
    "query", DATA["queries"], ids=[q["id"] for q in DATA["queries"]]
)
def test_complete_directional_branch_bundle(graph, models, responses, query):
    """Every valid one-sided continuation is present; spurious branches are rejected."""
    expected = directional_bundle(models, graph, query)
    actual = responses[query["id"]]
    assert all(any(matches_response(a, b) for b in expected) for a in actual), (
        "spurious directional branch"
    )
    assert all(any(matches_response(a, b) for a in actual) for b in expected), (
        "missing directional branch"
    )


def test_globally_budgeted_continuous_curriculum(models, graph):
    """Continuity, physical-time integrals and joint global budget allocation."""
    from curriculum_check import check_curriculum

    check_curriculum(load("curriculum.json"), DATA, models, graph)
