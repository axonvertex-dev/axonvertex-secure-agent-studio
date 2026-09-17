import "dotenv/config";

interface ModelInfo {
  id?: string;
  max_model_len?: number;
  [key: string]: unknown;
}

interface ModelsResponse {
  object?: string;
  data?: ModelInfo[];
}

interface ChatResponse {
  choices?: Array<{
    finish_reason?: string;
    message?: {
      role?: string;
      content?: string | null;
    };
  }>;

  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
}

const baseUrl = (
  process.env.GEMMA_BASE_URL ??
  "http://127.0.0.1:11433/v1"
).replace(/\/+$/, "");

const configuredModel =
  process.env.GEMMA_MODEL ??
  "gemma-4-12b-it-qat";

const apiKey =
  process.env.GEMMA_API_KEY?.trim() ?? "";

if (!apiKey) {
  throw new Error("GEMMA_API_KEY is missing from .env");
}

async function requestJson<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const headers = new Headers(init?.headers);

  headers.set("Content-Type", "application/json");
  headers.set("Authorization", `Bearer ${apiKey}`);

  const response = await fetch(
    `${baseUrl}${path}`,
    {
      ...init,
      headers
    }
  );

  const raw = await response.text();

  let parsed: unknown;

  try {
    parsed = JSON.parse(raw);
  } catch {
    parsed = raw;
  }

  if (!response.ok) {
    throw new Error(
      `HTTP ${response.status} ${response.statusText}\n` +
      `${JSON.stringify(parsed, null, 2)}`
    );
  }

  return parsed as T;
}

async function main(): Promise<void> {
  console.log("==============================================");
  console.log(" AXONVERTEX Secure Agent Studio");
  console.log(" Checkpoint 0 — Node A Inference Contract");
  console.log("==============================================");

  console.log();
  console.log(`Endpoint : ${baseUrl}`);
  console.log(`Model    : ${configuredModel}`);

  const models =
    await requestJson<ModelsResponse>("/models");

  const liveModel =
    models.data?.find(
      item => item.id === configuredModel
    );

  if (!liveModel) {
    throw new Error(
      `Configured model '${configuredModel}' was not advertised`
    );
  }

  console.log();
  console.log("Live model:");
  console.log(
    JSON.stringify(
      {
        id: liveModel.id,
        maxModelLen: liveModel.max_model_len ?? null
      },
      null,
      2
    )
  );

  const startedAt = performance.now();

  const completion =
    await requestJson<ChatResponse>(
      "/chat/completions",
      {
        method: "POST",
        body: JSON.stringify({
          model: configuredModel,
          messages: [
            {
              role: "system",
              content:
                "You are an inference connectivity probe. " +
                "Follow the output instruction exactly."
            },
            {
              role: "user",
              content:
                "Return exactly AXONVERTEX_PROBE_OK and nothing else."
            }
          ],
          temperature: 0,
          max_tokens: 32
        })
      }
    );

  const elapsedMs =
    performance.now() - startedAt;

  const responseText =
    completion.choices?.[0]?.message?.content?.trim() ?? "";

  const status =
    responseText === "AXONVERTEX_PROBE_OK"
      ? "PASS"
      : "UNEXPECTED_OUTPUT";

  const report = {
    probe: "node-a-gemma-inference-contract",
    status,
    endpoint: baseUrl,
    model: configuredModel,
    maxModelLen: liveModel.max_model_len ?? null,
    response: responseText,
    finishReason:
      completion.choices?.[0]?.finish_reason ?? null,
    usage: completion.usage ?? null,
    elapsedMs: Math.round(elapsedMs)
  };

  console.log();
  console.log("Probe result:");
  console.log(JSON.stringify(report, null, 2));

  if (status !== "PASS") {
    process.exitCode = 2;
  }
}

main().catch((error: unknown) => {
  console.error();
  console.error("PROBE FAILED");

  if (error instanceof Error) {
    console.error(error.stack ?? error.message);
  } else {
    console.error(error);
  }

  process.exitCode = 1;
});
