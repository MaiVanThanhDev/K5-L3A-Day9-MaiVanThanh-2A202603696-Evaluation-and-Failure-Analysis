"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)
    Also catches: duplicated (item, seed) rows, a seed list / item count that differs from the
    baseline's, a graded cell that is NaN or not a bool, and headline metrics that do not match
    the rows they claim to summarise (a hand-edited report)."""
    problems: list[str] = []
    graded = _graded(spec)
    pm, bm = pr.get("manifest") or {}, base.get("manifest") or {}
    rows, brows = pr.get("rows") or [], base.get("rows") or []
    metrics = pr.get("metrics") or {}

    for k, v in metrics.items():
        if _num_bad(v):
            problems.append(f"metric {k} is {v} (NaN/inf: a crashed grader, not a score)")
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), "
                        f"first: {pr['evaluator_failures'][0]}")

    seeds = list(pm.get("seeds") or [])
    expected_rows = (pm.get("items") or 0) * len(seeds)
    if len(rows) != expected_rows:
        problems.append(f"{len(rows)} rows, manifest says {pm.get('items')} items x {len(seeds)} seeds"
                        f" = {expected_rows} (dropped or duplicated rows)")
    if pm.get("items") != bm.get("items") or list(bm.get("seeds") or []) != seeds:
        problems.append(f"manifest items/seeds {pm.get('items')}/{seeds} differ from baseline "
                        f"{bm.get('items')}/{bm.get('seeds')} (cherry-picked seeds or items)")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    counts: dict[tuple, int] = {}
    for k in keys:
        counts[k] = counts.get(k, 0) + 1
    dups = sorted((k for k, c in counts.items() if c > 1), key=str)
    if dups:
        problems.append(f"{len(dups)} duplicated (item, seed) row(s), first {dups[0]}")
    bkeys = {(r.get("item_id"), r.get("seed")) for r in brows}
    if set(keys) != bkeys:
        problems.append(f"(item, seed) set differs from baseline: {len(bkeys - set(keys))} missing, "
                        f"{len(set(keys) - bkeys)} extra")

    bad_cells = 0
    for r in rows:
        for m in graded:
            v = r.get(m)
            if not isinstance(v, bool):
                bad_cells += 1
                if bad_cells == 1:
                    problems.append(f"row {r.get('item_id')}@{r.get('seed')}: {m} = {v!r} "
                                    "(missing or crashed grader drops out of the mean)")
    if bad_cells > 1:
        problems.append(f"{bad_cells} graded cell(s) missing or non-boolean in total")

    if rows and not bad_cells:
        for k, v in _recompute(rows, graded, spec.get("pass_k")).items():
            if k == "cost_per_success" or k not in metrics:
                if k in graded and k not in metrics:
                    problems.append(f"metric {k} missing from the report")
                continue
            claimed = metrics[k]
            if (claimed is None) != (v is None) or (
                    v is not None and isinstance(claimed, (int, float)) and not _num_bad(claimed)
                    and abs(float(claimed) - float(v)) > 1e-3):
                problems.append(f"metric {k} = {claimed} but the rows give {v} (report edited?)")

    base_tags = {r.get("item_id"): sorted(r.get("slices") or []) for r in brows}
    relabelled = sorted({r.get("item_id") for r in rows if r.get("item_id") in base_tags
                         and sorted(r.get("slices") or []) != base_tags[r.get("item_id")]}, key=str)
    if relabelled:
        problems.append(f"slice tags differ from baseline on {len(relabelled)} item(s), first {relabelled[0]}")

    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems



def _num_bad(v) -> bool:
    return isinstance(v, float) and (math.isnan(v) or math.isinf(v))


def _graded(spec: dict) -> list[str]:
    from lab9.graders import GRADERS
    return [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS]


def _recompute(rows: list[dict], metric_ids: list[str], k_values) -> dict:
    """Metrics recomputed from the rows exactly as lab9.eval.aggregate does."""
    from lab9.eval import aggregate
    try:
        return aggregate([{**r, "cost": r.get("cost") or 0.0} for r in rows], metric_ids,
                         k_values=k_values or [])
    except (TypeError, ValueError, KeyError, ZeroDivisionError):
        return {}


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => thresholds may only get stricter."""
    out: list[str] = []
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return out      # a new eval-set version starts a new ratchet (and needs a new baseline)

    def compare(where: str, old: dict, new: dict | None) -> None:
        if new is None:
            out.append(f"ratchet: {where} removed from the spec")
            return
        if old.get("blocking") and not new.get("blocking"):
            out.append(f"ratchet: {where} was blocking, now non-blocking")
        o_th = old.get("threshold") if "threshold" in old else old
        n_th = (new.get("threshold") if "threshold" in new else new) or {}
        o_th = o_th or {}
        for key in ("max", "max_increase"):
            if key in o_th and (n_th.get(key) is None or float(n_th[key]) > float(o_th[key])):
                out.append(f"ratchet: {where} {key} loosened {o_th[key]} -> {n_th.get(key)}")
        if "min" in o_th and (n_th.get("min") is None or float(n_th["min"]) < float(o_th["min"])):
            out.append(f"ratchet: {where} min loosened {o_th['min']} -> {n_th.get('min')}")
        if o_th.get("no_significant_drop") and not n_th.get("no_significant_drop"):
            out.append(f"ratchet: {where} dropped no_significant_drop")

    new_metrics = {m["id"]: m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        compare(f"metric {m['id']}", m, new_metrics.get(m["id"]))
    new_slices = {(s.get("name"), s.get("metric")): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        compare(f"slice {s.get('name')}/{s.get('metric')}", s, new_slices.get((s.get("name"), s.get("metric"))))
    for key in ("seeds", "eval_set", "labels", "adversarial_pack"):
        if base_spec.get(key) != spec.get(key):
            out.append(f"ratchet: spec {key} changed on the same eval-set version")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines).
    A slice with no items in the PR is MISSING (it cannot vouch for anything) and blocks if blocking."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if ("min" in sl and val < sl["min"]) or ("max" in sl and val > sl["max"]):
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if sl.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000),
                                                   rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
