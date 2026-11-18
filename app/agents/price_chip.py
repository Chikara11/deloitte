"""Deterministic M&A 'Price Chip' valuation adjustment engine."""

from __future__ import annotations

from app.agents.models import Finding, PriceChipItem


def compute_price_chips(
    findings: list[Finding],
    proposed_price_eur: float = 200_000_000.0,
) -> tuple[str, float, float, list[PriceChipItem]]:
    """Translate verified findings into Deloitte M&A valuation chips & deal status."""
    chips: list[PriceChipItem] = []
    tampering = any(f.category == "CYBER_TAMPERING" for f in findings)

    for f in findings:
        if not f.verified:
            continue
        if f.category == "LEGAL" and (f.metric_value or 0) > 20_000_000:
            impact = -0.5 * float(f.metric_value or 0)
            chips.append(
                PriceChipItem(
                    rule_name="Change-of-Control Concentration Risk (50% of €40M contract)",
                    impact_eur=impact,
                    action="Condition Precedent: Require MegaRetail written CoC waiver before closing",
                )
            )
        elif f.finding_id == "QNT-01" and (f.metric_value or 0) > 0:
            impact = -4.0 * float(f.metric_value or 0)
            chips.append(
                PriceChipItem(
                    rule_name="Revenue Overstatement Valuation Chip (4.0x EV/Rev multiple)",
                    impact_eur=impact,
                    action="Purchase Price Reduction: Reduce headline EV by 4.0x missing revenue",
                )
            )
        elif f.category == "FORENSIC" and (f.metric_value or 0) > 0:
            impact = -2.0 * float(f.metric_value or 0)
            chips.append(
                PriceChipItem(
                    rule_name="CEO Self-Dealing Exposure (2.0x Apex Logistics retainer)",
                    impact_eur=impact,
                    action="Special Escrow Holdback + Independent Forensic Audit",
                )
            )

    if tampering:
        chips.append(
            PriceChipItem(
                rule_name="Active Seller Document Tampering (Model Armor Block)",
                impact_eur=0.0,
                action="GOVERNANCE OVERRIDE: HALT / WALK-AWAY RECOMMENDED",
            )
        )

    total_chip = sum(c.impact_eur for c in chips)
    adjusted = max(0.0, proposed_price_eur + total_chip)

    if tampering or len([f for f in findings if f.severity == "CRITICAL"]) >= 2:
        status = "CRITICAL_WALK_AWAY"
    elif findings:
        status = "CAUTION"
    else:
        status = "CLEAR"

    return status, total_chip, adjusted, chips
