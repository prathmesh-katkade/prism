import type { ApiRequest, ApiTransport, SseEvent, SseRequest } from "@prism/api-contracts";

export class RestSseTransport implements ApiTransport {
  public constructor(private readonly baseUrl: URL) {}

  public async request<TResponse>(request: ApiRequest): Promise<TResponse> {
    const response = await fetch(new URL(request.path, this.baseUrl), {
      method: request.method ?? "GET",
      ...(request.body === undefined ? {} : {
        body: JSON.stringify(request.body),
        headers: { "content-type": "application/json" }
      }),
      ...(request.signal === undefined ? {} : { signal: request.signal })
    });
    if (!response.ok) throw new Error(`PRISM API request failed: ${response.status}`);
    return (await response.json()) as TResponse;
  }

  public async *subscribe(request: SseRequest): AsyncIterable<SseEvent> {
    const response = await fetch(new URL(request.path, this.baseUrl), {
      headers: { accept: "text/event-stream" },
      ...(request.signal === undefined ? {} : { signal: request.signal })
    });
    if (!response.ok || response.body === null) throw new Error("PRISM SSE connection failed");
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) return;
      buffer += chunk.value;
      const messages = buffer.split("\n\n");
      buffer = messages.pop() ?? "";
      for (const message of messages) yield parseSseEvent(message);
    }
  }
}

function parseSseEvent(message: string): SseEvent {
  const fields = new Map(message.split("\n").map((line) => {
    const [key, ...rest] = line.split(":");
    return [key ?? "", rest.join(":").trim()] as const;
  }));
  const id = fields.get("id");
  return {
    event: fields.get("event") ?? "message",
    ...(id === undefined ? {} : { id }),
    data: JSON.parse(fields.get("data") ?? "null")
  };
}
