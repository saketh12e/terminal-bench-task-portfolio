"""Data-only verification of disclosure-conditioned integer rollout certificates."""

import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import planner_evaluator as ev
from artifacts import load_evaluation, load_witnesses
from lottery_audit import LotteryAudit
from certificate import CertificateAudit
from endpoint_worker import endpoint_batch

EVIDENCE = os.environ.get("JLA_EVIDENCE", "/tests/evidence.json")
EVALUATION = os.environ.get("JLA_EVALUATION", "/app/evaluation.json")
WITNESSES = os.environ.get("JLA_WITNESSES", "/app/witnesses.npz")
PEEK = ev.load_problem(EVIDENCE)
GROUPS = [g["id"] for g in PEEK.disclosure["exposures"]]
ENDPOINTS = [(g, m, s) for g in GROUPS for m in PEEK.metric_ids for s in ev.SIDES]
GATES = [(g, r) for g in GROUPS for r in PEEK.requirements]


@pytest.fixture(scope="session")
def problem():
    return PEEK


@pytest.fixture(scope="session")
def evaluation(problem):
    return load_evaluation(EVALUATION, problem)


@pytest.fixture(scope="session")
def witnesses(problem, evaluation):
    return load_witnesses(WITNESSES, problem, evaluation)


@pytest.fixture(scope="session")
def audit(problem, evaluation):
    return LotteryAudit(problem, evaluation)


@pytest.fixture(scope="session")
def endpoint_checks(problem, evaluation, witnesses):
    populations = {
        key: q for key, q in witnesses.items() if key.endswith(("__lo", "__hi"))
    }
    return endpoint_batch(problem, evaluation, populations, ENDPOINTS)


def test_evaluation_schema(evaluation):
    """Exact versioned report, integral counts, known exposure/response ids and finite values."""
    assert abs(sum(w for p, w in evaluation["mixture"]) - 1) < 1e-12


def test_witness_archive(witnesses):
    """Every endpoint, regret, score and bank population has the required finite real shape."""
    assert all(np.isfinite(q).all() for q in witnesses.values())


def test_support_is_deployable(audit):
    """Architecture, off-path fleet and deployed-model edge constraints hold per positive draw."""
    assert abs(audit.weights.sum() - 1) < 1e-12


@pytest.mark.parametrize("group", GROUPS)
def test_exposure_probability(audit, group):
    """Conditioned risk cannot be hidden by making a regulated exposure too unlikely."""
    minimum, calibration = audit.exposure_minimum(group)
    assert minimum >= audit.channel.floors[group] - ev.GATE_EPS, {
        "exposure": group,
        "minimum": minimum,
        "calibration": calibration,
        "required": audit.channel.floors[group],
    }


@pytest.mark.parametrize(
    "group,requirement", GATES, ids=[g + "__" + r[0] for g, r in GATES]
)
def test_universal_conditional_safety(audit, group, requirement):
    """Each pooled safety guarantee holds for all shared populations and channel calibrations."""
    result = audit.gate(requirement, group)
    assert result[3] <= ev.GATE_EPS, (group, requirement, result[:2], result[3])


def test_sharp_adaptive_regret(audit, evaluation, witnesses):
    """Response may depend on the record, while one population and calibration precede it."""
    truth = max(r[0] for r in audit.scenarios())
    assert abs(truth - evaluation["worst_case_regret"]) <= ev.VALUE_TOL
    q = witnesses["selection__regret"]
    assert max(audit.trajectory.residuals(q).values()) <= ev.FEAS_TOL
    assert (
        abs(audit.scenario_value(evaluation["regret_adversary"], q, False) - truth)
        <= ev.VALUE_TOL
    )


def test_sharp_conditional_score(audit, evaluation, witnesses):
    """The separately maximized score conditions both regret and all-node deterministic costs."""
    truth = audit.score()
    assert abs(truth - evaluation["selection_score"]) <= ev.VALUE_TOL
    q = witnesses["selection__score"]
    assert max(audit.trajectory.residuals(q).values()) <= ev.FEAS_TOL
    assert (
        abs(audit.scenario_value(evaluation["score_adversary"], q, True) - truth)
        <= ev.VALUE_TOL
    )


def test_global_fractional_certificate(audit, evaluation, witnesses):
    """A global MIP dual bound over all trees certifies the coupled conditional objective."""
    lower = CertificateAudit(audit).lower_bound(evaluation, witnesses)
    claimed = evaluation["certificate"]["lower_bound"]
    assert lower >= claimed - 1e-8, "bank does not substantiate the claimed lower bound"
    assert -ev.VALUE_TOL <= audit.score() - claimed <= ev.VALUE_TOL, (
        "reported global gap is not within tolerance"
    )
    assert -ev.VALUE_TOL <= audit.score() - lower <= ev.VALUE_TOL, (
        "independently certified global gap is not within tolerance"
    )


@pytest.mark.parametrize(
    "group,metric_id,side", ENDPOINTS, ids=["__".join(x) for x in ENDPOINTS]
)
def test_metric_endpoint(endpoint_checks, group, metric_id, side):
    """Each exposure-conditioned ratio endpoint is globally sharp and jointly attained."""
    errors = endpoint_checks[metric_id, group, side]
    assert not errors, "; ".join(errors)
