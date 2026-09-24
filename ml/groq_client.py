"""
Groq LLM integration — used to turn structured KPI/analytics JSON into
natural-language executive insights and recommendations (feature #6, #23).

Requires GROQ_API_KEY in a .env file at the project root (see .env.example).
If no key is configured, callers should fall back to the rule-based
insights already produced by ml/insights.py — the app never hard-fails
because Groq is unavailable.
"""

import os
import json
import logging
import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# llama-3.3-70b-versatile was decommissioned by Groq on 2026-08-16 -- every
# request against it now fails with a 4xx, which is why the copilot/report
# silently fell back to the rule-based path even with a valid API key.
# openai/gpt-oss-120b is Groq's recommended replacement (see
# https://console.groq.com/docs/deprecations). Still overridable via env.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

logger = logging.getLogger("nexora.groq")


class GroqUnavailable(Exception):
    pass


def _api_key():
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise GroqUnavailable("GROQ_API_KEY is not set. Add it to your .env file.")
    return key


def ask_groq(system_prompt: str, user_prompt: str, max_tokens: int = 700, temperature: float = 0.4) -> str:
    key = _api_key()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        # (connect_timeout, read_timeout). Trimmed further than before --
        # if the host is reachable at all, gpt-oss-120b on Groq typically
        # responds in 1-3s for a short answer; capping the read timeout at
        # 10s means a slow/stuck request still fails fast into the
        # rule-based fallback instead of the chat feeling stuck.
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=(3, 10))
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        # Log the real reason server-side (terminal) so it's diagnosable --
        # e.g. connection blocked, 401 invalid key, 400 bad model, 429 rate
        # limit -- rather than only ever surfacing a generic "unavailable"
        # to the browser.
        body = getattr(getattr(e, "response", None), "text", "")
        logger.warning("Groq request failed (model=%s): %s%s", GROQ_MODEL, e, f" | response: {body[:300]}" if body else "")
        raise
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def generate_business_insights(kpis: dict, regions: list, top_products: list, anomalies: list) -> str:
    """Natural-language paragraph(s) summarizing performance, in the style
    requested by the brief: 'Revenue increased X%, driven by...'"""
    system_prompt = (
        "You are a senior business intelligence analyst writing a short, sharp "
        "executive insight summary for company management. Use plain business "
        "language, cite concrete numbers from the data provided, and organize "
        "your answer into short bullet points grouped by theme (Sales, Products, "
        "Customers, Regions). Do not invent numbers that are not in the data. "
        "Keep the whole answer under 220 words."
    )
    user_prompt = (
        f"KPIs: {json.dumps(kpis)}\n\n"
        f"Regional performance: {json.dumps(regions[:5])}\n\n"
        f"Top products: {json.dumps(top_products[:5])}\n\n"
        f"Recent anomalies: {json.dumps(anomalies[:5])}\n\n"
        "Write the executive insight summary now."
    )
    return ask_groq(system_prompt, user_prompt)


def generate_executive_report_narrative(context: dict) -> str:
    system_prompt = (
        "You are writing the narrative sections of a one-click executive report "
        "for a Business Intelligence platform. Given structured analytics JSON, "
        "produce a concise Executive Summary (3-5 sentences) followed by a short "
        "'Key Recommendations' bullet list (max 5 bullets). Business tone, no "
        "fluff, only reference numbers present in the JSON."
    )
    user_prompt = json.dumps(context, default=str)[:12000]
    return ask_groq(system_prompt, user_prompt, max_tokens=900)