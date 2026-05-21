"""Template-based document generator.

Pure-Python fallback that produces Markdown documents from a project's
answers, in either French or English depending on ``project.language``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from planner.models import Project


# ---------------------------------------------------------------------------
# Localization
# ---------------------------------------------------------------------------
_STRINGS = {
    "en": {
        "bp_title": "Business Plan",
        "bp_exec": "Executive Summary",
        "bp_problem": "Problem",
        "bp_solution": "Solution",
        "bp_audience": "Target Audience",
        "bp_market": "Market & Competition",
        "bp_business": "Business Model",
        "bp_metrics": "Success Metrics",
        "bp_milestones": "Milestones",
        "bp_risks": "Risks",
        "cdc_title": "Specifications (Cahier des Charges)",
        "cdc_context": "1. Context",
        "cdc_scope": "2. Scope",
        "cdc_in": "In scope",
        "cdc_nice": "Nice to have",
        "cdc_out": "Out of scope",
        "cdc_functional": "3. Functional Requirements",
        "cdc_nonfunc": "4. Non-Functional Requirements",
        "cdc_stack": "5. Technical Stack",
        "cdc_data": "6. Data Model",
        "cdc_deliv": "7. Deliverables",
        "cdc_planning": "8. Planning & Constraints",
        "us_title": "User Stories",
        "us_intro": "Generated from the personas and features.",
        "us_template": "**US-{n}** — As a **{role}**, I want to **{feature}**, so that **{benefit}**.",
        "no_personas": "User",
        "no_benefit": "I can reach my goal",
        "ms_design": "Design & spec sign-off",
        "ms_mvp": "MVP build",
        "ms_beta": "Closed beta",
        "ms_launch": "Public launch",
        "label_competitors": "Competitors",
        "label_diff": "Differentiation",
        "label_timeline": "Timeline",
        "label_budget": "Budget / Team",
        "label_hosting": "Hosting",
        "label_integrations": "Integrations",
        "label_audience": "Target users",
        "deliv_code": "Working application matching the in-scope features",
        "deliv_docs": "Documentation (README, setup guide, this Cahier des Charges)",
        "deliv_tests": "Automated tests for critical flows",
        "deliv_demo": "Demo environment / staging deployment",
        "nonfunc_perf": "Performance: pages respond in under 500ms on the target hardware.",
        "nonfunc_sec": "Security: secrets in env vars, dependencies kept up to date, HTTPS in production.",
        "nonfunc_avail": "Availability: target 99% uptime for the MVP.",
        "nonfunc_obs": "Observability: structured logs and a simple error tracker.",
    },
    "fr": {
        "bp_title": "Business Plan",
        "bp_exec": "Résumé exécutif",
        "bp_problem": "Problème",
        "bp_solution": "Solution",
        "bp_audience": "Public cible",
        "bp_market": "Marché et concurrence",
        "bp_business": "Modèle économique",
        "bp_metrics": "Indicateurs de succès",
        "bp_milestones": "Jalons",
        "bp_risks": "Risques",
        "cdc_title": "Cahier des Charges",
        "cdc_context": "1. Contexte",
        "cdc_scope": "2. Périmètre",
        "cdc_in": "Dans le périmètre",
        "cdc_nice": "Souhaitable",
        "cdc_out": "Hors périmètre",
        "cdc_functional": "3. Exigences fonctionnelles",
        "cdc_nonfunc": "4. Exigences non fonctionnelles",
        "cdc_stack": "5. Stack technique",
        "cdc_data": "6. Modèle de données",
        "cdc_deliv": "7. Livrables",
        "cdc_planning": "8. Planning et contraintes",
        "us_title": "User Stories",
        "us_intro": "Générées à partir des personas et des fonctionnalités.",
        "us_template": "**US-{n}** — En tant que **{role}**, je veux **{feature}**, afin de **{benefit}**.",
        "no_personas": "Utilisateur",
        "no_benefit": "atteindre mon objectif",
        "ms_design": "Validation du design et des specs",
        "ms_mvp": "Réalisation du MVP",
        "ms_beta": "Beta fermée",
        "ms_launch": "Lancement public",
        "label_competitors": "Concurrents",
        "label_diff": "Différenciation",
        "label_timeline": "Délais",
        "label_budget": "Budget / Équipe",
        "label_hosting": "Hébergement",
        "label_integrations": "Intégrations",
        "label_audience": "Utilisateurs cibles",
        "deliv_code": "Application fonctionnelle couvrant les fonctionnalités dans le périmètre",
        "deliv_docs": "Documentation (README, guide d'installation, ce cahier des charges)",
        "deliv_tests": "Tests automatisés sur les parcours critiques",
        "deliv_demo": "Environnement de démonstration / déploiement de staging",
        "nonfunc_perf": "Performance : les pages répondent en moins de 500ms sur le matériel cible.",
        "nonfunc_sec": "Sécurité : secrets en variables d'environnement, dépendances à jour, HTTPS en production.",
        "nonfunc_avail": "Disponibilité : objectif de 99% pour le MVP.",
        "nonfunc_obs": "Observabilité : logs structurés et suivi d'erreurs basique.",
    },
}


def _t(project: "Project", key: str) -> str:
    return _STRINGS.get(project.language, _STRINGS["en"])[key]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_documents(project: "Project") -> dict[str, str]:
    return {
        "business_plan": business_plan(project),
        "specifications": specifications(project),
        "user_stories": user_stories(project),
    }


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def business_plan(project: "Project") -> str:
    L = lambda k: _t(project, k)  # noqa: E731
    lines = [f"# {L('bp_title')} — {project.name}"]
    if project.tagline:
        lines.append(f"_{project.tagline}_")
    lines.append("")
    lines.append(f"## {L('bp_exec')}")
    lines.append(project.solution or project.problem or "")
    lines.append("")
    lines.append(f"## {L('bp_problem')}")
    lines.append(project.problem or "—")
    lines.append("")
    lines.append(f"## {L('bp_solution')}")
    lines.append(project.solution or "—")
    lines.append("")
    lines.append(f"## {L('bp_audience')}")
    lines.append(project.target_users or "—")
    if project.personas:
        lines.append("")
        for persona in project.personas:
            lines.append(
                f"- **{persona.get('name', '')}** ({persona.get('role', '')}): "
                f"{persona.get('goal', '')}"
            )
    lines.append("")
    lines.append(f"## {L('bp_market')}")
    if project.competitors:
        lines.append(f"**{L('label_competitors')}:** {project.competitors}")
    if project.differentiation:
        lines.append("")
        lines.append(f"**{L('label_diff')}:** {project.differentiation}")
    lines.append("")
    lines.append(f"## {L('bp_business')}")
    lines.append(project.business_model or "—")
    lines.append("")
    lines.append(f"## {L('bp_metrics')}")
    lines.append(project.success_metrics or "—")
    lines.append("")
    lines.append(f"## {L('bp_milestones')}")
    for ms_key in ("ms_design", "ms_mvp", "ms_beta", "ms_launch"):
        lines.append(f"- {L(ms_key)}")
    lines.append("")
    lines.append(f"## {L('bp_risks')}")
    lines.append(project.risks or "—")
    return "\n".join(lines).strip() + "\n"


def specifications(project: "Project") -> str:
    L = lambda k: _t(project, k)  # noqa: E731
    lines = [f"# {L('cdc_title')} — {project.name}"]
    if project.tagline:
        lines.append(f"_{project.tagline}_")
    lines.append("")
    lines.append(f"## {L('cdc_context')}")
    lines.append(project.problem or "—")
    if project.solution:
        lines.append("")
        lines.append(project.solution)
    lines.append("")
    lines.append(f"## {L('cdc_scope')}")
    lines.append(f"### {L('cdc_in')}")
    lines.extend(_bullets(project.features))
    lines.append("")
    lines.append(f"### {L('cdc_nice')}")
    lines.extend(_bullets(project.nice_to_have))
    lines.append("")
    lines.append(f"### {L('cdc_out')}")
    lines.extend(_bullets(project.out_of_scope))
    lines.append("")
    lines.append(f"## {L('cdc_functional')}")
    if project.features:
        for i, feat in enumerate(project.features, start=1):
            lines.append(f"- **FR-{i:02d}** — {feat}")
    else:
        lines.append("—")
    lines.append("")
    lines.append(f"## {L('cdc_nonfunc')}")
    for nf_key in ("nonfunc_perf", "nonfunc_sec", "nonfunc_avail", "nonfunc_obs"):
        lines.append(f"- {L(nf_key)}")
    lines.append("")
    lines.append(f"## {L('cdc_stack')}")
    if project.stack:
        lines.append(f"- **Stack:** {project.stack}")
    if project.hosting:
        lines.append(f"- **{L('label_hosting')}:** {project.hosting}")
    if project.integrations:
        lines.append(f"- **{L('label_integrations')}:** {project.integrations}")
    if not (project.stack or project.hosting or project.integrations):
        lines.append("—")
    lines.append("")
    lines.append(f"## {L('cdc_data')}")
    if project.entities:
        for ent in project.entities:
            lines.append(f"### {ent.get('name', '')}")
            for field in ent.get("fields", []) or ["—"]:
                lines.append(f"- {field}")
            lines.append("")
    else:
        lines.append("—")
    lines.append("")
    lines.append(f"## {L('cdc_deliv')}")
    for d_key in ("deliv_code", "deliv_docs", "deliv_tests", "deliv_demo"):
        lines.append(f"- {L(d_key)}")
    lines.append("")
    lines.append(f"## {L('cdc_planning')}")
    if project.timeline:
        lines.append(f"- **{L('label_timeline')}:** {project.timeline}")
    if project.budget:
        lines.append(f"- **{L('label_budget')}:** {project.budget}")
    if project.risks:
        lines.append(f"- **{L('bp_risks')}:** {project.risks}")
    if not (project.timeline or project.budget or project.risks):
        lines.append("—")
    return "\n".join(lines).strip() + "\n"


def user_stories(project: "Project") -> str:
    L = lambda k: _t(project, k)  # noqa: E731
    lines = [f"# {L('us_title')} — {project.name}", "", L("us_intro"), ""]
    personas = project.personas or [{"role": L("no_personas"), "name": L("no_personas")}]
    features = list(project.features or []) + list(project.nice_to_have or [])
    if not features:
        lines.append("—")
        return "\n".join(lines) + "\n"
    n = 1
    for persona in personas:
        role = persona.get("role") or persona.get("name") or L("no_personas")
        benefit = persona.get("goal") or L("no_benefit")
        for feat in features:
            lines.append(L("us_template").format(n=n, role=role, feature=feat, benefit=benefit))
            n += 1
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _bullets(items) -> list[str]:
    if not items:
        return ["—"]
    return [f"- {x}" for x in items]


def custom_stub(project: "Project", title: str, prompt: str) -> str:
    """Fallback used when no Claude key is available for a custom doc.

    Records the prompt so the user can write the doc themselves and shows
    the project context inline.
    """

    lines = [
        f"# {title}",
        "",
        "> _This document is a starter. Add your Claude API key in Settings to "
        "generate it automatically next time._",
        "",
    ]
    if prompt:
        lines.extend(["## Instructions", prompt, ""])
    lines.append(f"## Context: {project.name}")
    if project.tagline:
        lines.append(project.tagline)
    if project.problem:
        lines.append("")
        lines.append("**Problem:** " + project.problem)
    if project.solution:
        lines.append("")
        lines.append("**Solution:** " + project.solution)
    return "\n".join(lines).strip() + "\n"
