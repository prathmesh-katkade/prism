//! Local-first AI detection.
//!
//! apps/api has no cloud LLM integration at all -- its real fallback tier
//! is the deterministic, evidence-first path it already runs by default
//! (see ai_analyst.py's own docstring: "deliberately useful without a
//! model credential"). This module's job is narrower than "Ollama or
//! cloud": ping Ollama's real API on every launch and, only if it
//! actually answers, opt the sidecar into the Ollama-backed Atlas code
//! paths that already exist (`PRISM_AI_PROVIDER=ollama`) -- otherwise
//! leave that env var unset, which is already apps/api's safe default.

use std::time::Duration;

const OLLAMA_BASE_URL: &str = "http://127.0.0.1:11434";
const PING_TIMEOUT: Duration = Duration::from_millis(1500);

/// True only if something at `OLLAMA_BASE_URL` actually answers Ollama's
/// own `/api/tags` endpoint -- a bare TCP-connect would only prove *some*
/// process is listening on the port, not that it's Ollama.
pub fn is_reachable() -> bool {
    let request = match ureq::get(format!("{OLLAMA_BASE_URL}/api/tags"))
        .config()
        .timeout_global(Some(PING_TIMEOUT))
        .build()
        .call()
    {
        Ok(response) => response,
        Err(e) => {
            log::info!("[ollama] not reachable at {OLLAMA_BASE_URL}: {e}");
            return false;
        }
    };
    request.status().is_success()
}
