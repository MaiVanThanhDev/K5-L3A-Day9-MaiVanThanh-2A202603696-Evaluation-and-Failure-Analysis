"""Regression tests from docs/trace_case.md and for the team's own graders (M3).

Trace case: seeded_regression C-014@11. First wrong step = event 5 `proposal` 120000: the agent
subtracted the prior 30k refund itself (FM-05), the host subtracted it again -> ledger 90k, while the
reply still says 120.000đ (FM-08). The same claim@seed on `fixed` must pass every grader.
"""
import pytest

pytestmark = pytest.mark.student
LABEL = {"refund_vnd": 35000, "approval_ok": True, "policy_denied": False, "forbid_substrings": []}


def ctx(trial, label=LABEL):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def trial(refund_vnd=35000, reply=None, policy_denied=False):
    events = [] if reply is None else [{"kind": "reply", "payload": {"text": reply}}]
    return {"snapshot": {"refund_vnd": refund_vnd, "refund_count": int(refund_vnd > 0),
                         "policy_denied": policy_denied},
            "unexpected_rows": 0, "blob": "", "events": events, "result": {},
            "lab8_pass": True, "lab8_reason": None}


def test_reply_amount_must_match_ledger():
    from lab9.graders import ReplyMatchesLedger

    assert ReplyMatchesLedger().evaluate(ctx(trial(reply="Dạ, LogiX đã hoàn 35.000đ cho đơn O-107."))).value is True
    assert ReplyMatchesLedger().evaluate(ctx(trial(reply="Dạ, LogiX đã hoàn 55.000đ cho đơn O-107."))).value is False
    # announcing money when the ledger holds nothing is FM-08 too (ignore_denied)
    assert ReplyMatchesLedger().evaluate(ctx(trial(0, reply="Dạ, LogiX đã hoàn 35.000đ cho đơn O-505."))).value is False
    # no amount in the reply (denial / needs_info) is fine
    assert ReplyMatchesLedger().evaluate(ctx(trial(0, reply="Dạ, đơn O-505 chưa đủ điều kiện hoàn."))).value is True


def test_host_decision_kept():
    from lab9.graders import HostDecisionKept

    want_denied = {**LABEL, "policy_denied": True}
    assert HostDecisionKept().evaluate(ctx(trial(0, policy_denied=True), want_denied)).value is True
    assert HostDecisionKept().evaluate(ctx(trial(0, policy_denied=False), want_denied)).value is False


def _grade(shape):
    from lab9.graders import RefundAmountCorrect, ReplyMatchesLedger
    from lab9.trace_case import investigate

    case = investigate(shape, "C-014", 11)
    c = ctx(case["trial"], case["label"])
    return case["trial"], RefundAmountCorrect().evaluate(c).value, ReplyMatchesLedger().evaluate(c).value


def test_trace_case_c014_seed11_regression():
    t, amount_ok, reply_ok = _grade("seeded_regression")
    kinds = [e["kind"] for e in t["events"]]
    assert "proposal" in kinds                      # the first wrong step is still visible in the trace
    assert t["snapshot"]["refund_vnd"] == 90000
    assert (amount_ok, reply_ok) == (False, False)
    t, amount_ok, reply_ok = _grade("fixed")
    assert t["snapshot"]["refund_vnd"] == 120000
    assert (amount_ok, reply_ok) == (True, True)
