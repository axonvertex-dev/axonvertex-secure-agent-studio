/** Authenticated Gemma adapter, deliberately stateless across user conversations. */
export type GemmaMessage = {role: "system" | "user" | "assistant"; content: string};
export interface GemmaResult {
  content: string;
  finishReason: string;
  usage: {prompt_tokens?: number; completion_tokens?: number};
}
type FetchLike = typeof fetch;
export class SharedGemmaClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly model: string;
  private readonly transport: FetchLike;
  constructor(options: {baseUrl: string; apiKey: string; model: string; transport?: FetchLike}) {
    if (!options.apiKey || !options.baseUrl.startsWith("http") || !options.model) throw new Error("INVALID_GEMMA_CONFIG");
    this.baseUrl = options.baseUrl.replace(/\/+$/, ""); this.apiKey = options.apiKey;
    this.model = options.model; this.transport = options.transport ?? fetch;
  }
  async complete(messages: readonly GemmaMessage[], signal: AbortSignal, maxTokens = 256): Promise<GemmaResult> {
    if (!messages.length || !Number.isSafeInteger(maxTokens) || maxTokens < 1 || maxTokens > 2048 ||
        messages.some(m => !["system", "user", "assistant"].includes(m.role) || typeof m.content !== "string"))
      throw new Error("INVALID_GEMMA_MESSAGES");
    // No saved conversation state in the model adapter: the caller explicitly provides
    // an authorized context package for THIS invocation only.
    const response = await this.transport(`${this.baseUrl}/chat/completions`, {
      method: "POST", signal,
      headers: {"Content-Type": "application/json", Authorization: `Bearer ${this.apiKey}`},
      body: JSON.stringify({model: this.model,
        messages: messages.map(m => ({role: m.role, content: m.content})),
        temperature: 0, max_tokens: maxTokens,
        chat_template_kwargs: {enable_thinking: false}})
    });
    // Do not expose raw backend body: it could contain prompts, auth details or private data.
    if (!response.ok) throw new Error(`GEMMA_HTTP_${response.status}`);
    const data: unknown = await response.json();
    if (!data || typeof data !== "object" || !("choices" in data)) throw new Error("GEMMA_PROTOCOL_ERROR");
    const obj = data as {choices?: Array<{finish_reason?: string; message?: {content?: unknown}}>,
      usage?: {prompt_tokens?: number; completion_tokens?: number}};
    const choice = obj.choices?.[0];
    if (choice?.finish_reason !== "stop" || typeof choice.message?.content !== "string" || !choice.message.content.trim())
      throw new Error(`GEMMA_INCOMPLETE_${choice?.finish_reason ?? "unknown"}`);
    return {content: choice.message.content, finishReason: choice.finish_reason,
      usage: {prompt_tokens: obj.usage?.prompt_tokens, completion_tokens: obj.usage?.completion_tokens}};
  }
}
