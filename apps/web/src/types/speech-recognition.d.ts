/**
 * Minimal, spec-accurate ambient types for the Web Speech API's
 * `SpeechRecognition` (TypeScript's own lib.dom.d.ts ships
 * `SpeechRecognitionResult`/`SpeechRecognitionResultList` but omits the
 * `SpeechRecognition` interface and constructor itself, and every current
 * browser that implements it -- Chrome/Edge/Safari -- still only exposes it
 * under the vendor-prefixed `webkitSpeechRecognition` global; Firefox has no
 * implementation at all). Only the members `use-voice.ts` actually reads or
 * sets are declared -- this is not a full spec surface.
 */
interface SpeechRecognitionEvent extends Event {
  readonly resultIndex: number;
  readonly results: SpeechRecognitionResultList;
}

interface SpeechRecognitionErrorEvent extends Event {
  readonly error: string;
}

interface SpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

interface Window {
  SpeechRecognition?: { new (): SpeechRecognition };
  webkitSpeechRecognition?: { new (): SpeechRecognition };
}
