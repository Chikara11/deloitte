"""ADK-governed Runner Harness: allow-list callbacks, Model Armor hooks, Pydantic retry, Skeptic check."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import ValidationError

from app.agents.auditor import run_auditor_rules
from app.agents.bridge import generate_micro_briefs
from app.agents.exporter import render_control_sheet_md
from app.agents.models import AuditCase, CanonicalInvoice, ExpertResponse, Finding
from app.agents.synthesis import run_synthesis
from app.config import settings
from app.data.audit_logger import audit_logger
from app.security.gate1 import check_model_armor

# Per-agent tool allow-list enforced via before_tool_callback
AGENT_TOOL_ALLOWLIST: dict[str, set[str]] = {
    "AuditorAgent": {"run_deterministic_rules", "read_passport", "read_regulation"},
    "BridgeAgent": {"draft_micro_briefs"},
    "SynthesisAgent": {"compute_confidence_score"},
}


class HarnessSecurityError(Exception):
    pass


def before_tool_callback(agent_name: str, tool_name: str, session_id: str, tenant_id: str) -> None:
    """Enforce per-agent tool allow-list."""
    allowed = AGENT_TOOL_ALLOWLIST.get(agent_name, set())
    if tool_name not in allowed:
        audit_logger.log(session_id, tenant_id, agent_name, "TOOL_ALLOWLIST_BLOCK", "BLOCK", {"tool": tool_name})
        raise HarnessSecurityError(f"Tool '{tool_name}' not in allow-list for {agent_name}")


def before_model_callback(agent_name: str, prompt: str, session_id: str, tenant_id: str) -> None:
    """Run Model Armor check before sending any prompt to Gemini."""
    verdict = check_model_armor(prompt)
    if not verdict.is_safe:
        audit_logger.log(session_id, tenant_id, agent_name, "MODEL_ARMOR_BLOCK", "BLOCK", {"phase": "before_model", "rule": verdict.matched_rule})
        raise HarnessSecurityError(f"before_model_callback blocked: {verdict.matched_rule}")


def after_model_callback(agent_name: str, response_text: str, session_id: str, tenant_id: str) -> None:
    """Run Model Armor check on model output."""
    verdict = check_model_armor(response_text)
    if not verdict.is_safe:
        audit_logger.log(session_id, tenant_id, agent_name, "MODEL_ARMOR_BLOCK", "BLOCK", {"phase": "after_model", "rule": verdict.matched_rule})
        raise HarnessSecurityError(f"after_model_callback blocked: {verdict.matched_rule}")


def skeptic_verify_findings(findings: list[Finding], session_id: str, tenant_id: str) -> list[Finding]:
    """Mandatory Evidence Traceability Gate: reject any finding lacking >=1 input AND >=1 regulation/passport evidence."""
    verified: list[Finding] = []
    for f in findings:
        has_input = any(e.source_type == "input" for e in f.evidences)
        has_norm = any(e.source_type in ("regulation", "passport") for e in f.evidences)
        if not (has_input and has_norm):
            f.skeptic_verified = False
            audit_logger.log(
                session_id,
                tenant_id,
                "SkepticGate",
                "SKEPTIC_REJECT",
                "REJECT",
                {"rule_id": f.rule_id, "reason": "Missing mandatory input + regulation/passport evidence"},
            )
            continue
        f.skeptic_verified = True
        verified.append(f)
    return verified


def _run_with_pydantic_retry(fn: Callable[[], Any], schema_cls: Any, max_retries: int = 1) -> Any:
    """Validate output against Pydantic schema with 1 retry."""
    last_err: Exception | None = None
    for _ in range(max_retries + 1):
        try:
            res = fn()
            if isinstance(res, list):
                return [schema_cls.model_validate(item.model_dump() if hasattr(item, "model_dump") else item) for item in res]
            return schema_cls.model_validate(res.model_dump() if hasattr(res, "model_dump") else res)
        except ValidationError as exc:
            last_err = exc
    raise last_err  # type: ignore[misc]


def _maybe_gemini_explain(
    agent_name: str,
    prompt: str,
    fallback: str,
    session_id: str,
    tenant_id: str,
) -> str:
    """Invoke Gemini on Vertex AI guarded by before/after_model_callback."""
    before_model_callback(agent_name, prompt, session_id, tenant_id)
    if settings.use_real_gcp_data:
        try:
            from google import genai

            client = genai.Client(vertexai=True, project=settings.gcp_project_id, location=settings.gcp_region)
            resp = client.models.generate_content(model=settings.gemini_fast_model, contents=prompt)
            if resp.text:
                out = resp.text.strip()
                after_model_callback(agent_name, out, session_id, tenant_id)
                return out
        except Exception:
            pass
    after_model_callback(agent_name, fallback, session_id, tenant_id)
    return fallback


def execute_audit_harness(invoice: CanonicalInvoice, locators: dict[str, Any], session_id: str | None = None) -> AuditCase:
    """Run fixed ADK Harness: AuditorAgent -> Skeptic -> (BridgeAgent) -> SynthesisAgent -> Pause at Gate 2/3."""
    sid = session_id or f"sess-{uuid.uuid4().hex[:8]}"
    audit_logger.set_step("AUDITOR_AGENT")
    before_tool_callback("AuditorAgent", "run_deterministic_rules", sid, invoice.tenant_id)

    raw_findings, base_expl = run_auditor_rules(invoice, locators)
    findings: list[Finding] = _run_with_pydantic_retry(lambda: raw_findings, Finding, max_retries=1)

    audit_logger.set_step("SKEPTIC_VERIFICATION")
    verified_findings = skeptic_verify_findings(findings, sid, invoice.tenant_id)
    failed = [f for f in verified_findings if not f.passed]

    prompt = (
        f"Résume en 2 phrases claires en français les résultats d'audit de la facture {invoice.invoice_id} "
        f"({invoice.amount_ht:,.0f} €) : {base_expl}"
    )
    explanation = _maybe_gemini_explain("AuditorAgent", prompt, base_expl, sid, invoice.tenant_id)

    audit_logger.log(
        sid,
        invoice.tenant_id,
        "AuditorAgent",
        "RULES_EVALUATED",
        "ANOMALIE" if failed else "PASS",
        {"invoice_id": invoice.invoice_id, "failed": [f.rule_id for f in failed]},
    )

    micro_briefs = []
    if failed:
        audit_logger.set_step("BRIDGE_AGENT")
        before_tool_callback("BridgeAgent", "draft_micro_briefs", sid, invoice.tenant_id)
        micro_briefs = generate_micro_briefs(invoice, verified_findings)
        audit_logger.log(sid, invoice.tenant_id, "BridgeAgent", "MICRO_BRIEFS_CREATED", "INFO", {"invoice_id": invoice.invoice_id})

    audit_logger.set_step("SYNTHESIS_AGENT")
    before_tool_callback("SynthesisAgent", "compute_confidence_score", sid, invoice.tenant_id)
    score, color, rec = run_synthesis(verified_findings, {})
    audit_logger.log(sid, invoice.tenant_id, "SynthesisAgent", "SCORE_COMPUTED", "INFO", {"score": score, "color": color})

    next_step = "PAUSE_GATE_2_EXPERTS" if failed else "PAUSE_GATE_3_AUDITOR"
    audit_logger.set_step(next_step)

    case = AuditCase(
        case_id=f"{invoice.tenant_id}:{invoice.invoice_id}",
        session_id=sid,
        tenant_id=invoice.tenant_id,
        status="Anomalie" if failed else "Conforme",
        invoice=invoice,
        findings=verified_findings,
        auditor_explanation=explanation,
        micro_briefs=micro_briefs,
        confidence_score=score,
        score_color=color,
        recommendation=rec,
        harness_step=next_step,
        last_action="Anomalie détectée — attente experts" if failed else "Conforme — prêt pour validation",
    )
    case.control_sheet_md = render_control_sheet_md(case)
    return case


def resume_gate2_expert(case: AuditCase, role: str, decision: str, comment: str, responder: str) -> AuditCase:
    """Resume harness at Gate 2 with expert response and re-run SynthesisAgent."""
    role_u = role.upper()
    case.expert_responses[role_u] = ExpertResponse(
        role=role_u,  # type: ignore[arg-type]
        decision=decision,
        comment=comment,
        responder=responder,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    audit_logger.log(case.session_id, case.tenant_id, f"Gate2_{role_u}", "EXPERT_DECISION", "INFO", {"invoice_id": case.invoice.invoice_id, "decision": decision})

    score, color, rec = run_synthesis(case.findings, case.expert_responses)
    case.confidence_score = score
    case.score_color = color
    case.recommendation = rec
    case.harness_step = "PAUSE_GATE_3_AUDITOR"
    case.last_action = f"{role_u}: {decision}"
    case.control_sheet_md = render_control_sheet_md(case)
    return case


def resume_gate3_auditor(case: AuditCase, decision: str, validator: str, comment: str = "") -> AuditCase:
    """Resume harness at Gate 3 with final auditor validation/rejection."""
    case.status = "Validé" if decision.lower() == "valider" else "Rejeté"
    case.validator_decision = {
        "decision": decision,
        "validator": validator,
        "comment": comment,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    case.harness_step = "COMPLETED"
    case.last_action = f"Gate 3: {decision} par {validator}"
    audit_logger.set_step("COMPLETED")
    audit_logger.log(case.session_id, case.tenant_id, "Gate3_Auditor", "AUDITOR_DECISION", "PASS" if case.status == "Validé" else "REJECT", {"invoice_id": case.invoice.invoice_id})
    case.control_sheet_md = render_control_sheet_md(case)
    return case
