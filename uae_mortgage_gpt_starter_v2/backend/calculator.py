from __future__ import annotations

from typing import Dict, Any, List


def _get_index_series(payload: Dict[str, Any], name: str) -> List[float]:
    """Fetch an index series by name from rate_scenarios.base, fallback to last value if horizon > series len."""
    base = payload.get("rate_scenarios", {}).get("base", {})
    series = base.get(name, [])
    if not series:
        # If missing, assume flat 0 index rather than blowing up
        return [0.0]
    return series


def _index_for_month(series: List[float], m: int) -> float:
    """Return index value for month m (1-indexed). Extend by repeating last value for longer horizons."""
    if m <= 0:
        m = 1
    return series[m - 1] if m - 1 < len(series) else series[-1]


def _bps_to_decimal(bps: float) -> float:
    return (bps or 0.0) / 10_000.0


def _monthly_payment(principal: float, annual_rate: float, months: int) -> float:
    """Standard fixed-rate monthly payment for a given period.
    If annual_rate is 0, it's straight-line principal / months."""
    if months <= 0:
        return 0.0
    r = annual_rate / 12.0
    if abs(r) < 1e-12:
        return principal / months
    return principal * (r * (1 + r) ** months) / ((1 + r) ** months - 1)


def _amortize_with_resets(
    principal: float,
    horizon_months: int,
    reset_every_months: int,
    annual_rate_for_month_fn,
) -> Dict[str, float]:
    """
    Simulate month-by-month amortization with rate resets.
    annual_rate_for_month_fn(m, outstanding) -> annual rate for month m.
    Returns total_cash_out and outstanding at end of horizon.
    """
    outstanding = float(principal)
    total_cash_out = 0.0
    m = 1
    while m <= horizon_months and outstanding > 0.01:
        # Determine the next reset boundary
        segment_len = min(reset_every_months if reset_every_months > 0 else horizon_months, horizon_months - m + 1)
        # Lock the rate for this segment
        annual_rate = annual_rate_for_month_fn(m, outstanding)
        payment = _monthly_payment(outstanding, annual_rate, segment_len)

        for _ in range(segment_len):
            r = annual_rate / 12.0
            interest = outstanding * r
            principal_pay = payment - interest
            if principal_pay <= 0:
                # Pathological rate vs term: at least pay interest
                principal_pay = 0.0
                payment = interest
            outstanding = max(0.0, outstanding - principal_pay)
            total_cash_out += payment
            m += 1
            if m > horizon_months or outstanding <= 0.01:
                break

    return {"total_cash_out": total_cash_out, "outstanding_end": outstanding}


def _sum_optional_fees(payload: Dict[str, Any]) -> float:
    """
    Optional fee container (if you decide to pass granular fees later):
      "fees": {
        "dld": 0, "processing": 0, "valuation": 0, "registration": 0, "trustee": 0, "other": 0
      }
    """
    fees = payload.get("fees", {})
    keys = ["dld", "processing", "valuation", "registration", "trustee", "other"]
    return sum(float(fees.get(k, 0.0) or 0.0) for k in keys)


def compare(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Core comparison routine.
    Expects the structure you've been using in tests:
      principal_aed, tenure_months, horizon_months,
      current_terms { index_type, margin_bps, reset_freq_months, early_settlement {percent_of_outstanding, cap_aed}, ... },
      new_offer { fixed_rate_annual, fixed_months, reversion_index_type, reversion_margin_bps, reset_freq_months, ... },
      rate_scenarios { base: { EIBOR_1M: [...], EIBOR_3M: [...] } }
    """
    p = input_payload

    # Required
    principal = float(p["principal_aed"])
    tenure_months = int(p["tenure_months"])
    horizon = int(p["horizon_months"])

    # --- Current terms (stay) ---
    cur = p["current_terms"]
    cur_idx_type = cur.get("index_type", "EIBOR_1M")
    cur_margin = _bps_to_decimal(float(cur.get("margin_bps", 0)))
    cur_reset = int(cur.get("reset_freq_months", 1))
    es = cur.get("early_settlement", {})
    es_pct = float(es.get("percent_of_outstanding", 0.01))  # default 1%
    es_cap = float(es.get("cap_aed", 10000))                # cap AED 10k by default

    # --- New offer (switch) ---
    new = p["new_offer"]
    fx_rate = float(new.get("fixed_rate_annual", 0.0))
    fx_months = int(new.get("fixed_months", 0))
    rev_idx_type = new.get("reversion_index_type", "EIBOR_3M")
    rev_margin = _bps_to_decimal(float(new.get("reversion_margin_bps", 0)))
    new_reset = int(new.get("reset_freq_months", 3))

    # Indices
    series_1m = _get_index_series(p, "EIBOR_1M")
    series_3m = _get_index_series(p, "EIBOR_3M")

    def _series_for_name(name: str) -> List[float]:
        return series_1m if name == "EIBOR_1M" else series_3m

    # ---------------------------
    # Scenario A: STAY with current terms
    # ---------------------------
    cur_series = _series_for_name(cur_idx_type)

    def cur_annual_rate_for_month(m: int, outstanding: float) -> float:
        return _index_for_month(cur_series, m) + cur_margin

    stay = _amortize_with_resets(
        principal=principal,
        horizon_months=horizon,
        reset_every_months=cur_reset,
        annual_rate_for_month_fn=cur_annual_rate_for_month,
    )
    stay_total_cash = stay["total_cash_out"]

    # ---------------------------
    # Scenario B: SWITCH to new offer
    # - Includes early settlement penalty on today's outstanding (approx = principal for horizon start),
    #   then applies optional fees if provided.
    # ---------------------------
    # Early settlement on outstanding at t=0 (approx.)
    early_settlement_penalty = min(principal * es_pct, es_cap)

    # User-provided fees (DLD, processing, valuation, registration, trustee, etc.)
    other_fees = _sum_optional_fees(p)
    upfront_fees_switch = early_settlement_penalty + other_fees

    rev_series = _series_for_name(rev_idx_type)

    def switch_annual_rate_for_month(m: int, outstanding: float) -> float:
        # Fixed for the first fx_months, then index + margin
        if m <= max(0, fx_months):
            return fx_rate
        return _index_for_month(rev_series, m) + rev_margin

    switch = _amortize_with_resets(
        principal=principal,
        horizon_months=horizon,
        reset_every_months=new_reset,
        annual_rate_for_month_fn=switch_annual_rate_for_month,
    )
    switch_total_cash = switch["total_cash_out"] + upfront_fees_switch

    # ---------------------------
    # Summary & recommendation
    # ---------------------------
    recommendation = "Switch" if switch_total_cash < stay_total_cash else "Stay"

    # Simple break-even heuristic: first month where cumulative switch < stay
    # (quick & understandable fallback without a second pass)
    break_even_month = None
    cum_stay = 0.0
    cum_switch = upfront_fees_switch
    outstanding_a = float(principal)
    outstanding_b = float(principal)

    # A small per-month replay using same logic to find a crossing point
    ms = 1
    while ms <= horizon and break_even_month is None:
        # stay month
        rate_a = cur_annual_rate_for_month(ms, outstanding_a)
        pay_a = _monthly_payment(outstanding_a, rate_a, max(1, min(cur_reset, horizon - ms + 1)))
        # recompute actual paid for one month
        interest_a = outstanding_a * (rate_a / 12.0)
        principal_a = max(0.0, pay_a - interest_a)
        outstanding_a = max(0.0, outstanding_a - principal_a)
        cum_stay += pay_a

        # switch month
        rate_b = switch_annual_rate_for_month(ms, outstanding_b)
        pay_b = _monthly_payment(outstanding_b, rate_b, max(1, min(new_reset, horizon - ms + 1)))
        interest_b = outstanding_b * (rate_b / 12.0)
        principal_b = max(0.0, pay_b - interest_b)
        outstanding_b = max(0.0, outstanding_b - principal_b)
        cum_switch += pay_b

        if cum_switch <= cum_stay:
            break_even_month = ms
        ms += 1

    return {
        "summary": {
            "stay_total_cash_out_aed": round(stay_total_cash, 2),
            "switch_total_cash_out_aed": round(switch_total_cash, 2),
            "break_even_month": break_even_month,
            "recommendation": recommendation,
            "assumptions_note": (
                "Early settlement penalty applied on current outstanding with cap; "
                "optional fees added if provided; rates follow input indices/margins."
            ),
        },
        "upfront_fees_applied": {
            "stay": 0.0,
            "switch": round(upfront_fees_switch, 2),
        },
    }
