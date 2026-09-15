"use client";

/**
 * Atlas's Voice Operating Layer: push-to-talk dictation, a "wake phrase"
 * continuous-listening mode, and spoken read-back, all on top of the
 * browser's own Web Speech API -- no backend, no new dependency. Feature
 * detection is real: `supported` is false wherever `SpeechRecognition`
 * isn't exposed (Firefox has none at all; WebKitGTK's Linux build has
 * historically lacked a working STT backend, which is exactly why this
 * stays behind a real capability check rather than assuming every browser
 * -- desktop-shell's webview included -- can do this).
 *
 * "Wake mode" here means literal phrase-matching against the browser's own
 * continuous transcript stream, not a dedicated low-power wake-word
 * detector (Web Speech API has no such primitive) -- so it only listens
 * while the tab is open and the user has explicitly armed it, never in
 * the background.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export type VoiceMode = "idle" | "listening" | "speaking";
export type VoiceVerbosity = "concise" | "full" | "off";

const STORAGE_KEY = "prism.voice.settings.v1";
const WAKE_PHRASES = ["hey atlas", "atlas"];

type StoredSettings = { enabled: boolean; verbosity: VoiceVerbosity };

const defaultSettings: StoredSettings = { enabled: false, verbosity: "concise" };

function readSettings(): StoredSettings {
  if (typeof window === "undefined") return defaultSettings;
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<StoredSettings>;
    const verbosity: VoiceVerbosity = parsed.verbosity === "full" || parsed.verbosity === "off" ? parsed.verbosity : "concise";
    return { enabled: Boolean(parsed.enabled), verbosity };
  } catch {
    return defaultSettings;
  }
}

function speechRecognitionCtor(): { new (): SpeechRecognition } | undefined {
  if (typeof window === "undefined") return undefined;
  return window.SpeechRecognition ?? window.webkitSpeechRecognition;
}

/** Strips a leading wake phrase ("atlas", "hey atlas") from one final
 * transcript segment. `woke: true, command: ""` means the phrase was said
 * alone -- the caller should keep listening for the next segment as the
 * actual command, never guess one. */
export function parseWakeUtterance(raw: string): { woke: boolean; command: string } {
  const text = raw.trim();
  const lower = text.toLowerCase();
  for (const phrase of WAKE_PHRASES) {
    if (lower === phrase) return { woke: true, command: "" };
    if (lower.startsWith(`${phrase} `) || lower.startsWith(`${phrase},`)) {
      return { woke: true, command: text.slice(phrase.length).replace(/^,\s*/, "").trim() };
    }
  }
  return { woke: false, command: "" };
}

/** What to actually speak for a given verbosity -- `null` means say
 * nothing. "Concise" reads only the first sentence rather than a truncated
 * mid-word fragment; "full" reads the real answer verbatim, never a
 * paraphrase this layer invents. */
export function speakableAnswer(answer: string, verbosity: VoiceVerbosity): string | null {
  if (verbosity === "off" || !answer.trim()) return null;
  if (verbosity === "full") return answer;
  const firstSentence = /^[^.!?]*[.!?]/.exec(answer);
  return firstSentence ? firstSentence[0].trim() : answer.length > 200 ? `${answer.slice(0, 200)}…` : answer;
}

export type VoiceLayer = {
  supported: boolean;
  enabled: boolean;
  wakeArmed: boolean;
  mode: VoiceMode;
  transcript: string;
  verbosity: VoiceVerbosity;
  enable(): void;
  disable(): void;
  setVerbosity(verbosity: VoiceVerbosity): void;
  pushToTalk(): void;
  toggleWake(): void;
  speak(text: string): void;
  stopSpeaking(): void;
};

/** `onCommand` fires with one finalized utterance -- a push-to-talk result,
 * or a wake-phrase-stripped command -- and is the caller's sole hook for
 * deciding what a spoken command does; this layer never routes or executes
 * anything itself. */
export function useVoiceLayer(onCommand: (text: string) => void): VoiceLayer {
  const [settings, setSettings] = useState<StoredSettings>(defaultSettings);
  const [ready, setReady] = useState(false);
  const [wakeArmed, setWakeArmed] = useState(false);
  const [mode, setMode] = useState<VoiceMode>("idle");
  const [transcript, setTranscript] = useState("");
  const [supported, setSupported] = useState(false);

  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const onCommandRef = useRef(onCommand);
  onCommandRef.current = onCommand;
  const wakeArmedRef = useRef(false);
  wakeArmedRef.current = wakeArmed;

  useEffect(() => {
    setSettings(readSettings());
    setSupported(Boolean(speechRecognitionCtor()) && typeof window !== "undefined" && "speechSynthesis" in window);
    setReady(true);
  }, []);
  useEffect(() => {
    if (ready) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  }, [settings, ready]);

  const stopSpeaking = useCallback(() => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
  }, []);

  const speak = useCallback(
    (text: string) => {
      const line = speakableAnswer(text, settings.verbosity);
      if (!supported || !line) return;
      stopSpeaking();
      const utterance = new SpeechSynthesisUtterance(line);
      utterance.onstart = () => setMode("speaking");
      utterance.onend = () => setMode((current) => (current === "speaking" ? "idle" : current));
      utterance.onerror = () => setMode((current) => (current === "speaking" ? "idle" : current));
      window.speechSynthesis.speak(utterance);
    },
    [supported, settings.verbosity, stopSpeaking]
  );

  const runRecognitionSession = useCallback(
    (continuous: boolean) => {
      const Ctor = speechRecognitionCtor();
      if (!Ctor) return;
      stopSpeaking(); // Interruption handling: starting to listen always cuts off anything being spoken.
      recognitionRef.current?.abort();
      const recognition = new Ctor();
      recognition.continuous = continuous;
      recognition.interimResults = true;
      recognition.lang = "en-US";
      recognition.onstart = () => {
        setMode("listening");
        setTranscript("");
      };
      recognition.onresult = (event) => {
        let interim = "";
        let final = "";
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const result = event.results.item(i);
          const alternative = result.item(0);
          if (result.isFinal) final += alternative.transcript;
          else interim += alternative.transcript;
        }
        if (final) {
          setTranscript(final);
          if (continuous) {
            const parsed = parseWakeUtterance(final);
            if (parsed.woke && parsed.command) onCommandRef.current(parsed.command);
            // A bare wake phrase (no command yet) just keeps this same
            // continuous session running, listening for the next segment.
          } else {
            onCommandRef.current(final.trim());
          }
        } else {
          setTranscript(interim);
        }
      };
      recognition.onend = () => {
        recognitionRef.current = null;
        if (continuous && wakeArmedRef.current) {
          // Browsers stop a continuous session after a silence window even
          // though nothing asked it to stop -- restart to keep wake mode
          // genuinely continuous rather than silently going deaf.
          runRecognitionSession(true);
        } else {
          setMode("idle");
        }
      };
      recognition.onerror = () => {
        recognitionRef.current = null;
        if (!continuous) setMode("idle");
      };
      recognitionRef.current = recognition;
      recognition.start();
    },
    [stopSpeaking]
  );

  const pushToTalk = useCallback(() => {
    if (!supported || !settings.enabled) return;
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      return;
    }
    runRecognitionSession(false);
  }, [supported, settings.enabled, runRecognitionSession]);

  const toggleWake = useCallback(() => {
    if (!supported || !settings.enabled) return;
    if (wakeArmedRef.current) {
      setWakeArmed(false);
      recognitionRef.current?.stop();
      recognitionRef.current = null;
      setMode("idle");
    } else {
      setWakeArmed(true);
      runRecognitionSession(true);
    }
  }, [supported, settings.enabled, runRecognitionSession]);

  useEffect(
    () => () => {
      recognitionRef.current?.abort();
      stopSpeaking();
    },
    [stopSpeaking]
  );

  return {
    supported,
    enabled: settings.enabled,
    wakeArmed,
    mode,
    transcript,
    verbosity: settings.verbosity,
    enable: () => setSettings((current) => ({ ...current, enabled: true })),
    disable: () => {
      setSettings((current) => ({ ...current, enabled: false }));
      setWakeArmed(false);
      recognitionRef.current?.abort();
      recognitionRef.current = null;
      stopSpeaking();
      setMode("idle");
    },
    setVerbosity: (verbosity) => setSettings((current) => ({ ...current, verbosity })),
    pushToTalk,
    toggleWake,
    speak,
    stopSpeaking,
  };
}
