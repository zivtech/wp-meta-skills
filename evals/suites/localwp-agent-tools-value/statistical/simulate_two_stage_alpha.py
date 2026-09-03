#!/usr/bin/env python3
"""Realized type-I error of the pre-registered two-stage rule, under H0.

Rule (verbatim from the design, §4.4/§7 v2):
  Stage 1: F fixtures x R1 reps per arm. Delta1 = mean_f (pT_f - pC_f).
           p1 = two-sided within-fixture label-permutation p.
           reject if p1 < alpha.
  Continue to Stage 2 iff p1 >= alpha AND Delta1 > 0.15.
  Stage 2: add (R2 - R1) reps per arm per fixture; recompute Delta2, p2 on the
           pooled data; reject if p2 < alpha.
  "Success" additionally requires Delta >= 0.20 at the stage that rejected.

Under H0 both arms share each fixture's pass probability p_f (heterogeneous,
p_f ~ U(0.20, 0.80)). The permutation distribution of the per-fixture
difference under label exchange is exactly hypergeometric in the number of
passes assigned to arm T, so the permutation test is computed exactly rather
than by resampling labels.
"""
import argparse, sys
import numpy as np

def perm_p(passes_T, passes_C, R, rng, B):
    F = passes_T.shape[0]
    tot = passes_T + passes_C
    obs = np.mean((passes_T - passes_C) / R)
    # S_chosen ~ Hypergeometric(ngood=tot, nbad=2R-tot, nsample=R) per fixture
    S = rng.hypergeometric(np.broadcast_to(tot, (B, F)), np.broadcast_to(2 * R - tot, (B, F)), R)
    stat = np.mean((2 * S - tot) / R, axis=1)
    p = (np.sum(np.abs(stat) >= abs(obs) - 1e-12) + 1) / (B + 1)
    return obs, p

def simulate(F, R1, R2, alpha, cont_delta, succ_delta, sims, B, seed, p_low=0.20, p_high=0.80):
    rng = np.random.default_rng(seed)
    rej1 = rej2 = succ1 = succ2 = cont = 0
    rej1_only_rule = 0
    for _ in range(sims):
        pf = rng.uniform(p_low, p_high, size=F)
        T1 = rng.binomial(R1, pf); C1 = rng.binomial(R1, pf)
        d1, p1 = perm_p(T1, C1, R1, rng, B)
        if p1 < alpha:
            rej1 += 1; rej1_only_rule += 1
            if d1 >= succ_delta: succ1 += 1
            continue
        if d1 > cont_delta:
            cont += 1
            T2 = T1 + rng.binomial(R2 - R1, pf); C2 = C1 + rng.binomial(R2 - R1, pf)
            d2, p2 = perm_p(T2, C2, R2, rng, B)
            if p2 < alpha:
                rej2 += 1
                if d2 >= succ_delta: succ2 += 1
    n = sims
    return dict(
        stage1_only_alpha=rej1_only_rule / n,
        continue_rate=cont / n,
        realized_alpha_p=(rej1 + rej2) / n,
        realized_alpha_success=(succ1 + succ2) / n,
        stage2_share_of_rejections=(rej2 / (rej1 + rej2)) if (rej1 + rej2) else 0.0,
    )

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", type=int, default=13)
    ap.add_argument("--r1", type=int, default=6)
    ap.add_argument("--r2", type=int, default=10)
    ap.add_argument("--alpha", type=float, default=0.025)
    ap.add_argument("--continue-delta", type=float, default=0.15)
    ap.add_argument("--success-delta", type=float, default=0.20)
    ap.add_argument("--sims", type=int, default=10000)
    ap.add_argument("--perms", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=20260902)
    ap.add_argument("--p-low", type=float, default=0.20, help="H0 per-fixture pass rate, lower bound of U(low, high)")
    ap.add_argument("--p-high", type=float, default=0.80)
    a = ap.parse_args()
    r = simulate(a.fixtures, a.r1, a.r2, a.alpha, a.continue_delta, a.success_delta, a.sims, a.perms, a.seed, a.p_low, a.p_high)
    print(f"F={a.fixtures} R1={a.r1} R2={a.r2} alpha={a.alpha} continue_if_delta>{a.continue_delta} success_delta>={a.success_delta} sims={a.sims} perms={a.perms} seed={a.seed} p_f~U({a.p_low},{a.p_high})")
    for k, v in r.items():
        print(f"  {k}: {v:.4f}")
