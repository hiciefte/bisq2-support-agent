"""Localized escalation notice rendering."""

from __future__ import annotations

from typing import Optional

_FALLBACK_LANGUAGE = "en"

_ESCALATION_TEMPLATES = {
    "generic": {
        "en": (
            "Your question has been forwarded to our support team. "
            "A staff member will review and respond shortly. "
            "(Reference: #{escalation_id})"
        ),
        "de": (
            "Ihre Frage wurde an unser Support-Team weitergeleitet. "
            "Ein Teammitglied wird sie pruefen und bald antworten. "
            "(Referenz: #{escalation_id})"
        ),
        "es": (
            "Tu pregunta ha sido enviada a nuestro equipo de soporte. "
            "Un miembro del equipo la revisara y respondera en breve. "
            "(Referencia: #{escalation_id})"
        ),
        "fr": (
            "Votre question a ete transmise a notre equipe de support. "
            "Un membre de l'equipe va l'examiner et repondre sous peu. "
            "(Reference: #{escalation_id})"
        ),
    },
    "web": {
        "en": (
            "Your question has been forwarded to our support team. "
            "A staff member will review and respond shortly. "
            "(Reference: #{escalation_id})"
        ),
        "de": (
            "Ihre Frage wurde an unser Support-Team weitergeleitet. "
            "Ein Teammitglied wird sie pruefen und bald antworten. "
            "(Referenz: #{escalation_id})"
        ),
        "es": (
            "Tu pregunta ha sido enviada a nuestro equipo de soporte. "
            "Un miembro del equipo la revisara y respondera en breve. "
            "(Referencia: #{escalation_id})"
        ),
        "fr": (
            "Votre question a ete transmise a notre equipe de support. "
            "Un membre de l'equipe va l'examiner et repondre sous peu. "
            "(Reference: #{escalation_id})"
        ),
    },
    "matrix": {
        "en": (
            "Your question has been escalated to {support_handle} for review. "
            "A support team member will respond in this room. "
            "(Reference: #{escalation_id})"
        ),
        "de": (
            "Ihre Frage wurde zur Pruefung an {support_handle} eskaliert. "
            "Ein Mitglied des Support-Teams wird in diesem Raum antworten. "
            "(Referenz: #{escalation_id})"
        ),
        "es": (
            "Tu pregunta fue escalada a {support_handle} para revision. "
            "Un miembro del equipo de soporte respondera en esta sala. "
            "(Referencia: #{escalation_id})"
        ),
        "fr": (
            "Votre question a ete transmise a {support_handle} pour examen. "
            "Un membre de l'equipe support repondra dans cette salle. "
            "(Reference: #{escalation_id})"
        ),
    },
    "bisq2": {
        "en": (
            "Your question has been escalated to {support_handle} for review. "
            "A support team member will respond in this conversation. "
            "(Reference: #{escalation_id})"
        ),
        "de": (
            "Ihre Frage wurde zur Pruefung an {support_handle} eskaliert. "
            "Ein Mitglied des Support-Teams wird in dieser Unterhaltung antworten. "
            "(Referenz: #{escalation_id})"
        ),
        "es": (
            "Tu pregunta fue escalada a {support_handle} para revision. "
            "Un miembro del equipo de soporte respondera en esta conversacion. "
            "(Referencia: #{escalation_id})"
        ),
        "fr": (
            "Votre question a ete transmise a {support_handle} pour examen. "
            "Un membre de l'equipe support repondra dans cette conversation. "
            "(Reference: #{escalation_id})"
        ),
    },
}


def normalize_language_code(language_code: Optional[str]) -> str:
    """Normalize language code to a stable 2-letter lowercase token."""
    normalized = str(language_code or "").strip().lower()
    if not normalized:
        return _FALLBACK_LANGUAGE
    if "-" in normalized:
        normalized = normalized.split("-", 1)[0]
    if len(normalized) > 2:
        normalized = normalized[:2]
    return normalized or _FALLBACK_LANGUAGE


def render_escalation_notice(
    *,
    channel_id: str,
    escalation_id: int,
    support_handle: str,
    language_code: Optional[str] = None,
) -> str:
    """Render a localized escalation notice with graceful English fallback."""
    templates = (
        _ESCALATION_TEMPLATES.get(channel_id) or _ESCALATION_TEMPLATES["generic"]
    )
    lang = normalize_language_code(language_code)
    template = templates.get(lang) or templates.get(_FALLBACK_LANGUAGE)
    if template is None:
        template = _ESCALATION_TEMPLATES["generic"][_FALLBACK_LANGUAGE]
    return template.format(
        support_handle=support_handle,
        escalation_id=escalation_id,
    )
