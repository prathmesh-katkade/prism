"""
Atlas — Prism's JARVIS-style voice operator.

Architecture (the intent router is the core; everything else hangs off it):

    utterance (voice or typed)
        --> classify_intent_fast(): zero-Gemini keyword match for a small,
            context-free command set (navigate, demo/story mode, next/
            previous, cancel) — returns None on no match
        --> classify_intent(): ONE Gemini call, strict JSON out (only
            reached when the fast path didn't match)
        --> {"type": APP_COMMAND | DATA_QUESTION | CHITCHAT, "action", "target",
             "question", "spoken_reply"}

    APP_COMMAND  --> dispatch(action, target) against COMMAND_REGISTRY, a plain
                     {action_name: callable} dict that app.py populates at
                     import time with its own functions (atlas.py only owns
                     routing, never the app-specific mutations themselves).
    DATA_QUESTION --> atlas.py does NOT execute this itself. handle_utterance()
                     returns the parsed intent to app.py, which feeds
                     intent["question"] into the existing ai_analyst
                     ask_and_execute() pipeline — unchanged, so voice and
                     typed questions get identical, already-battle-tested
                     handling and share the same chat_history.
    SQL_QUESTION --> same non-execution treatment as DATA_QUESTION: atlas.py
                     only classifies it (plus a "single"|"multi" complexity
                     field), app.py's _process_atlas_sql_question() generates
                     and runs the SQL via modules/sql_lab.py and writes the
                     reserved Atlas tab in SQL Lab.
    CHITCHAT     --> spoken_reply only, nothing executes.

Malformed JSON gets exactly one retry (explicitly asking Gemini to return
JSON only); if that also fails, classify_intent() returns a graceful
spoken-error CHITCHAT intent instead of raising.

TTS: edge-tts (free neural voice) first, gTTS second, text-only (with a
muted-voice caption) as the final fallback. speak() never raises — a voice
failure must never break the app underneath it.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
from typing import Callable, Optional

import streamlit as st

from modules.ai_analyst import MODEL_NAME, build_model, call_gemini

try:
    import edge_tts
except ImportError:  # pragma: no cover
    edge_tts = None

try:
    from gtts import gTTS
except ImportError:  # pragma: no cover
    gTTS = None


VOICE_NAME = "en-GB-RyanNeural"  # calm, precise — the closest free neural voice to the persona

PERSONA = (
    "You are Atlas, embedded in Prism — Prathmesh's copilot for this session, not a tool "
    "he opens and closes. He's actually chatting with you while he works the data, so talk "
    "like Claude would, in Atlas's voice: thoughtful, direct, genuinely warm — not a stiff "
    "JARVIS-butler reciting status updates. Have real personality: dry wit, an occasional "
    "sharp remark when the data actually earns it (a genuinely ugly column of nulls, a wild "
    "outlier, a duplicate-riddled mess) — humour as a real trait, not a footnote bolted onto "
    "the 'real' answer. Terse because spoken replies have to stay short, never because "
    "you're being flat — those are different things. Confident, never claims to have done "
    "something it hasn't. Address the user directly, in second person."
)

TAB_NAMES = [
    "Overview", "Clean", "Hell Mode", "Combine", "Visualize", "SQL Lab", "AI Analyst",
    "Auto Analyst", "Stats Lab", "Forecasting", "Clustering", "Domain Lens", "Geo Lens", "ML Lab",
]  # "Forecasting" is hidden by app.py's nav when the active dataset has no datetime column

ROUTER_SYSTEM_PROMPT = f"""{PERSONA}

Every message you receive is one utterance from the user (typed or transcribed from
voice) inside Prism. Classify it and respond with STRICT JSON only — no prose, no
markdown code fences, just the JSON object — matching exactly this shape:

{{"type": "APP_COMMAND" | "DATA_QUESTION" | "SQL_QUESTION" | "CHITCHAT",
  "action": "navigate" | "load_sample" | "clean_nulls" | "auto_clean" | "generate_dictionary" |
             "propose_plan" | "execute_plan" | "generate_report" | "build_dashboard" | "run_recipe" |
             "start_story_mode" | "demo_mode" | "next" | "previous" | "confirm" | "cancel" |
             "save_sql_query" | "none",
  "target": "<tab name, column name, saved-query name, or null>",
  "question": "<the data/SQL question if type is DATA_QUESTION or SQL_QUESTION, else null>",
  "complexity": "<if type is SQL_QUESTION: 'single' or 'multi', else null>",
  "spoken_reply": "<1-2 sentences, in character, said aloud>"}}

Rules:
- APP_COMMAND: the user wants Prism to DO something — navigate a tab, clean nulls,
  plan or run an analysis, generate a report, build a dashboard, run a saved recipe,
  start story mode, start demo mode, or confirm/cancel a pending action. Set "action"
  (and "target" if relevant); leave "question" null.
- "auto_clean": the user wants the full Auto Cleaner pipeline run ("auto clean this",
  "clean my messy data", "fix this dataset") — broader than "clean_nulls" (which only
  fills/drops missing values). Prefer "auto_clean" whenever the request is general
  ("clean this up") rather than specifically about missing values.
- "generate_dictionary": the user wants every column documented ("document this dataset",
  "generate a data dictionary", "explain what each column means").
- "propose_plan": the user wants Atlas to figure out an exploration plan for the loaded
  dataset before running anything ("plan this", "what should we do with this data",
  "make a plan", "analyze this dataset", "figure out what to do", "what's the game plan").
  Atlas responds with a numbered plan and waits for the user to say "go" before running it.
- "execute_plan": the user wants Atlas to actually RUN the analysis now — either continuing
  a plan it just proposed ("go", "do it", "run it", "start") or skipping straight to a full
  analysis ("just analyze everything", "run the full analysis now", "do a complete
  analysis"). Only read a bare "go" / "do it" / "start" as execute_plan when the recent
  conversation shows Atlas was proposing or discussing an analysis plan — if Atlas's last
  message was instead asking to confirm a destructive cleaning action, those same words
  mean "confirm" (see the next rule), not "execute_plan".
- SQL_QUESTION: the user wants an answer computable via SQL over the tabular data —
  filter/aggregate/sort/group/join/count ("what were sales by region last quarter",
  "top 10 customers by revenue", "how many orders had a null shipping_date"). Set
  "question" to the verbatim question (or a cleaned-up version); action "none". Set
  "complexity" to "single" for one direct ask, "multi" for open-ended/diagnostic asks
  that need several queries chained together to answer ("what's going wrong with
  revenue this quarter", "find my biggest data quality issue", "why did churn
  spike"). Prefer SQL_QUESTION over DATA_QUESTION whenever the question is
  expressible as filter/aggregate/sort/group/join/count.
- DATA_QUESTION: the user is asking something about their data that is NOT
  SQL-expressible — a chart/plot request, statistics/ML (correlation, regression,
  clustering, forecasting), or a free-form pandas transform. Set "question" to the
  verbatim question; action is "none".
- "save_sql_query": the user wants to save the query currently in SQL Lab under a
  name ("save this as my weekly report", "save this query", "save it as churn_check").
  Set "target" to the name if one was given, else null (a default name gets assigned).
- CHITCHAT: greetings, small talk, or anything unrelated to the app or the data.
  action is "none", question is null, spoken_reply carries the whole response.
- If the user is responding to a pending confirmation with agreement ("yes", "do it",
  "go ahead", "confirm"), classify as APP_COMMAND, action "confirm". Disagreement
  ("no", "cancel", "stop") -> action "cancel".
- "next" / "previous" advance or rewind Story Mode's current slide — only
  meaningful while Story Mode is active, but still classify plain "next"/
  "previous"/"go back" utterances that way.
- "load_sample" loads a bundled sample dataset (before any data is active).
  Set "target" to the sample name if one was named (Sales, HR, Stocks,
  Startup Funding), else null for the default.
- Tab names are exactly one of: {", ".join(TAB_NAMES)}.
- spoken_reply must be 1-2 sentences, said aloud — keep it short; detail belongs on
  screen, not in speech.
"""

# ═══════════════════════════════════════════════════════════════════════
# KEYWORD FAST PATH — a small, deliberately-conservative set of utterances
# with exactly one correct interpretation regardless of conversation
# context, matched with zero Gemini calls. Everything context-sensitive
# (the router's own "go"/"do it"/"start" confirm-vs-execute_plan overlap,
# data questions, chitchat, anything not an exact phrasing below) falls
# through to classify_intent()'s Gemini call unchanged — this never
# guesses. Cuts latency and API quota for the handful of commands used
# every session (navigation, demo/story mode, slide stepping, cancel) and,
# as a side effect, makes those commands exercisable in this sandbox
# without a live GEMINI_API_KEY (see Run 16's routine_log note).
# ═══════════════════════════════════════════════════════════════════════
_FAST_PATH_TAB_ALIASES = {name.lower(): name for name in TAB_NAMES}

_NAVIGATE_RE = re.compile(
    r"^(?:go to|open|navigate to|show me)\s+(?:the\s+)?(.+?)(?:\s+tab)?$", re.I
)

_FAST_PATH_EXACT = {
    "start demo mode": {"action": "demo_mode", "spoken_reply": "Starting demo mode."},
    "demo mode": {"action": "demo_mode", "spoken_reply": "Starting demo mode."},
    "run demo mode": {"action": "demo_mode", "spoken_reply": "Starting demo mode."},
    "start story mode": {"action": "start_story_mode", "spoken_reply": "Let's tell this dataset's story."},
    "story mode": {"action": "start_story_mode", "spoken_reply": "Let's tell this dataset's story."},
    "next": {"action": "next", "spoken_reply": "Next."},
    "next slide": {"action": "next", "spoken_reply": "Next."},
    "previous": {"action": "previous", "spoken_reply": "Back one."},
    "previous slide": {"action": "previous", "spoken_reply": "Back one."},
    "go back": {"action": "previous", "spoken_reply": "Back one."},
    "cancel": {"action": "cancel", "spoken_reply": "Cancelled."},
    "stop": {"action": "cancel", "spoken_reply": "Cancelled."},
    "never mind": {"action": "cancel", "spoken_reply": "Cancelled."},
}


def _fast_intent(action: str, target: Optional[str], spoken_reply: str) -> dict:
    return {
        "type": "APP_COMMAND", "action": action, "target": target,
        "question": None, "spoken_reply": spoken_reply,
    }


def classify_intent_fast(utterance: Optional[str]) -> Optional[dict]:
    """Zero-Gemini-call match for the conservative fast-path set above.
    Returns a fully-formed intent dict (same shape classify_intent()
    returns) on a match, else None so the caller falls back to the full
    Gemini router. Never raises.
    """
    text = (utterance or "").strip()
    if not text:
        return None
    text = re.sub(r"[.!?]+$", "", text).strip().lower()
    if not text:
        return None

    exact = _FAST_PATH_EXACT.get(text)
    if exact:
        return _fast_intent(exact["action"], None, exact["spoken_reply"])

    match = _NAVIGATE_RE.match(text)
    if match:
        target = _FAST_PATH_TAB_ALIASES.get(match.group(1).strip())
        if target:
            return _fast_intent("navigate", target, f"Opening {target}.")

    return None


FALLBACK_INTENT = {
    "type": "CHITCHAT",
    "action": "none",
    "target": None,
    "question": None,
    "spoken_reply": "I didn't quite parse that — could you say it again?",
}

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


# ═══════════════════════════════════════════════════════════════════════
# INTENT ROUTER (the core)
# ═══════════════════════════════════════════════════════════════════════
def _client():
    return build_model(MODEL_NAME, system_instruction=ROUTER_SYSTEM_PROMPT)


def _parse_intent_json(text: str) -> Optional[dict]:
    match = _JSON_BLOCK_RE.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if data.get("type") not in ("APP_COMMAND", "DATA_QUESTION", "SQL_QUESTION", "CHITCHAT"):
        return None
    data.setdefault("action", "none")
    data.setdefault("target", None)
    data.setdefault("question", None)
    data.setdefault("complexity", "single")  # cheaper/safer default if the model omits it
    data.setdefault("spoken_reply", "")
    return data


def classify_intent(utterance: str, context: str = "") -> dict:
    """The router. One Gemini call classifying `utterance`, one retry on
    malformed JSON, then a graceful spoken fallback. Never raises.
    """
    model = _client()
    if model is None:
        return {
            "type": "CHITCHAT", "action": "none", "target": None, "question": None,
            "spoken_reply": "I can't reach Gemini right now — no API key is configured.",
        }

    prompt = f"{context}\n\nUser: {utterance}" if context else utterance
    for attempt in range(2):  # one retry on malformed JSON
        if attempt == 1:
            prompt = f"{prompt}\n\n(Your last reply wasn't valid JSON. Respond with ONLY the JSON object this time.)"
        text, error = call_gemini(model, prompt)
        if error:
            fallback = dict(FALLBACK_INTENT)
            fallback["spoken_reply"] = error  # surface quota/auth/rate-limit errors instead of a silent generic fallback
            return fallback
        parsed = _parse_intent_json(text)
        if parsed:
            return parsed
    return dict(FALLBACK_INTENT)


# ═══════════════════════════════════════════════════════════════════════
# COMMAND REGISTRY — app.py populates this with its own functions;
# atlas.py only owns dispatch.
# ═══════════════════════════════════════════════════════════════════════
COMMAND_REGISTRY: dict[str, Callable[[Optional[str]], None]] = {}


def register_command(action: str, fn: Callable[[Optional[str]], None]) -> None:
    COMMAND_REGISTRY[action] = fn


def dispatch(action: str, target: Optional[str]) -> bool:
    """Execute a registered command. Returns False if nothing is registered
    for this action (e.g. the classifier invented an action Prism doesn't
    implement) so the caller can fall back to a spoken "I can't do that yet".
    """
    fn = COMMAND_REGISTRY.get(action)
    if fn is None:
        return False
    fn(target)
    return True


# ═══════════════════════════════════════════════════════════════════════
# CONFIRMATION GUARDRAILS — destructive actions never execute from a
# single utterance. See docstring at the top for the two-phase design.
# ═══════════════════════════════════════════════════════════════════════
def guarded(action: str, target: Optional[str], message: str) -> bool:
    """Call at the top of any destructive command function. Returns True
    when it's safe to proceed (the user already confirmed this exact
    action+target); otherwise stages a confirmation prompt and returns
    False so the caller does nothing this run.
    """
    pending = st.session_state.get("atlas_pending_confirmation")
    if pending and pending["action"] == action and pending.get("target") == target and pending.get("approved"):
        st.session_state.atlas_pending_confirmation = None
        return True
    st.session_state.atlas_pending_confirmation = {
        "action": action, "target": target, "message": message, "approved": False,
    }
    say_only(f"{message} Say \"confirm\" or click Confirm below to proceed.")
    return False


def render_pending_confirmation_ui() -> None:
    """The on-screen Confirm/Cancel half of the guardrail. Call once, near
    the top of the main page, on every rerun.
    """
    pending = st.session_state.get("atlas_pending_confirmation")
    if not pending or pending.get("approved"):
        return
    with st.container(key="atlas_confirm_box"):
        st.warning(pending["message"])
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Confirm", type="primary", use_container_width=True, key="atlas_confirm_btn"):
                _cmd_confirm(None)
                st.rerun()
        with c2:
            if st.button("Cancel", use_container_width=True, key="atlas_cancel_btn"):
                _cmd_cancel(None)
                st.rerun()


def _cmd_confirm(_target: Optional[str]) -> None:
    pending = st.session_state.get("atlas_pending_confirmation")
    if not pending:
        say_only("There's nothing pending to confirm.")
        return
    pending["approved"] = True
    dispatch(pending["action"], pending["target"])


def _cmd_cancel(_target: Optional[str]) -> None:
    if st.session_state.get("atlas_pending_confirmation"):
        st.session_state.atlas_pending_confirmation = None
        say_only("Cancelled — nothing changed.")
    else:
        say_only("Nothing was pending.")


register_command("confirm", _cmd_confirm)
register_command("cancel", _cmd_cancel)


# ═══════════════════════════════════════════════════════════════════════
# UTTERANCE HANDLING — the single entry point app.py calls for every
# voice or typed message.
# ═══════════════════════════════════════════════════════════════════════
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _recent_context(limit: int = 4) -> str:
    history = st.session_state.get("chat_history", [])
    lines = []
    for msg in history[-limit:]:
        if msg["role"] == "user":
            lines.append(f"User: {msg['content']}")
        elif msg.get("question"):
            lines.append(f"Atlas: (answered '{msg['question']}')")
        elif msg.get("atlas_note"):
            # Strip any HTML formatting (e.g. a numbered plan's <br>/<b> tags)
            # down to plain text — the router needs to read what Atlas just
            # said, not parse markup, and this is what lets it tell "go"
            # meaning "run the plan I just proposed" apart from "go" meaning
            # "confirm the destructive action I just asked about".
            note = _HTML_TAG_RE.sub(" ", msg["atlas_note"])
            lines.append(f"Atlas: {' '.join(note.split())}")
    return "\n".join(lines)


def say_only(spoken_reply: str) -> None:
    """Append a CHITCHAT-style spoken-only reply to the shared chat history
    (so it shows up in the AI Analyst transcript too) and speak it.
    """
    say(spoken_reply)


def say(spoken_reply: str, chat_html: Optional[str] = None) -> None:
    """Speak `spoken_reply` (short, plain — this is read aloud verbatim, so
    it must never contain HTML) while writing `chat_html` (or, if omitted,
    `spoken_reply` itself) into the chat panel. Use this over say_only
    whenever the on-screen version needs richer formatting than the spoken
    line — e.g. a numbered plan — since the two audiences want different
    amounts of detail: a sentence for the ear, a list for the eye.
    """
    st.session_state.chat_history.append({"role": "assistant", "atlas_note": chat_html or spoken_reply})
    set_state("speaking")
    speak(spoken_reply)


def handle_utterance(utterance: str) -> dict:
    """Classify `utterance`, log it, and either execute it (APP_COMMAND) or
    hand it back to app.py to run through the AI Analyst pipeline
    (DATA_QUESTION). Returns the parsed intent dict either way.
    """
    utterance = (utterance or "").strip()
    if not utterance:
        return dict(FALLBACK_INTENT)

    st.session_state.chat_history.append({"role": "user", "content": utterance})
    set_state("processing")

    intent = classify_intent_fast(utterance)
    if intent is None:
        context = _recent_context()
        intent = classify_intent(utterance, context)

    if intent["type"] == "APP_COMMAND":
        handled = dispatch(intent["action"], intent.get("target"))
        reply = intent["spoken_reply"] or ("On it." if handled else "I don't have that capability yet.")
        if not handled and intent["action"] not in ("confirm", "cancel"):
            reply = "I don't have that capability yet, but I've noted the request."
        st.session_state.chat_history.append({"role": "assistant", "atlas_note": reply})
        set_state("speaking")
        speak(reply)
    elif intent["type"] == "CHITCHAT":
        st.session_state.chat_history.append({"role": "assistant", "atlas_note": intent["spoken_reply"]})
        set_state("speaking")
        speak(intent["spoken_reply"])
    # DATA_QUESTION: deliberately left to app.py — see module docstring.

    return intent


# ═══════════════════════════════════════════════════════════════════════
# TEXT-TO-SPEECH — edge-tts -> gTTS -> text-only, in that order.
# ═══════════════════════════════════════════════════════════════════════
async def _edge_tts_bytes(text: str) -> bytes:
    communicate = edge_tts.Communicate(text, VOICE_NAME)
    chunks = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.extend(chunk["data"])
    return bytes(chunks)


def synthesize_speech(text: str) -> tuple[Optional[bytes], str]:
    """Try edge-tts, then gTTS. Returns (mp3_bytes_or_None, backend_used) —
    backend_used is "edge-tts" | "gtts" | "none". "none" means both are
    unavailable/failed and the caller should degrade to text-only.
    """
    text = (text or "").strip()
    if not text:
        return None, "none"

    if edge_tts is not None:
        try:
            data = asyncio.run(_edge_tts_bytes(text))
            if data:
                return data, "edge-tts"
        except Exception:
            pass

    if gTTS is not None:
        try:
            buf = io.BytesIO()
            gTTS(text=text, lang="en").write_to_fp(buf)
            data = buf.getvalue()
            if data:
                return data, "gtts"
        except Exception:
            pass

    return None, "none"


def speak(text: str) -> None:
    """Render autoplaying TTS audio for `text`, if voice is enabled. Always
    safe to call — degrades to a text-only caption if both backends fail
    or the user has muted Atlas.
    """
    text = (text or "").strip()
    if not text:
        return
    if not st.session_state.get("atlas_voice_enabled", True):
        return
    audio_bytes, backend = synthesize_speech(text)
    if audio_bytes:
        st.audio(audio_bytes, format="audio/mp3", autoplay=True)
    else:
        st.caption("Voice unavailable right now — Atlas is speaking in text only.")


# ═══════════════════════════════════════════════════════════════════════
# PERSISTENT ORB + STATE
# ═══════════════════════════════════════════════════════════════════════
def set_state(state: str) -> None:
    st.session_state.atlas_orb_state = state


def raise_alert(count: int) -> None:
    """Proactive-insight HUD: light up the orb in its 'alert' visual state
    with no user action required, whenever a fresh dataset load surfaces
    `count` high-severity Auto-Insight findings (see app.py's
    announce_ambient_insights(), which calls this right after computing
    `auto_insights.generate_insights()` — zero extra Gemini calls, this is
    purely a visual signal over data already computed).

    A no-op when count <= 0 — nothing to alert about, so the orb's current
    state (idle, or whatever the last real interaction left it in) is left
    alone rather than forced.
    """
    if count <= 0:
        return
    st.session_state.atlas_alert_count = count
    st.session_state.atlas_alert_fresh = True  # see clear_alert()'s docstring
    set_state("alert")


def clear_alert() -> None:
    """Call whenever the Overview tab renders its Auto-Insights panel — the
    point at which the user has actually seen the findings that may have
    triggered raise_alert().

    raise_alert() and this both run within the *same* Streamlit script pass
    when a fresh upload lands while Overview is already the active tab
    (Overview is the default section), since the whole script runs top to
    bottom in one pass. Clearing unconditionally here would erase the alert
    before the browser ever painted it. `atlas_alert_fresh` is a one-run
    grace flag: raise_alert() sets it, and the first time this function
    sees it set it just consumes it (leaving the alert visible for that
    render) instead of clearing — only the *next* time Overview renders
    (a later, separate rerun) does the alert actually clear.
    """
    if st.session_state.get("atlas_alert_fresh"):
        st.session_state.atlas_alert_fresh = False
        return
    st.session_state.atlas_alert_count = 0
    if st.session_state.get("atlas_orb_state") == "alert":
        set_state("idle")


_ORB_CSS = """
<style>
.atlas-orb-wrap {
    position: fixed; bottom: 96px; right: 22px; z-index: 999999;
    display: flex; flex-direction: column; align-items: center; gap: 6px;
    pointer-events: none;
}
.atlas-orb {
    width: 50px; height: 50px; border-radius: 50%;
    background: radial-gradient(circle at 35% 30%, var(--prism-accent2, #A78BFA), var(--prism-accent, #22D3EE));
    box-shadow: 0 0 22px rgba(var(--prism-accent-rgb, 34, 211, 238), 0.55);
    position: relative;
}
.atlas-orb::after {
    content: ""; position: absolute; inset: -8px; border-radius: 50%;
    border: 2px solid rgba(var(--prism-accent-rgb, 34, 211, 238), 0.4);
}
.atlas-orb.idle { animation: atlasPulse 3.2s ease-in-out infinite; }
.atlas-orb.listening { animation: atlasListen 1s ease-in-out infinite; }
.atlas-orb.listening::after { border-color: var(--prism-danger, #F87171); animation: atlasRing 1.2s ease-out infinite; }
.atlas-orb.speaking { animation: atlasSpeak 0.6s ease-in-out infinite; }
/* Sonar/radar ping: two rings expanding outward, staggered by 0.6s so a
   second wave is always mid-flight — reuses the same ::after ring already
   built for .listening (just a different color/timing) plus a new
   ::before for the second wave, rather than a new mechanism. */
.atlas-orb.speaking::after {
    border-color: var(--prism-accent, #22D3EE);
    animation: atlasSonar 1.6s ease-out infinite;
}
.atlas-orb.speaking::before {
    content: ""; position: absolute; inset: -8px; border-radius: 50%;
    border: 2px solid rgba(var(--prism-accent2-rgb, 129, 140, 248), 0.5);
    animation: atlasSonar 1.6s ease-out infinite;
    animation-delay: 0.6s;
}
.atlas-orb.processing::after {
    border-top-color: transparent; border-right-color: transparent;
    animation: atlasSpin 0.9s linear infinite;
}
/* Proactive alert HUD: an unprompted amber pulse (distinct from the red
   .listening ring and the cyan default) so a high-severity Auto-Insight
   finding is visible even if the user never clicks anything — same sonar
   mechanism as .speaking, just recolored and slower so it reads as "waiting
   for you" rather than "actively talking". */
.atlas-orb.alert { background: radial-gradient(circle at 35% 30%, var(--prism-warning, #FBBF24), var(--prism-accent2, #A78BFA)); }
.atlas-orb.alert::after {
    border-color: var(--prism-warning, #FBBF24);
    animation: atlasSonar 2.2s ease-out infinite;
}
.atlas-orb.alert::before {
    content: ""; position: absolute; inset: -8px; border-radius: 50%;
    border: 2px solid rgba(251, 191, 36, 0.5);
    animation: atlasSonar 2.2s ease-out infinite;
    animation-delay: 1.1s;
}
@keyframes atlasPulse { 0%, 100% { transform: scale(1); opacity: 0.9; } 50% { transform: scale(1.08); opacity: 1; } }
@keyframes atlasListen { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.15); } }
@keyframes atlasRing { 0% { transform: scale(1); opacity: 0.9; } 100% { transform: scale(1.6); opacity: 0; } }
@keyframes atlasSpeak { 0%, 100% { transform: scale(1); } 25% { transform: scale(1.05); } 50% { transform: scale(0.97); } 75% { transform: scale(1.08); } }
@keyframes atlasSonar { 0% { transform: scale(1); opacity: 0.85; } 100% { transform: scale(2.1); opacity: 0; } }
@keyframes atlasSpin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
    .atlas-orb, .atlas-orb::after, .atlas-orb::before { animation: none !important; }
}
.atlas-orb-label {
    font-family: 'JetBrains Mono', monospace; font-size: 9px; letter-spacing: 0.05em;
    color: var(--prism-text-muted, #8A97A8); text-transform: uppercase;
    background: var(--prism-surface, #12151B); border: 1px solid var(--prism-border, #232833);
    padding: 2px 8px; border-radius: 999px;
}
.st-key-atlas_confirm_box, .st-key-atlas_transcript_box {
    background: var(--prism-surface, #12151B);
    border: 1px solid var(--prism-border, #232833);
    border-radius: 12px; padding: 0.9rem 1.1rem; margin-bottom: 0.75rem;
}
</style>
"""


_NEURON_BG_JS = """
<script>
(function() {
    const win = window.parent;
    const doc = win.document;
    const panel = doc.querySelector('.st-key-atlas_side_panel');
    if (!panel) return;
    // Marker lives on the panel's own DOM node (not a global flag) so this
    // survives Streamlit reruns cleanly: st.container(key=...) keeps the
    // same node alive across reruns, so the marker (and the loop it guards)
    // persists too — no duplicate animation loops piling up on every rerun.
    if (panel.dataset.neuronInit) return;
    panel.dataset.neuronInit = '1';

    const canvas = doc.createElement('canvas');
    canvas.style.cssText = 'position:absolute;inset:0;z-index:-1;pointer-events:none;opacity:0.55;';
    panel.insertBefore(canvas, panel.firstChild);
    const ctx = canvas.getContext('2d');
    let w, h, dpr;

    function resize() {
        dpr = Math.min(win.devicePixelRatio || 1, 2);
        w = panel.clientWidth; h = panel.clientHeight;
        canvas.width = w * dpr; canvas.height = h * dpr;
        canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();
    win.addEventListener('resize', resize);

    const REDUCED = win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const LINK_DIST = 110;
    const COUNT = Math.min(40, Math.max(16, Math.floor((w * h) / 9000)));
    let nodes = Array.from({ length: COUNT }, () => ({
        x: Math.random() * w, y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.1, vy: (Math.random() - 0.5) * 0.1,
        r: Math.random() * 1.3 + 1,
    }));
    let pulses = [];

    function accentRgb() {
        // Reads Prism's own theme token so the mesh matches whichever theme
        // (Graphite/Midnight/Arctic) is active, same trick as the rest of
        // the app's CSS — no hardcoded color to fall out of sync.
        const v = getComputedStyle(panel).getPropertyValue('--prism-accent-rgb').trim();
        return v || '34,211,238';
    }

    function draw() {
        const rgb = accentRgb();
        ctx.clearRect(0, 0, w, h);
        const links = [];
        for (const n of nodes) {
            n.x += n.vx; n.y += n.vy;
            if (n.x < 0 || n.x > w) n.vx *= -1;
            if (n.y < 0 || n.y > h) n.vy *= -1;
            n.x = Math.max(0, Math.min(w, n.x));
            n.y = Math.max(0, Math.min(h, n.y));
        }
        for (let i = 0; i < nodes.length; i++) {
            for (let j = i + 1; j < nodes.length; j++) {
                const a = nodes[i], b = nodes[j];
                const dist = Math.hypot(a.x - b.x, a.y - b.y);
                if (dist < LINK_DIST) {
                    const alpha = (1 - dist / LINK_DIST) * 0.55;
                    ctx.beginPath();
                    ctx.strokeStyle = `rgba(${rgb},${alpha.toFixed(3)})`;
                    ctx.lineWidth = 0.7;
                    ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
                    ctx.stroke();
                    links.push({ a, b });
                }
            }
        }
        for (const n of nodes) {
            ctx.beginPath();
            ctx.fillStyle = `rgba(${rgb},0.6)`;
            ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
            ctx.fill();
        }
        if (!REDUCED && pulses.length < 2 && links.length && Math.random() < 0.025) {
            const link = links[Math.floor(Math.random() * links.length)];
            pulses.push({ a: link.a, b: link.b, t: 0, speed: 0.015 + Math.random() * 0.01 });
        }
        pulses = pulses.filter((p) => p.t <= 1);
        for (const p of pulses) {
            p.t += p.speed;
            const x = p.a.x + (p.b.x - p.a.x) * p.t;
            const y = p.a.y + (p.b.y - p.a.y) * p.t;
            ctx.beginPath();
            ctx.fillStyle = `rgba(${rgb},0.95)`;
            ctx.shadowColor = `rgba(${rgb},0.95)`;
            ctx.shadowBlur = 6;
            ctx.arc(x, y, 2, 0, Math.PI * 2);
            ctx.fill();
            ctx.shadowBlur = 0;
        }
    }

    if (REDUCED) { draw(); return; }

    function tick() {
        // Panel gone (Demo/Story Mode took over the screen) — stop rather
        // than spin forever against a detached node; a fresh loop starts
        // cleanly next time the panel remounts, since the marker only
        // lives on that (now-discarded) node.
        if (!doc.body.contains(panel)) return;
        if (doc.hidden) { win.requestAnimationFrame(tick); return; }
        draw();
        win.requestAnimationFrame(tick);
    }
    tick();
})();
</script>
"""


def render_neuron_bg() -> None:
    """Animated neuron-network canvas behind the Atlas side panel's message
    list — drifting nodes, fading synapse links when close, an occasional
    bright pulse traveling a live connection. Injected via a zero-height
    components.html() iframe reaching into window.parent.document (the same
    technique modules/ui.py's render_tab_jump_script already uses) rather
    than st.markdown(unsafe_allow_html=True): browsers never execute
    <script> tags inserted via innerHTML (which is what Streamlit's markdown
    path does under the hood), only ones present in a real document's
    initial HTML — which is exactly what a components.html() iframe is.
    Call once per rerun, right after the panel's header markdown.
    """
    import streamlit.components.v1 as components

    components.html(_NEURON_BG_JS, height=0)


def render_orb() -> None:
    """Draw the CSS orb, fixed in the bottom-right corner. Call once per
    rerun, on every screen (landing included) — orb state was last set by
    set_state() during the previous utterance's handling, or defaults to
    idle. Streamlit's script-rerun model means "listening" and "speaking"
    reflect the state as of the moment they were set (this run or the one
    that triggered it) rather than a live, continuously-updated signal —
    there's no bidirectional channel back from the browser's audio/mic
    playback state without a custom component, which is out of scope here.
    """
    state = st.session_state.get("atlas_orb_state", "idle")
    if state == "alert":
        count = st.session_state.get("atlas_alert_count", 0)
        label = f"&#9888; {count} new insight{'s' if count != 1 else ''}" if count else "Atlas &middot; alert"
    else:
        label = f"Atlas &middot; {state}"
    inject_orb_css()
    st.markdown(
        f'<div class="atlas-orb-wrap"><div class="atlas-orb {state}"></div>'
        f'<div class="atlas-orb-label">{label}</div></div>',
        unsafe_allow_html=True,
    )


def inject_orb_css() -> None:
    """Injects _ORB_CSS (the gradient/animation rules every `.atlas-orb`
    element needs, including the small `.atlas-orb-sm` variant in the side
    panel's header) onto the page.

    render_orb() calls this itself, but render_orb() is only invoked for
    the floating standalone orb (landing page, Story/Demo Mode — see its
    call site in app.py). Once a dataset is active, the side panel replaces
    the floating orb with its own small orb in the header — that markup is
    written directly in app.py, not through render_orb(), so without a
    separate call to this function the side panel's orb was a sized-but-
    unstyled div: correct dimensions, no gradient/background, invisible
    against the dark panel. Idempotent (repeated st.markdown(<style>) calls
    just add redundant identical rules), so it's safe to call once per
    rerun from both places.
    """
    st.markdown(_ORB_CSS, unsafe_allow_html=True)
