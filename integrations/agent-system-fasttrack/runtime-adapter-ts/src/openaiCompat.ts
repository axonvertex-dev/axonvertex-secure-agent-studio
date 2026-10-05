import type { ChatMessage, FetchLike } from "./types.js";
import { RuntimeInvocationError } from "./errors.js";
import type { MaterializedRuntime } from "./runtimeConfig.js";

interface OpenAIChoice {
  finish_reason?: string;
  message?: {
    content?: string | null;
    reasoning_content?: string | null;
  };
}

interface OpenAIResponse {
  choices?: OpenAIChoice[];
  usage?: unknown;
}

export interface ModelInvocationOptions {
  messages: ChatMessage[];
  temperature: number;
  maxTokens: number;
  timeoutMs: number;
}

export async function invokeOpenAICompatible(
  runtime: MaterializedRuntime,
  options: ModelInvocationOptions,
  fetchImpl: FetchLike = fetch,
): Promise<{
  raw: OpenAIResponse;
  content: string;
  reasoningContent?: string;
  finishReason?: string;
}> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs);

  try {
    const payload = {
      model: runtime.modelId,
      messages: options.messages,
      temperature: options.temperature,
      max_tokens: options.maxTokens,
    };

    const response = await fetchImpl(`${runtime.baseUrl}/chat/completions`, {
      method: "POST",
      signal: controller.signal,
      headers: {
        Authorization: `Bearer ${runtime.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const body = await response.text();
    if (!response.ok) {
      throw new RuntimeInvocationError(
        `Runtime ${runtime.id} returned HTTP ${response.status}: ${body.slice(0, 500)}`,
      );
    }

    const parsed = JSON.parse(body) as OpenAIResponse;
    const first = parsed.choices?.[0];
    const content = first?.message?.content ?? "";
    const reasoningContent = first?.message?.reasoning_content ?? undefined;

    if (!content && !reasoningContent) {
      throw new RuntimeInvocationError(`Runtime ${runtime.id} returned no model content`);
    }

    return {
      raw: parsed,
      content,
      ...(reasoningContent ? { reasoningContent } : {}),
      ...(first?.finish_reason ? { finishReason: first.finish_reason } : {}),
    };
  } catch (error) {
    if (error instanceof RuntimeInvocationError) {
      throw error;
    }
    if (error instanceof Error && error.name === "AbortError") {
      throw new RuntimeInvocationError(`Runtime ${runtime.id} timed out`);
    }
    throw new RuntimeInvocationError(
      `Runtime ${runtime.id} invocation failed: ${error instanceof Error ? error.message : String(error)}`,
    );
  } finally {
    clearTimeout(timer);
  }
}
