import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseWakeUtterance, speakableAnswer, useVoiceLayer } from "./use-voice";

describe("parseWakeUtterance", () => {
  it("recognizes the wake phrase alone as woken with no command yet, never a guessed one", () => {
    expect(parseWakeUtterance("Atlas")).toEqual({ woke: true, command: "" });
    expect(parseWakeUtterance("hey atlas")).toEqual({ woke: true, command: "" });
  });

  it("strips the wake phrase and keeps the real command that follows it", () => {
    expect(parseWakeUtterance("Atlas profile this dataset")).toEqual({ woke: true, command: "profile this dataset" });
    expect(parseWakeUtterance("Hey Atlas, what drives churn")).toEqual({ woke: true, command: "what drives churn" });
  });

  it("never wakes on an utterance that merely mentions Atlas mid-sentence", () => {
    expect(parseWakeUtterance("show me the atlas dashboard")).toEqual({ woke: false, command: "" });
    expect(parseWakeUtterance("what is prism atlas")).toEqual({ woke: false, command: "" });
  });
});

describe("speakableAnswer", () => {
  it("says nothing when verbosity is off or the answer is empty, rather than reading blank silence", () => {
    expect(speakableAnswer("Churn correlates with support volume.", "off")).toBeNull();
    expect(speakableAnswer("   ", "concise")).toBeNull();
  });

  it("reads only the first sentence for concise, the real answer verbatim for full", () => {
    const answer = "Churn correlates with support-ticket volume. Confidence is moderate given the sample size.";
    expect(speakableAnswer(answer, "concise")).toBe("Churn correlates with support-ticket volume.");
    expect(speakableAnswer(answer, "full")).toBe(answer);
  });

  it("falls back to a bounded prefix for concise when the answer has no sentence punctuation", () => {
    const long = "a".repeat(250);
    expect(speakableAnswer(long, "concise")).toBe(`${"a".repeat(200)}…`);
  });
});

describe("useVoiceLayer", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("reports unsupported and stays inert when the browser has no SpeechRecognition", () => {
    const onCommand = vi.fn();
    const { result } = renderHook(() => useVoiceLayer(onCommand));
    expect(result.current.supported).toBe(false);
    act(() => result.current.pushToTalk());
    expect(result.current.mode).toBe("idle");
    expect(onCommand).not.toHaveBeenCalled();
  });

  it("starts a real recognition session on push-to-talk and routes the final transcript to onCommand, never an interim one", async () => {
    const instances: FakeSpeechRecognition[] = [];
    class FakeSpeechRecognition {
      continuous = false;
      interimResults = false;
      lang = "";
      onstart: (() => void) | null = null;
      onend: (() => void) | null = null;
      onresult: ((event: SpeechRecognitionEvent) => void) | null = null;
      onerror: ((event: SpeechRecognitionErrorEvent) => void) | null = null;
      started = false;
      constructor() {
        instances.push(this);
      }
      start() {
        this.started = true;
        this.onstart?.();
      }
      stop() {
        this.onend?.();
      }
      abort() {
        this.onend?.();
      }
    }
    vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
    vi.stubGlobal("speechSynthesis", { cancel: vi.fn(), speak: vi.fn() });
    vi.stubGlobal("SpeechSynthesisUtterance", class {} as unknown as typeof SpeechSynthesisUtterance);

    const onCommand = vi.fn();
    const { result } = renderHook(() => useVoiceLayer(onCommand));
    expect(result.current.supported).toBe(true);

    act(() => result.current.enable());
    await waitFor(() => expect(result.current.enabled).toBe(true));

    act(() => result.current.pushToTalk());
    await waitFor(() => expect(result.current.mode).toBe("listening"));
    expect(instances).toHaveLength(1);
    expect(instances[0]!.continuous).toBe(false);

    const interimResult = { isFinal: false, length: 1, item: () => ({ transcript: "profile th", confidence: 1 }) } as unknown as SpeechRecognitionResult;
    act(() => {
      instances[0]!.onresult?.({ resultIndex: 0, results: { length: 1, item: (i: number) => (i === 0 ? interimResult : interimResult) } } as unknown as SpeechRecognitionEvent);
    });
    expect(onCommand).not.toHaveBeenCalled();
    expect(result.current.transcript).toBe("profile th");

    const finalResult = { isFinal: true, length: 1, item: () => ({ transcript: "profile this dataset", confidence: 1 }) } as unknown as SpeechRecognitionResult;
    act(() => {
      instances[0]!.onresult?.({ resultIndex: 0, results: { length: 1, item: (i: number) => (i === 0 ? finalResult : finalResult) } } as unknown as SpeechRecognitionEvent);
    });
    expect(onCommand).toHaveBeenCalledWith("profile this dataset");
  });

  it("strips the wake phrase before routing a wake-mode command, and never routes a bare wake phrase as a command", async () => {
    const instances: Array<{ onresult: ((event: SpeechRecognitionEvent) => void) | null; continuous: boolean }> = [];
    class FakeSpeechRecognition {
      continuous = false;
      interimResults = false;
      lang = "";
      onstart: (() => void) | null = null;
      onend: (() => void) | null = null;
      onresult: ((event: SpeechRecognitionEvent) => void) | null = null;
      onerror: ((event: SpeechRecognitionErrorEvent) => void) | null = null;
      constructor() {
        instances.push(this);
      }
      start() {
        this.onstart?.();
      }
      stop() {
        this.onend?.();
      }
      abort() {
        this.onend?.();
      }
    }
    vi.stubGlobal("SpeechRecognition", FakeSpeechRecognition);
    vi.stubGlobal("speechSynthesis", { cancel: vi.fn(), speak: vi.fn() });
    vi.stubGlobal("SpeechSynthesisUtterance", class {} as unknown as typeof SpeechSynthesisUtterance);

    const onCommand = vi.fn();
    const { result } = renderHook(() => useVoiceLayer(onCommand));
    act(() => result.current.enable());
    await waitFor(() => expect(result.current.enabled).toBe(true));
    act(() => result.current.toggleWake());
    await waitFor(() => expect(result.current.wakeArmed).toBe(true));
    expect(instances[0]!.continuous).toBe(true);

    const bareWake = { isFinal: true, length: 1, item: () => ({ transcript: "Atlas", confidence: 1 }) } as unknown as SpeechRecognitionResult;
    act(() => {
      instances[0]!.onresult?.({ resultIndex: 0, results: { length: 1, item: () => bareWake } } as unknown as SpeechRecognitionEvent);
    });
    expect(onCommand).not.toHaveBeenCalled();

    const withCommand = { isFinal: true, length: 1, item: () => ({ transcript: "Atlas summarize the risks", confidence: 1 }) } as unknown as SpeechRecognitionResult;
    act(() => {
      instances[0]!.onresult?.({ resultIndex: 0, results: { length: 1, item: () => withCommand } } as unknown as SpeechRecognitionEvent);
    });
    expect(onCommand).toHaveBeenCalledWith("summarize the risks");
  });
});
