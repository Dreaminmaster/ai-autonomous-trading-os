from __future__ import annotations

import pytest

from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_announcements import (
    NOTICE_SPECS,
    final_transition_notice_proofs,
    parse_known_transition_notice,
)


PAGES = {
    "known-transition-eth-2024-04-18": """
      <h1>OKX to adjust the minimum order quantities for several futures</h1>
      <p>Published on Apr 12, 2024</p>
      <p>This update is scheduled for 6:00 am - 8:00 am UTC on April 18, 2024.</p>
      <table><tr><td>Perpetual</td><td>ETH/USDT</td><td>1</td><td>0.1</td></tr></table>
    """,
    "known-transition-btc-2024-04-25": """
      <h1>OKX to adjust the minimum order quantities for several futures</h1>
      <p>Published on Apr 19, 2024</p>
      <p>This update is scheduled for 6:00 am - 8:00 am UTC on April 25, 2024.</p>
      <table><tr><td>Perpetual</td><td>BTC/USDT</td><td>1</td><td>0.01</td><td>0.1</td><td>0.001</td></tr></table>
    """,
    "known-transition-eth-original-2024-12-18": """
      <h1>OKX to adjust the minimum order quantities for ETHUSDT perpetual and expiry futures</h1>
      <p>Published on Dec 11, 2024</p>
      <p>This update is scheduled for 6:00 am - 8:00 am UTC on December 18, 2024.</p>
      <table><tr><td>Perpetual</td><td>ETH/USDT</td><td>0.1</td><td>0.01</td><td>0.01</td><td>0.001</td></tr></table>
    """,
    "known-transition-eth-postponed-2025-01-09": """
      <h1>OKX to postpone adjusting minimum order quantities for ETHUSDT perpetual and expiry futures</h1>
      <p>Published on Dec 16, 2024</p>
      <p>The new adjustment time will be 6:00 am - 10:00 am UTC on January 9, 2025.</p>
      <table><tr><td>Perpetual</td><td>ETH/USDT</td><td>0.1</td><td>0.01</td><td>0.01</td><td>0.001</td></tr></table>
    """,
    "known-transition-btc-2025-01-22": """
      <h1>OKX to adjust the minimum order quantities of spots and futures</h1>
      <p>Published on Jan 17, 2025</p>
      <p>This update is scheduled for 6:00 am - 8:00 am UTC on January 22, 2025.</p>
      <table><tr><td>Perpetual</td><td>BTC/USDT</td><td>0.1</td><td>0.001</td><td>0.01</td><td>0.0001</td></tr></table>
    """,
}


def test_all_bound_transition_notices_parse_exact_windows_and_steps() -> None:
    parsed = []
    for request_id, html in PAGES.items():
        proof = parse_known_transition_notice(
            html.encode(), request_id=request_id, source_id=f"source-{request_id}"
        )
        spec = NOTICE_SPECS[request_id]
        assert proof["instrument"] == spec.instrument
        assert proof["window_start"] == spec.window_start
        assert proof["window_end_exclusive"] == spec.window_end_exclusive
        assert proof["old_lot"] == spec.old_step
        assert proof["new_lot"] == spec.new_step
        parsed.append(proof)

    final = final_transition_notice_proofs(parsed)
    assert len(final) == 4
    assert all(row["final_authority"] is True for row in final)
    assert not any(row["window_start"] == "2024-12-18T06:00:00Z" for row in final)


def test_notice_parser_rejects_wrong_window_or_values() -> None:
    wrong_window = PAGES["known-transition-btc-2025-01-22"].replace(
        "January 22, 2025", "January 23, 2025"
    )
    with pytest.raises(SourceAuthorityError, match="UTC window"):
        parse_known_transition_notice(
            wrong_window.encode(),
            request_id="known-transition-btc-2025-01-22",
            source_id="source-btc",
        )

    wrong_values = PAGES["known-transition-eth-2024-04-18"].replace(
        "<td>1</td><td>0.1</td>", "<td>2</td><td>0.2</td>"
    )
    with pytest.raises(SourceAuthorityError, match="contract steps"):
        parse_known_transition_notice(
            wrong_values.encode(),
            request_id="known-transition-eth-2024-04-18",
            source_id="source-eth",
        )


def test_final_notice_set_requires_all_four_effective_transitions() -> None:
    parsed = [
        parse_known_transition_notice(
            html.encode(), request_id=request_id, source_id=f"source-{request_id}"
        )
        for request_id, html in PAGES.items()
    ]
    with pytest.raises(SourceAuthorityError, match="incomplete"):
        final_transition_notice_proofs(parsed[:-1])
