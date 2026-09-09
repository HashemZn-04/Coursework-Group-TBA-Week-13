"""
Verdict mapping only — the actual LLM call (governance-prompt contextual audit)
now runs inside n8n's "AI Contextual Audit" node, using the team's existing
OpenAI credential there, instead of a Python OpenAI client here. n8n already
computes risk_level via its "Final Risk Assessment" node and POSTs the result
to /api/audit for persistence. See governance_prompt.py for the prompt text
that needs to be pasted into that n8n node, and ticket_work/epic_3_tickets.md
("C3 — n8n-hosted variant") for the full wiring steps.
"""

RISK_TO_VERDICT = {"HIGH": "high_risk", "MEDIUM": "flagged", "LOW": "compliant"}


def map_verdict(risk_level: str) -> str:
    return RISK_TO_VERDICT.get(risk_level, "compliant")
