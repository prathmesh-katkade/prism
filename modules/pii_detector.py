"""
PII Detector / Indian PII Vault — regex-scans text/categorical columns for
emails, phone numbers, likely person names, and India-specific identifiers
(Aadhaar, PAN, GSTIN, IFSC, Indian mobile numbers), and offers one-click
pattern-preserving masking per flagged column (e.g. "j***@gmail.com",
"XXXX-XXXX-1234" for Aadhaar). Runs automatically whenever a new dataset
becomes active (upload, sample dataset, restored session, or join result).

Strict mode (build_safe_sample / is_strict_mode-aware callers): when on,
any sample rows built for an LLM prompt have flagged PII columns redacted
first — the model still sees those columns exist (schema), just never
their actual values.
"""

from __future__ import annotations

import re

import pandas as pd

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}$")

# Loose enough to catch common phone formats; the digit-count check in
# _looks_like_phone() below is what actually keeps false positives down.
_PHONE_RE = re.compile(r"^\+?\d{0,3}[\s.\-]?\(?\d{2,4}\)?[\s.\-]?\d{3,4}[\s.\-]?\d{0,4}$")

# Two or three Title-Case words, letters only — a deliberately simple
# heuristic for "looks like a full person's name", not a rigorous NER model.
_NAME_RE = re.compile(r"^[A-Z][a-z]+(?:\s[A-Z][a-z]+){1,2}$")

# Column-name hints checked before applying the name pattern, so generic
# Title-Case categorical values (e.g. "New York", "Team Lead") aren't flagged
# just because they happen to match the shape of a name.
_NAME_HINT_KEYWORDS = ["name", "employee", "customer", "client", "contact", "person"]

# --- India-specific identifiers -------------------------------------------
# Aadhaar: 12 digits, optionally space-grouped in 4s (e.g. "1234 5678 9012").
_AADHAAR_RE = re.compile(r"^\d{4}\s?\d{4}\s?\d{4}$")
# PAN: 5 letters, 4 digits, 1 letter (e.g. "ABCDE1234F").
_PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
# GSTIN: 2-digit state code + 10-char embedded PAN + entity code + 'Z' + checksum.
_GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z]\d[A-Z]$|^\d{2}[A-Z]{5}\d{4}[A-Z]\dZ[A-Z0-9]$")
# IFSC: 4-letter bank code, literal '0', 6 alphanumeric branch code.
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
# Indian mobile: optional +91/91/0 prefix, then a 10-digit number starting 6-9.
_INDIAN_MOBILE_RE = re.compile(r"^(?:\+?91[\-\s]?|0)?[6-9]\d{9}$")

# A column is flagged once at least this share of its non-null values match.
MATCH_THRESHOLD_PCT = 30.0


def _looks_like_phone(value: str) -> bool:
    value = value.strip()
    if not _PHONE_RE.match(value):
        return False
    digit_count = sum(c.isdigit() for c in value)
    return 7 <= digit_count <= 15


def _looks_like_name_column(col: str) -> bool:
    lowered = col.lower()
    return any(hint in lowered for hint in _NAME_HINT_KEYWORDS)


def _mask_email(value: str) -> str:
    if "@" not in value:
        return value
    local, _, domain = value.partition("@")
    masked_local = (local[0] + "***") if local else "***"
    return f"{masked_local}@{domain}"


def _mask_phone(value: str) -> str:
    total_digits = sum(c.isdigit() for c in value)
    keep_last = min(2, total_digits)
    digits_seen = 0
    out_chars = []
    for c in value:
        if c.isdigit():
            digits_seen += 1
            out_chars.append(c if digits_seen > total_digits - keep_last else "*")
        else:
            out_chars.append(c)
    return "".join(out_chars)


def _mask_name(value: str) -> str:
    parts = value.split()
    masked_parts = [p[0] + "*" * (len(p) - 1) if len(p) > 1 else p for p in parts]
    return " ".join(masked_parts)


def _mask_aadhaar(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 12:
        return "XXXX-XXXX-XXXX"
    return f"XXXX-XXXX-{digits[-4:]}"


def _mask_pan(value: str) -> str:
    """Pattern-preserving: keep the 3rd-letter entity class + digits (the
    genuinely useful-for-analysis part), mask the two identity-bearing
    letters and the checksum letter — e.g. "ABCDE1234F" -> "ABCXX1234X".
    """
    v = value.strip().upper()
    if len(v) != 10:
        return "XXXXX0000X"
    return f"{v[:3]}XX{v[5:9]}X"


def _mask_gstin(value: str) -> str:
    v = value.strip().upper()
    if len(v) != 15:
        return "XX" + "X" * 13
    return f"{v[:2]}{v[2:5]}XXXXXX{v[11:]}"


def _mask_ifsc(value: str) -> str:
    v = value.strip().upper()
    if len(v) != 11:
        return "XXXX0XXXXXX"
    return f"{v[:4]}0XX{v[7:]}"


def _mask_mobile(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) < 10:
        return "X" * len(value)
    last4 = digits[-4:]
    prefix = "+91-" if value.strip().startswith("+91") else ""
    return f"{prefix}XXXXXX{last4}"


_MASK_FUNCS = {
    "email": _mask_email, "phone": _mask_phone, "name": _mask_name,
    "aadhaar": _mask_aadhaar, "pan": _mask_pan, "gstin": _mask_gstin,
    "ifsc": _mask_ifsc, "mobile": _mask_mobile,
}

# Display label for every PII type, in the order the Overview banner and
# masking expander should check/list them — most India-specific and
# highest-stakes first.
PII_TYPE_LABELS = {
    "aadhaar": "Aadhaar numbers", "pan": "PAN numbers", "gstin": "GSTIN numbers",
    "ifsc": "IFSC codes", "mobile": "Indian mobile numbers",
    "email": "Emails", "phone": "Phone numbers", "name": "Likely names",
}
ALL_PII_TYPES = list(PII_TYPE_LABELS.keys())


def scan_dataframe(df: pd.DataFrame, column_types: dict[str, str]) -> dict:
    """Regex-scan text/categorical columns for emails, phone numbers, likely
    person names, and India-specific identifiers (Aadhaar/PAN/GSTIN/IFSC/
    Indian mobile). Returns {pii_type: [...]} for every type in
    ALL_PII_TYPES — each a list of {"column", "match_pct", "sample"} dicts,
    "sample" already masked so the banner itself never displays raw PII.
    India-specific patterns are checked before the generic ones so an
    Indian mobile column is labeled "mobile", not just generic "phone".
    """
    findings: dict[str, list[dict]] = {t: [] for t in ALL_PII_TYPES}

    for col, ctype in column_types.items():
        if ctype not in ("text", "categorical"):
            continue
        non_null = df[col].dropna().astype(str)
        if non_null.empty:
            continue

        def _pct(pattern_fn, values=non_null) -> float:
            return 100 * values.apply(lambda v: bool(pattern_fn(v.strip()))).mean()

        aadhaar_pct = _pct(_AADHAAR_RE.match)
        if aadhaar_pct >= MATCH_THRESHOLD_PCT:
            findings["aadhaar"].append(
                {"column": col, "match_pct": round(aadhaar_pct, 1), "sample": _mask_aadhaar(non_null.iloc[0])}
            )
            continue  # treat a column as one PII type at most

        pan_pct = _pct(lambda v: _PAN_RE.match(v.upper()))
        if pan_pct >= MATCH_THRESHOLD_PCT:
            findings["pan"].append(
                {"column": col, "match_pct": round(pan_pct, 1), "sample": _mask_pan(non_null.iloc[0])}
            )
            continue

        gstin_pct = _pct(lambda v: _GSTIN_RE.match(v.upper()))
        if gstin_pct >= MATCH_THRESHOLD_PCT:
            findings["gstin"].append(
                {"column": col, "match_pct": round(gstin_pct, 1), "sample": _mask_gstin(non_null.iloc[0])}
            )
            continue

        ifsc_pct = _pct(lambda v: _IFSC_RE.match(v.upper()))
        if ifsc_pct >= MATCH_THRESHOLD_PCT:
            findings["ifsc"].append(
                {"column": col, "match_pct": round(ifsc_pct, 1), "sample": _mask_ifsc(non_null.iloc[0])}
            )
            continue

        mobile_pct = _pct(lambda v: _INDIAN_MOBILE_RE.match(v.replace(" ", "")))
        if mobile_pct >= MATCH_THRESHOLD_PCT:
            findings["mobile"].append(
                {"column": col, "match_pct": round(mobile_pct, 1), "sample": _mask_mobile(non_null.iloc[0])}
            )
            continue

        email_pct = _pct(_EMAIL_RE.match)
        if email_pct >= MATCH_THRESHOLD_PCT:
            findings["email"].append(
                {"column": col, "match_pct": round(email_pct, 1), "sample": _mask_email(non_null.iloc[0])}
            )
            continue

        phone_pct = 100 * non_null.apply(_looks_like_phone).mean()
        if phone_pct >= MATCH_THRESHOLD_PCT:
            findings["phone"].append(
                {"column": col, "match_pct": round(phone_pct, 1), "sample": _mask_phone(non_null.iloc[0])}
            )
            continue

        if _looks_like_name_column(col):
            name_pct = _pct(_NAME_RE.match)
            if name_pct >= MATCH_THRESHOLD_PCT:
                findings["name"].append(
                    {"column": col, "match_pct": round(name_pct, 1), "sample": _mask_name(non_null.iloc[0])}
                )

    return findings


def has_findings(findings: dict) -> bool:
    return any(findings.get(t) for t in ALL_PII_TYPES)


def describe_findings(findings: dict) -> str:
    parts = [f"{len(findings[t])} {PII_TYPE_LABELS[t].lower()}" for t in ALL_PII_TYPES if findings.get(t)]
    return f"Detected {', '.join(parts)}." if parts else "No PII detected."


def flagged_columns(findings: dict) -> list[str]:
    """Every column name flagged under any PII type — used to redact a
    sample before it's sent to an LLM in strict mode.
    """
    return [entry["column"] for t in ALL_PII_TYPES for entry in findings.get(t, [])]


def build_safe_sample(df: pd.DataFrame, findings: dict, n: int = 5) -> pd.DataFrame:
    """A copy of df.head(n) with every PII-flagged column's values replaced
    by a placeholder — used for LLM prompts in strict mode so the model
    still sees the column exists (schema) but never an actual value.
    """
    sample = df.head(n).copy()
    for col in flagged_columns(findings):
        if col in sample.columns:
            sample[col] = "[REDACTED]"
    return sample


def mask_column(df: pd.DataFrame, column: str, pii_type: str) -> pd.DataFrame:
    """Return a copy of df with `column` masked in place, per pii_type (any
    key in ALL_PII_TYPES). Null values pass through unchanged.
    """
    mask_func = _MASK_FUNCS.get(pii_type)
    if mask_func is None:
        return df
    new_df = df.copy()
    new_df[column] = new_df[column].apply(lambda v: mask_func(str(v)) if pd.notna(v) else v)
    return new_df
