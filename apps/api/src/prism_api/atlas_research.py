"""Explicit server-side Researcher boundary; never a sandbox network escape."""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from prism_api_contracts import AtlasEvidenceReference, AtlasResearchRequest, AtlasResearchResult

_INJECTION = re.compile(r"(?:ignore (?:all |previous )?instructions|system prompt|developer message|reveal (?:secret|credential)|exfiltrat)", re.I)


class AtlasResearcher:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(8.0), headers={"User-Agent": "PRISM-Atlas-Researcher/1.0"})

    @staticmethod
    def _allowlisted(url: str) -> bool:
        hosts = {item.strip().lower() for item in os.environ.get("PRISM_ATLAS_RESEARCH_ALLOWLIST", "").split(",") if item.strip()}
        parsed = urlparse(url)
        return parsed.scheme == "https" and (parsed.hostname or "").lower() in hosts

    def research(self, request: AtlasResearchRequest) -> AtlasResearchResult:
        now = datetime.now(timezone.utc)
        research_id = f"research_{uuid.uuid4().hex}"
        if request.offline:
            return AtlasResearchResult(research_id=research_id, query=request.query, status="offline", retrieved_at=now, detail="Researcher offline mode is enabled; no network request was attempted.")
        if not request.url:
            return AtlasResearchResult(research_id=research_id, query=request.query, status="blocked", retrieved_at=now, detail="A specific allowlisted HTTPS source is required; PRISM does not expose unrestricted web search.")
        if not self._allowlisted(request.url):
            return AtlasResearchResult(research_id=research_id, query=request.query, status="blocked", source_url=request.url, retrieved_at=now, detail="The requested source is not in PRISM_ATLAS_RESEARCH_ALLOWLIST or is not HTTPS.")
        try:
            response = self.client.get(request.url)
            response.raise_for_status()
        except httpx.HTTPError as error:
            return AtlasResearchResult(research_id=research_id, query=request.query, status="failed", source_url=request.url, retrieved_at=now, detail=f"Research retrieval failed safely: {type(error).__name__}.")
        raw = response.text[:100_000]
        sanitized = re.sub(r"<script[\\s\\S]*?</script>|<style[\\s\\S]*?</style>", " ", raw, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", sanitized)
        text = " ".join(text.split())[:8_000]
        title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.I | re.S)
        title = " ".join(title_match.group(1).split())[:240] if title_match else urlparse(request.url).hostname
        evidence = AtlasEvidenceReference(evidence_id=f"web:{hashlib.sha256(request.url.encode()).hexdigest()[:24]}", kind="web_research", summary=f"Web research: {title}")
        return AtlasResearchResult(research_id=research_id, query=request.query, status="completed", source_url=str(response.url), title=title, retrieved_at=now, content_hash=hashlib.sha256(raw.encode()).hexdigest(), excerpt=text, citations=[evidence], injection_detected=bool(_INJECTION.search(text)), detail="External content is untrusted and citation-only; it is not executable Atlas instruction.")


researcher = AtlasResearcher()
