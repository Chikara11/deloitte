"""ADK Harness: 5-Gate HITL state machine, tool allow-list, Model Armor callbacks, Skeptic check & hash-chained audit events."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from app.agents.auditor import run_auditor_rules
from app.agents.bridge import generate_micro_briefs
from app.agents.exporter import render_control_sheet_md
from app.agents.models import AuditCase, CanonicalInvoice, Evidence, ExpertResponse, Finding, MicroBrief
from app.agents.synthesis import run_synthesis
from app.config import settings
from app.data.audit_logger import audit_logger
from app.security.gate1 import check_model_armor, server_vault

try:
    from google.adk.agents import LlmAgent

    ADK_AVAILABLE = True
except Exception:  # pragma: no cover
    LlmAgent = None  # type: ignore[assignment,misc]
    ADK_AVAILABLE = False

ADK_AGENTS: dict[str, Any] = {}
if ADK_AVAILABLE and LlmAgent is not None:
    ADK_AGENTS["AuditorAgent"] = LlmAgent(
        name="AuditorAgent",
        model=settings.gemini_fast_model,
        description="Deterministic financial audit rules + Gemini explanation under Skeptic evidence check.",
    )
    ADK_AGENTS["BridgeAgent"] = LlmAgent(
        name="BridgeAgent",
        model=settings.gemini_fast_model,
        description="Drafts micro-briefs for Tax & Legal Lawyer and Operational Consultant.",
    )
    ADK_AGENTS["SynthesisAgent"] = LlmAgent(
        name="SynthesisAgent",
        model=settings.gemini_pro_model,
        description="Aggregates rules + expert answers into confidence score and recommendation.",
    )

AGENT_TOOL_ALLOWLIST: dict[str, set[str]] = {
    "AuditorAgent": {"run_deterministic_audit", "explain_findings_llm"},
    "BridgeAgent": {"draft_micro_briefs"},
    "SynthesisAgent": {"compute_score_and_recommendation"},
}

_RAW_PII_CHECK_RE = re.compile(
    r"(\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)"
)


class HarnessSecurityError(RuntimeError):
    """Raised when an agent attempts a disallowed tool or Model Armor blocks content."""


class HarnessPermissionError(PermissionError):
    """Raised when a user lacks the required role for a gate or state transition."""


def _prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def before_tool_callback(agent_name: str, tool_name: str, session_id: str, tenant_id: str, case_id: str = "SYSTEM") -> None:
    allowed = AGENT_TOOL_ALLOWLIST.get(agent_name, set())
    if tool_name not in allowed:
        audit_logger.record_event(
            session_id=session_id,
            tenant_id=tenant_id,
            case_id=case_id,
            gate="HARNESS",
            actor_type="system",
            actor_id="HarnessGuard",
            actor_role="System",
            action="TOOL_ALLOWLIST_BLOCK",
            decision="BLOCK",
            comment=f"{agent_name} attempted disallowed tool {tool_name}",
        )
        raise HarnessSecurityError(f"Tool '{tool_name}' is not in allow-list for {agent_name}")


def before_model_callback(agent_name: str, prompt_text: str, session_id: str, tenant_id: str, case_id: str = "SYSTEM") -> None:
    verdict = check_model_armor(prompt_text)
    if not verdict.is_safe:
        audit_logger.record_event(
            session_id=session_id,
            tenant_id=tenant_id,
            case_id=case_id,
            gate="HARNESS",
            actor_type="system",
            actor_id="ModelArmor",
            actor_role="System",
            action="MODEL_ARMOR_BLOCK",
            decision="BLOCK",
            comment=f"{agent_name} prompt blocked ({verdict.matched_rule})",
        )
        raise HarnessSecurityError(f"Model Armor blocked prompt in {agent_name}: {verdict.matched_rule}")


def after_model_callback(agent_name: str, output_text: str, session_id: str, tenant_id: str, case_id: str = "SYSTEM") -> str:
    verdict = check_model_armor(output_text)
    if not verdict.is_safe:
        audit_logger.record_event(
            session_id=session_id,
            tenant_id=tenant_id,
            case_id=case_id,
            gate="HARNESS",
            actor_type="system",
            actor_id="ModelArmor",
            actor_role="System",
            action="MODEL_ARMOR_BLOCK",
            decision="BLOCK",
            comment=f"{agent_name} output blocked ({verdict.matched_rule})",
        )
        raise HarnessSecurityError(f"Model Armor blocked output in {agent_name}: {verdict.matched_rule}")
    return output_text


def skeptic_verify_findings(findings: list[Finding], session_id: str, tenant_id: str, case_id: str = "SYSTEM") -> list[Finding]:
    """Reject any finding lacking >=1 input evidence AND >=1 regulation or passport evidence."""
    verified: list[Finding] = []
    for f in findings:
        types = {e.source_type for e in f.evidences}
        if "input" in types and ("regulation" in types or "passport" in types):
            f.skeptic_verified = True
            verified.append(f)
        else:
            audit_logger.record_event(
                session_id=session_id,
                tenant_id=tenant_id,
                case_id=case_id,
                gate="SKEPTIC",
                actor_type="system",
                actor_id="SkepticCheck",
                actor_role="System",
                action="SKEPTIC_REJECT",
                decision="REJECT",
                comment=f"Rule {f.rule_id} missing input + regulation/passport evidence",
            )
    return verified


def _run_auditor_step(case: AuditCase, ledger_locator: dict[str, Any], feedback: str = "") -> AuditCase:
    before = {"status": case.status, "findings_count": len(case.findings)}
    audit_logger.set_step("AuditorAgent")
    before_tool_callback("AuditorAgent", "run_deterministic_audit", case.session_id, case.tenant_id, case.case_id)
    before_model_callback("AuditorAgent", case.invoice.model_dump_json(), case.session_id, case.tenant_id, case.case_id)

    findings, explanation = run_auditor_rules(case.invoice, ledger_locator)
    if feedback:
        explanation = f"[Re-exécuté suite au retour : {feedback}] {explanation}"

    after_model_callback("AuditorAgent", explanation, case.session_id, case.tenant_id, case.case_id)
    verified = skeptic_verify_findings(findings, case.session_id, case.tenant_id, case.case_id)

    failed_ids = [f.rule_id for f in verified if not f.passed]
    score = max(0, 100 - 20 * len(failed_ids))
    color = "green" if score >= 70 else ("amber" if score >= 40 else "red")

    case.findings = verified
    case.auditor_explanation = explanation
    case.auditor_feedback = feedback
    case.confidence_score = score
    case.score_color = color  # type: ignore[assignment]
    case.status = "AUDITOR_AGENT_DONE"
    case.harness_step = "PAUSE_GATE_2_AUDITOR"
    case.last_action = f"AuditorAgent terminé ({len(failed_ids)} anomalie(s)) — En attente Gate 2"

    ev_refs = [f"{e.file}:{e.locator}" for f in verified for e in f.evidences]
    audit_logger.record_event(
        session_id=case.session_id,
        tenant_id=case.tenant_id,
        case_id=case.case_id,
        gate="GATE_2",
        actor_type="agent",
        actor_id="AuditorAgent",
        actor_role="Agent",
        action="AUDITOR_RUN",
        decision="ANOMALIE" if failed_ids else "CONFORME",
        comment=f"Règles en échec: {failed_ids or 'aucune'}",
        before=before,
        after={"status": case.status, "failed_rules": failed_ids, "score": score},
        model_name=settings.gemini_fast_model,
        prompt_hash=_prompt_hash(case.invoice.model_dump_json()),
        evidence_refs=ev_refs,
    )
    audit_logger.save_case(case)
    return case


def _run_bridge_step(case: AuditCase, feedback: str = "") -> AuditCase:
    before = {"status": case.status, "briefs_count": len(case.micro_briefs)}
    audit_logger.set_step("BridgeAgent")
    before_tool_callback("BridgeAgent", "draft_micro_briefs", case.session_id, case.tenant_id, case.case_id)

    failed = [f for f in case.findings if not f.passed]
    if failed:
        briefs = generate_micro_briefs(case.invoice, failed)
        if feedback:
            for b in briefs:
                b.context_summary = f"[Révisé suite au retour : {feedback}] {b.context_summary}"
    else:
        briefs = [
            MicroBrief(
                role="AVOCAT",
                title="Confirmation fiscale (dossier conforme)",
                question="Confirmez-vous qu'aucune revue fiscale complémentaire n'est requise ?",
                options=["Conforme", "Non conforme", "Complément requis"],
                context_summary=f"Facture {case.invoice.invoice_id} conforme aux règles déterministes.",
            ),
            MicroBrief(
                role="CONSULTANT",
                title="Confirmation livraison (dossier conforme)",
                question="Confirmez-vous la réception de la prestation sur l'exercice 2026 ?",
                options=["Livré en 2026", "Livré en 2027", "Non livré"],
                context_summary=f"Prestation {case.invoice.description} datée au {case.invoice.service_date}.",
            ),
        ]

    case.micro_briefs = briefs
    case.status = "BRIEFS_DRAFTED"
    case.harness_step = "PAUSE_GATE_3_BRIEFS"
    case.last_action = "BridgeAgent terminé — En attente validation Gate 3"

    audit_logger.record_event(
        session_id=case.session_id,
        tenant_id=case.tenant_id,
        case_id=case.case_id,
        gate="GATE_3",
        actor_type="agent",
        actor_id="BridgeAgent",
        actor_role="Agent",
        action="BRIEFS_DRAFTED",
        decision="DRAFTED",
        comment=feedback or f"{len(briefs)} micro-brief(s) rédigé(s)",
        before=before,
        after={"status": case.status, "briefs": [b.model_dump() for b in briefs]},
        model_name=settings.gemini_fast_model,
        prompt_hash=_prompt_hash(str([f.rule_id for f in failed])),
    )
    audit_logger.save_case(case)
    return case


def _run_synthesis_step(case: AuditCase, feedback: str = "") -> AuditCase:
    before = {"status": case.status, "score": case.confidence_score}
    audit_logger.set_step("SynthesisAgent")
    before_tool_callback("SynthesisAgent", "compute_score_and_recommendation", case.session_id, case.tenant_id, case.case_id)

    score, color, rec = run_synthesis(case.findings, case.expert_responses)
    if feedback:
        rec = f"[Synthèse révisée : {feedback}] {rec}"

    case.confidence_score = score
    case.score_color = color  # type: ignore[assignment]
    case.recommendation = rec
    case.conclusion = rec
    case.synthesis_feedback = feedback
    case.status = "SYNTHESIS_DONE"
    case.harness_step = "PAUSE_GATE_5_FINAL"
    case.last_action = f"SynthesisAgent terminé (score {score}/100) — En attente Gate 5"

    audit_logger.record_event(
        session_id=case.session_id,
        tenant_id=case.tenant_id,
        case_id=case.case_id,
        gate="GATE_5",
        actor_type="agent",
        actor_id="SynthesisAgent",
        actor_role="Agent",
        action="SYNTHESIS_COMPUTED",
        decision=color.upper(),
        comment=feedback or rec,
        before=before,
        after={"status": case.status, "score": score, "color": color, "conclusion": rec},
        model_name=settings.gemini_pro_model,
        prompt_hash=_prompt_hash(rec),
    )
    audit_logger.save_case(case)
    return case


def execute_audit_harness(
    invoice: CanonicalInvoice,
    ledger_locator: dict[str, Any],
    session_id: str,
    scope_files: list[str] | None = None,
) -> AuditCase:
    """Ingest invoice -> RECEIVED -> SECURITY_CHECKED -> AuditorAgent -> PAUSE at Gate 2."""
    case_id = f"{invoice.tenant_id}:{invoice.invoice_id}"
    files = scope_files or [invoice.source_file, f"data/inputs/{invoice.tenant_id}/ledger.csv", f"data/passports/{invoice.tenant_id}.json"]

    case = AuditCase(
        case_id=case_id,
        session_id=session_id,
        tenant_id=invoice.tenant_id,
        status="RECEIVED",
        invoice=invoice,
        scope_files=files,
        harness_step="GATE_1_SECURITY",
        last_action="Pièce reçue",
    )
    audit_logger.record_event(
        session_id=session_id,
        tenant_id=invoice.tenant_id,
        case_id=case_id,
        gate="GATE_1",
        actor_type="system",
        actor_id="Ingestion",
        actor_role="System",
        action="CASE_RECEIVED",
        decision="RECEIVED",
        after={"status": "RECEIVED", "source_file": invoice.source_file},
    )

    case.status = "SECURITY_CHECKED"
    audit_logger.record_event(
        session_id=session_id,
        tenant_id=invoice.tenant_id,
        case_id=case_id,
        gate="GATE_1",
        actor_type="system",
        actor_id="Gate1Security",
        actor_role="System",
        action="SECURITY_PASSED",
        decision="PASS",
        before={"status": "RECEIVED"},
        after={"status": "SECURITY_CHECKED"},
    )
    audit_logger.save_case(case)
    return _run_auditor_step(case, ledger_locator)


def gate1_decide(case: AuditCase, decision: str, actor_id: str, actor_role: str, comment: str) -> AuditCase:
    """Gate 1 Security Analyst decision on a QUARANTINED file: Release | Confirm block."""
    if actor_role not in {"Analyste sécurité", "Manager"}:
        raise HarnessPermissionError("Rôle 'Analyste sécurité' requis pour Gate 1.")
    if case.status != "QUARANTINED":
        raise ValueError("Le dossier n'est pas en quarantaine.")
    if not comment.strip():
        raise ValueError("Un commentaire est obligatoire pour la décision Gate 1.")

    before = {"status": case.status, "quarantine_reason": case.quarantine_reason}
    if decision == "Release":
        case.status = "SECURITY_CHECKED"
        case.quarantine_reason = ""
        case.harness_step = "GATE_1_RELEASED"
        case.last_action = f"Quarantaine levée par {actor_id}"
        audit_logger.record_event(
            session_id=case.session_id,
            tenant_id=case.tenant_id,
            case_id=case.case_id,
            gate="GATE_1",
            actor_type="human",
            actor_id=actor_id,
            actor_role=actor_role,
            action="QUARANTINE_RELEASE",
            decision="RELEASE",
            comment=comment,
            before=before,
            after={"status": "SECURITY_CHECKED"},
        )
        audit_logger.save_case(case)
        return _run_auditor_step(case, {"row": 1, "column": "account"})

    case.status = "REJECTED"
    case.harness_step = "REJECTED"
    case.last_action = f"Blocage confirmé par {actor_id}"
    audit_logger.record_event(
        session_id=case.session_id,
        tenant_id=case.tenant_id,
        case_id=case.case_id,
        gate="GATE_1",
        actor_type="human",
        actor_id=actor_id,
        actor_role=actor_role,
        action="QUARANTINE_CONFIRM_BLOCK",
        decision="REJECTED",
        comment=comment,
        before=before,
        after={"status": "REJECTED"},
    )
    audit_logger.save_case(case)
    return case


def gate2_decide(
    case: AuditCase,
    decision: str,
    actor_id: str,
    actor_role: str,
    comment: str,
    scope_files: list[str] | None = None,
    rule_overrides: list[dict[str, Any]] | None = None,
    evidence_additions: list[dict[str, Any]] | None = None,
) -> AuditCase:
    """Gate 2 (after AuditorAgent): Approve | Edit | Reject."""
    if actor_role not in {"Auditeur", "Manager"}:
        raise HarnessPermissionError("Rôle 'Auditeur' ou 'Manager' requis pour Gate 2.")
    if decision in {"Edit", "Reject"} and not comment.strip():
        raise ValueError("Un commentaire est obligatoire pour Edit ou Reject.")

    before = {
        "status": case.status,
        "scope_files": list(case.scope_files),
        "findings": [f.model_dump() for f in case.findings],
    }

    if decision == "Reject":
        audit_logger.record_event(
            session_id=case.session_id,
            tenant_id=case.tenant_id,
            case_id=case.case_id,
            gate="GATE_2",
            actor_type="human",
            actor_id=actor_id,
            actor_role=actor_role,
            action="GATE2_REJECT",
            decision="REJECT",
            comment=comment,
            before=before,
            after={"status": "AUDITOR_AGENT_DONE", "feedback": comment},
        )
        return _run_auditor_step(case, {"row": 1, "column": "account"}, feedback=comment)

    if decision == "Edit":
        if scope_files is not None:
            case.scope_files = scope_files
        if rule_overrides:
            for ov in rule_overrides:
                for f in case.findings:
                    if f.rule_id == ov.get("rule_id"):
                        f.passed = bool(ov.get("passed", f.passed))
                        f.overridden_by = actor_id
                        f.override_justification = str(ov.get("justification", comment))
                        f.summary = f"[Surchargé par {actor_id}] {f.summary}"
        if evidence_additions:
            for add in evidence_additions:
                target_rule = add.get("rule_id")
                ev = Evidence(**add["evidence"])
                for f in case.findings:
                    if f.rule_id == target_rule:
                        f.evidences.append(ev)

    case.status = "GATE2_APPROVED"
    case.last_action = f"Gate 2 ({decision}) par {actor_id}"
    audit_logger.record_event(
        session_id=case.session_id,
        tenant_id=case.tenant_id,
        case_id=case.case_id,
        gate="GATE_2",
        actor_type="human",
        actor_id=actor_id,
        actor_role=actor_role,
        action=f"GATE2_{decision.upper()}",
        decision=decision.upper(),
        comment=comment or "Périmètre et preuves validés",
        before=before,
        after={"status": "GATE2_APPROVED", "scope_files": case.scope_files},
    )
    audit_logger.save_case(case)
    return _run_bridge_step(case)


def gate3_decide(
    case: AuditCase,
    decision: str,
    actor_id: str,
    actor_role: str,
    comment: str,
    edited_briefs: list[dict[str, Any]] | None = None,
) -> AuditCase:
    """Gate 3 (after BridgeAgent): Approve | Edit | Reject with PII check before experts see briefs."""
    if actor_role not in {"Auditeur", "Manager"}:
        raise HarnessPermissionError("Rôle 'Auditeur' ou 'Manager' requis pour Gate 3.")
    if decision in {"Edit", "Reject"} and not comment.strip():
        raise ValueError("Un commentaire est obligatoire pour Edit ou Reject.")

    before = {"status": case.status, "micro_briefs": [b.model_dump() for b in case.micro_briefs]}

    if decision == "Reject":
        audit_logger.record_event(
            session_id=case.session_id,
            tenant_id=case.tenant_id,
            case_id=case.case_id,
            gate="GATE_3",
            actor_type="human",
            actor_id=actor_id,
            actor_role=actor_role,
            action="GATE3_REJECT",
            decision="REJECT",
            comment=comment,
            before=before,
            after={"status": "BRIEFS_DRAFTED", "feedback": comment},
        )
        return _run_bridge_step(case, feedback=comment)

    if edited_briefs:
        updated: list[MicroBrief] = []
        for b_data in edited_briefs:
            updated.append(MicroBrief(**b_data))
        case.micro_briefs = updated

    # Mandatory PII check: ensure no unmasked IBAN/email leaks into micro-briefs
    combined_text = "\n".join(f"{b.title}\n{b.question}\n{b.context_summary}" for b in case.micro_briefs)
    if _RAW_PII_CHECK_RE.search(combined_text):
        # Auto-mask or reject; here we block approval until masked
        masked, count = server_vault.pseudonymize(combined_text)
        audit_logger.record_event(
            session_id=case.session_id,
            tenant_id=case.tenant_id,
            case_id=case.case_id,
            gate="GATE_3",
            actor_type="system",
            actor_id="DLP_Gate3",
            actor_role="System",
            action="PII_LEAK_BLOCK",
            decision="BLOCK",
            comment=f"Données personnelles non masquées détectées ({count})",
        )
        raise HarnessSecurityError("Des données personnelles non masquées (IBAN/email) ont été détectées dans les briefs.")

    case.status = "GATE3_APPROVED"
    case.harness_step = "PAUSE_GATE_4_EXPERTS"
    case.last_action = f"Briefs validés ({decision}) par {actor_id} — Envoyés aux experts"
    audit_logger.record_event(
        session_id=case.session_id,
        tenant_id=case.tenant_id,
        case_id=case.case_id,
        gate="GATE_3",
        actor_type="human",
        actor_id=actor_id,
        actor_role=actor_role,
        action=f"GATE3_{decision.upper()}",
        decision=decision.upper(),
        comment=comment or "Briefs approuvés sans données personnelles exposées",
        before=before,
        after={"status": "GATE3_APPROVED", "micro_briefs": [b.model_dump() for b in case.micro_briefs]},
    )
    audit_logger.save_case(case)
    return case


def gate4_expert_answer(
    case: AuditCase,
    expert_slot: str,  # AVOCAT | CONSULTANT
    decision: str,
    comment: str,
    actor_id: str,
    actor_role: str,
) -> AuditCase:
    """Gate 4: Avocat Tax & Legal and Consultant answer their approved micro-brief."""
    if case.status not in {"GATE3_APPROVED", "EXPERTS_ANSWERED"}:
        raise HarnessPermissionError("Les briefs doivent être approuvés (Gate 3) avant la réponse des experts.")
    if expert_slot == "AVOCAT" and actor_role not in {"Avocat", "Manager"}:
        raise HarnessPermissionError("Rôle 'Avocat' requis pour cette réponse.")
    if expert_slot == "CONSULTANT" and actor_role not in {"Consultant", "Manager"}:
        raise HarnessPermissionError("Rôle 'Consultant' requis pour cette réponse.")

    before = {"status": case.status, "expert_responses": {k: v.model_dump() for k, v in case.expert_responses.items()}}
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    case.expert_responses[expert_slot] = ExpertResponse(
        role=expert_slot,  # type: ignore[arg-type]
        decision=decision,
        comment=comment,
        responder=actor_id,
        timestamp=ts,
    )
    case.last_action = f"Réponse {expert_slot} ({decision})"

    audit_logger.record_event(
        session_id=case.session_id,
        tenant_id=case.tenant_id,
        case_id=case.case_id,
        gate="GATE_4",
        actor_type="human",
        actor_id=actor_id,
        actor_role=actor_role,
        action=f"EXPERT_{expert_slot}_ANSWER",
        decision=decision,
        comment=comment,
        before=before,
        after={"expert_responses": {k: v.model_dump() for k, v in case.expert_responses.items()}},
    )

    if "AVOCAT" in case.expert_responses and "CONSULTANT" in case.expert_responses:
        case.status = "EXPERTS_ANSWERED"
        audit_logger.save_case(case)
        return _run_synthesis_step(case)

    audit_logger.save_case(case)
    return case


def gate5_decide(
    case: AuditCase,
    decision: str,
    actor_id: str,
    actor_role: str,
    comment: str,
    edited_conclusion: str | None = None,
) -> AuditCase:
    """Gate 5 (after SynthesisAgent): Approve | Edit | Reject. Manager required if score < 40."""
    if case.status != "SYNTHESIS_DONE":
        raise ValueError("La synthèse doit être terminée (SYNTHESIS_DONE) avant Gate 5.")
    if case.confidence_score < 40 and actor_role != "Manager":
        raise HarnessPermissionError("Score < 40 : le rôle 'Manager' est obligatoire pour valider Gate 5.")
    if actor_role not in {"Auditeur", "Manager"}:
        raise HarnessPermissionError("Rôle 'Auditeur' ou 'Manager' requis pour Gate 5.")
    if decision in {"Edit", "Reject"} and not comment.strip():
        raise ValueError("Un commentaire est obligatoire pour Edit ou Reject.")

    before = {"status": case.status, "conclusion": case.conclusion}

    if decision == "Reject":
        audit_logger.record_event(
            session_id=case.session_id,
            tenant_id=case.tenant_id,
            case_id=case.case_id,
            gate="GATE_5",
            actor_type="human",
            actor_id=actor_id,
            actor_role=actor_role,
            action="GATE5_REJECT",
            decision="REJECT",
            comment=comment,
            before=before,
            after={"status": "SYNTHESIS_DONE", "feedback": comment},
        )
        return _run_synthesis_step(case, feedback=comment)

    if decision == "Edit" and edited_conclusion:
        case.conclusion = edited_conclusion
        case.recommendation = edited_conclusion

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    case.validator_decision = {
        "decision": decision,
        "validator": actor_id,
        "role": actor_role,
        "comment": comment,
        "timestamp": ts,
    }
    case.status = "GATE5_APPROVED"
    audit_logger.record_event(
        session_id=case.session_id,
        tenant_id=case.tenant_id,
        case_id=case.case_id,
        gate="GATE_5",
        actor_type="human",
        actor_id=actor_id,
        actor_role=actor_role,
        action=f"GATE5_{decision.upper()}",
        decision=decision.upper(),
        comment=comment or "Validation finale accordée",
        before=before,
        after={"status": "GATE5_APPROVED", "conclusion": case.conclusion},
    )

    # Generate Control Documentation Sheet only after Gate 5 approval
    case.status = "DOCUMENTED"
    case.harness_step = "COMPLETE"
    case.last_action = f"Fiche de contrôle générée ({actor_id})"
    case.control_sheet_md = render_control_sheet_md(case)

    audit_logger.record_event(
        session_id=case.session_id,
        tenant_id=case.tenant_id,
        case_id=case.case_id,
        gate="EXPORT",
        actor_type="system",
        actor_id="Exporter",
        actor_role="System",
        action="CONTROL_SHEET_GENERATED",
        decision="DOCUMENTED",
        comment="Fiche de contrôle générée après validation Gate 5",
        before={"status": "GATE5_APPROVED"},
        after={"status": "DOCUMENTED"},
    )
    audit_logger.save_case(case)
    return case


def bulk_approve_green(tenant_id: str, gate: str, actor_id: str, actor_role: str) -> int:
    """Bulk approval allowed at Gates 2 and 5 for green cases only."""
    if actor_role not in {"Auditeur", "Manager"}:
        raise HarnessPermissionError("Rôle 'Auditeur' ou 'Manager' requis pour l'approbation en masse.")
    if gate not in {"GATE_2", "GATE_5"}:
        raise ValueError("L'approbation en masse est autorisée uniquement aux Gates 2 et 5.")

    count = 0
    for case in audit_logger.list_cases(tenant_id=tenant_id):
        if case.score_color != "green":
            continue
        if gate == "GATE_2" and case.status == "AUDITOR_AGENT_DONE":
            c = gate2_decide(case, "Approve", actor_id, actor_role, "Approbation en masse (dossier vert)")
            c = gate3_decide(c, "Approve", actor_id, actor_role, "Auto-approbation briefs (dossier vert)")
            c = gate4_expert_answer(c, "AVOCAT", "Conforme", "Dossier vert conforme", actor_id, "Manager")
            gate4_expert_answer(c, "CONSULTANT", "Livré en 2026", "Dossier vert conforme", actor_id, "Manager")
            count += 1
        elif gate == "GATE_5" and case.status == "SYNTHESIS_DONE":
            gate5_decide(case, "Approve", actor_id, actor_role, "Approbation finale en masse (dossier vert)")
            count += 1
    return count
