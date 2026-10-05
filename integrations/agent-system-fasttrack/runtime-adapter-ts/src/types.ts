export type ChatRole = "system" | "user" | "assistant";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface ResolvedRuntime {
  id: string;
  modelId: string;
  engine: string;
  nodeRef: string;
  endpointRef: string;
  credentialRef: string;
}

export interface InvocationResolution {
  resolutionId: string;
  decision: "ALLOW" | "DENY";
  scope: "LAB_ONLY";
  reasons: string[];
  agentId?: string;
  agentRevision?: number;
  revisionDigest?: string;
  bindingId?: string;
  admissionId?: string;
  purpose: string;
  runtime?: ResolvedRuntime;
  issuedAt: string;
  expiresAt?: string;
}

export interface ResolveRequest {
  namespace: string;
  name: string;
  purpose: string;
}

export interface RuntimeTarget {
  endpointRef: string;
  credentialRef: string;
  modelId: string;
  engine: string;
  baseUrlEnv: string;
  defaultBaseUrl: string;
  apiKeyEnv: string;
}

export interface RuntimeTargetConfig {
  schemaVersion: string;
  runtimes: Record<string, RuntimeTarget>;
}

export interface GovernedInvocationRequest extends ResolveRequest {
  messages: ChatMessage[];
  temperature?: number;
  maxTokens?: number;
  timeoutMs?: number;
}

export interface InvocationEvidence {
  schemaVersion: "1.0";
  resolutionId: string;
  decision: "ALLOW";
  scope: "LAB_ONLY";
  agentId: string;
  agentRevision: number;
  revisionDigest: string;
  bindingId: string;
  admissionId: string;
  namespace: string;
  agentName: string;
  purpose: string;
  runtimeId: string;
  modelId: string;
  engine: string;
  nodeRef: string;
  endpointRef: string;
  requestDigest: string;
  responseDigest: string;
  issuedAt: string;
  resolutionExpiresAt: string;
  completedAt: string;
}

export interface GovernedInvocationResult {
  content: string;
  reasoningContent?: string;
  finishReason?: string;
  usage?: unknown;
  evidence: InvocationEvidence;
}

export type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;
