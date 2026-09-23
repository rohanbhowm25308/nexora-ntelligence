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
import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


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
    resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
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
