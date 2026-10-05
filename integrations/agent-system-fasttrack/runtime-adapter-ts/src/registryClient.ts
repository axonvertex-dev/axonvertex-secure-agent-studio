import type { FetchLike, InvocationResolution, ResolveRequest } from "./types.js";

export class RegistryClient {
  constructor(
    private readonly baseUrl: string,
    private readonly adminToken: string,
    private readonly fetchImpl: FetchLike = fetch,
  ) {
    if (!baseUrl.startsWith("http://") && !baseUrl.startsWith("https://")) {
      throw new Error("Registry base URL must be http(s)");
    }
    if (!adminToken.trim()) {
      throw new Error("Registry admin token is required");
    }
  }

  async resolve(request: ResolveRequest): Promise<InvocationResolution> {
    const response = await this.fetchImpl(
      `${this.baseUrl.replace(/\/$/, "")}/v1/invocations/resolve`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${this.adminToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(request),
      },
    );

    const body = await response.text();
    if (!response.ok) {
      throw new Error(`Registry resolution failed: HTTP ${response.status}: ${body.slice(0, 500)}`);
    }

    const parsed = JSON.parse(body) as InvocationResolution;
    if (!parsed.resolutionId || !parsed.decision || !Array.isArray(parsed.reasons)) {
      throw new Error("Registry returned an incomplete resolution");
    }
    return parsed;
  }
}
