
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

def emi(principal: float, monthly_rate: float, months: int) -> float:
    if monthly_rate == 0:
        return principal / months
    factor = (1 + monthly_rate) ** months
    return principal * monthly_rate * factor / (factor - 1)

def clamp(x: float, floor: float) -> float:
    return max(x, floor)

@dataclass
class Terms:
    bank: str
    index_type: str
    margin_bps: float
    floor_rate_annual: float
    reset_freq_months: int
    life_insurance_method: str = "none"
    life_insurance_value: float = 0.0
    fees: List[Dict[str, Any]] = None
    # Optional early settlement policy
    es_percent: float = 0.0
    es_cap_aed: float = 0.0
    # For new offer specifics
    fixed_rate_annual: Optional[float] = None
    fixed_months: Optional[int] = None
    reversion_index_type: Optional[str] = None
    reversion_margin_bps: Optional[float] = None

def insurance_cost(method: str, value: float, outstanding: float) -> float:
    if method == "percent_of_outstanding":
        return outstanding * (value / 12.0)
    if method == "fixed_monthly":
        return value
    return 0.0

def monthly_index(rate_curve: List[float], m: int) -> float:
    if m - 1 < len(rate_curve):
        return rate_curve[m - 1]
    return rate_curve[-1]

def estimate_buyout_fees_if_missing(principal: float, provided_fees: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    provided_types = {f.get("type") for f in (provided_fees or [])}
    est = []
    if "processing_fee" not in provided_types:
        est.append({"type": "processing_fee", "amount_aed": min(0.01 * principal, 10000.0), "timing": "upfront"})
    if "valuation_fee" not in provided_types:
        est.append({"type": "valuation_fee", "amount_aed": 2500.0, "timing": "upfront"})
    if "dld_fee" not in provided_types:
        est.append({"type": "dld_fee", "amount_aed": 0.0025 * principal + 290.0, "timing": "upfront"})
    if "trustee_fee" not in provided_types:
        est.append({"type": "trustee_fee", "amount_aed": 4200.0, "timing": "upfront"})
    if "mortgage_registration_fee" not in provided_types:
        est.append({"type": "mortgage_registration_fee", "amount_aed": 2000.0, "timing": "upfront"})
    return est

def estimate_release_and_liability_if_missing(provided_fees: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    provided_types = {f.get("type") for f in (provided_fees or [])}
    est = []
    if "release_letter_fee" not in provided_types:
        est.append({"type": "release_letter_fee", "amount_aed": 1000.0, "timing": "upfront"})
    if "liability_letter_fee" not in provided_types:
        est.append({"type": "liability_letter_fee", "amount_aed": 100.0, "timing": "upfront"})
    return est

def run_option(principal: float, tenure_months: int, horizon_months: int, prepayments: List[Dict[str, Any]],
               option: str, current: Terms, new: Terms, curves: Dict[str, List[float]],
               recompute_policy: str = "on_reset_only", auto_estimate_buyout_fees: bool = True) -> Dict[str, Any]:
    out = []
    p = principal
    fees_upfront = 0.0
    monthly_fee_sum = 0.0
    annual_fee_sum = 0.0

    terms = current if option == "stay" else new
    fees_list = []
    if terms.fees:
        fees_list.extend(terms.fees)

    if option == "switch" and auto_estimate_buyout_fees:
        fees_list.extend(estimate_buyout_fees_if_missing(principal, fees_list))
        fees_list.extend(estimate_release_and_liability_if_missing(current.fees or []))

    if option == "switch" and current.es_percent and current.es_percent > 0:
        es_fee = principal * current.es_percent
        if current.es_cap_aed and current.es_cap_aed > 0:
            es_fee = min(es_fee, current.es_cap_aed)
        fees_list.append({"type": "early_settlement_penalty_old_bank", "amount_aed": es_fee, "timing": "upfront"})

    for fee in fees_list:
        if fee.get("timing") == "upfront":
            fees_upfront += fee.get("amount_aed", 0.0)
        elif fee.get("timing") == "monthly":
            monthly_fee_sum += fee.get("amount_aed", 0.0)
        elif fee.get("timing") == "annual":
            annual_fee_sum += fee.get("amount_aed", 0.0)

    def rate_for_month(m: int) -> float:
        if option == "stay":
            idx_type = current.index_type
            idx_curve = curves[idx_type]
            annual = clamp(monthly_index(idx_curve, m), current.floor_rate_annual) + current.margin_bps / 10000.0
            return annual / 12.0
        else:
            if m <= (new.fixed_months or 0):
                return (new.fixed_rate_annual or 0.0) / 12.0
            else:
                idx_type = new.reversion_index_type or "EIBOR_3M"
                idx_curve = curves[idx_type]
                annual = clamp(monthly_index(idx_curve, m - (new.fixed_months or 0)), new.floor_rate_annual) + (new.reversion_margin_bps or 0.0) / 10000.0
                return annual / 12.0

    mrate = rate_for_month(1)
    emi_val = emi(p, mrate, tenure_months)

    total_cash = fees_upfront
    months_elapsed = 0
    prepay_map = {pp["month"]: pp for pp in prepayments} if prepayments else {}

    while months_elapsed < horizon_months and p > 0 and months_elapsed < tenure_months:
        m = months_elapsed + 1
        if recompute_policy == "on_reset_only":
            reset_freq = current.reset_freq_months if option == "stay" else (new.reset_freq_months or 3)
            if m == 1 or (m - 1) % reset_freq == 0:
                mrate = rate_for_month(m)
                emi_val = emi(p, mrate, tenure_months - months_elapsed)
        else:
            mrate = rate_for_month(m)
            emi_val = emi(p, mrate, tenure_months - months_elapsed)

        interest = p * mrate
        principal_paid = max(0.0, emi_val - interest)
        p = max(0.0, p - principal_paid)

        ins_cost = insurance_cost(terms.life_insurance_method or "none", terms.life_insurance_value or 0.0, p)
        fees_monthly = monthly_fee_sum + (annual_fee_sum if m % 12 == 1 else 0.0)

        if m in prepay_map:
            pp = prepay_map[m]
            amount = min(pp.get("amount", 0.0), p)
            p -= amount
            if pp.get("method") == "reduce_emi":
                emi_val = emi(p, mrate, tenure_months - months_elapsed)

        out.append({
            "month": m,
            "option": option,
            "emi": round(emi_val, 2),
            "interest": round(interest, 2),
            "principal_paid": round(principal_paid, 2),
            "fees": round(fees_monthly, 2),
            "insurance": round(ins_cost, 2),
            "principal_remaining": round(p, 2)
        })

        total_cash += emi_val + fees_monthly + ins_cost
        months_elapsed += 1

    return {"cashflows": out, "total_cash": round(total_cash, 2), "applied_upfront_fees": round(fees_upfront, 2), "fees_list": fees_list}

def compare(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    principal = input_payload["principal_aed"]
    tenure = input_payload["tenure_months"]
    horizon = input_payload["horizon_months"]
    prepayments = input_payload.get("prepayment_plan", [])
    scenarios = input_payload["rate_scenarios"]["base"]
    auto_estimate = input_payload.get("assumptions", {}).get("auto_estimate_buyout_fees", True)

    curves = {
        "EIBOR_1M": scenarios["EIBOR_1M"],
        "EIBOR_3M": scenarios["EIBOR_3M"]
    }

    cur = input_payload["current_terms"]
    new = input_payload["new_offer"]

    current_terms = Terms(
        bank=cur["bank"],
        index_type=cur["index_type"],
        margin_bps=cur["margin_bps"],
        floor_rate_annual=cur.get("floor_rate_annual", 0.0),
        reset_freq_months=cur["reset_freq_months"],
        life_insurance_method=cur.get("life_insurance_method", "none"),
        life_insurance_value=cur.get("life_insurance_value", 0.0),
        fees=cur.get("fees", []),
        es_percent=(cur.get("early_settlement", {}) or {}).get("percent_of_outstanding", 0.0),
        es_cap_aed=(cur.get("early_settlement", {}) or {}).get("cap_aed", 0.0)
    )
    new_terms = Terms(
        bank=new["bank"],
        index_type=new.get("reversion_index_type", "EIBOR_3M"),
        margin_bps=new.get("reversion_margin_bps", 0.0),
        floor_rate_annual=new.get("floor_rate_annual", 0.0),
        reset_freq_months=new.get("reset_freq_months", 3),
        life_insurance_method=cur.get("life_insurance_method", "none"),
        life_insurance_value=cur.get("life_insurance_value", 0.0),
        fees=new.get("fees", []),
        fixed_rate_annual=new["fixed_rate_annual"],
        fixed_months=new["fixed_months"],
        reversion_index_type=new.get("reversion_index_type", "EIBOR_3M"),
        reversion_margin_bps=new.get("reversion_margin_bps", 0.0),
    )

    recompute_policy = input_payload.get("assumptions", {}).get("recompute_policy", "on_reset_only")

    stay = run_option(principal, tenure, horizon, prepayments, "stay", current_terms, new_terms, curves, recompute_policy, auto_estimate)
    switch = run_option(principal, tenure, horizon, prepayments, "switch", current_terms, new_terms, curves, recompute_policy, auto_estimate)

    cum_stay = 0.0
    cum_switch = 0.0
    break_even = None
    for m in range(min(len(stay["cashflows"]), len(switch["cashflows"]))):
        cum_stay += stay["cashflows"][m]["emi"] + stay["cashflows"][m]["fees"] + stay["cashflows"][m]["insurance"]
        cum_switch += switch["cashflows"][m]["emi"] + switch["cashflows"][m]["fees"] + switch["cashflows"][m]["insurance"]
        if break_even is None and cum_switch <= cum_stay:
            break_even = m + 1

    recommendation = "switch" if switch["total_cash"] < stay["total_cash"] else "stay"

    return {
        "summary": {
            "stay_total_cash_out_aed": stay["total_cash"],
            "switch_total_cash_out_aed": switch["total_cash"],
            "break_even_month": break_even,
            "recommendation": recommendation,
            "assumptions_note": "Base scenario with automatic UAE buyout fee estimates applied."
        },
        "monthly_cashflows": stay["cashflows"] + switch["cashflows"],
        "fees_breakdown": {
            "stay": stay["fees_list"],
            "switch": switch["fees_list"]
        },
        "upfront_fees_applied": {
            "stay": stay["applied_upfront_fees"],
            "switch": switch["applied_upfront_fees"]
        }
    }
