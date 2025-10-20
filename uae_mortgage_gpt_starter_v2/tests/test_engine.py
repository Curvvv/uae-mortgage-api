
import json
from backend.calculator import compare

def test_compare_smoke():
    payload = json.load(open('sample_data/sample_input.json'))
    out = compare(payload)
    assert "summary" in out
    assert out["summary"]["stay_total_cash_out_aed"] > 0
    assert out["summary"]["switch_total_cash_out_aed"] > 0
    # Check that auto estimated fees were applied for switch
    assert out["upfront_fees_applied"]["switch"] > 0
