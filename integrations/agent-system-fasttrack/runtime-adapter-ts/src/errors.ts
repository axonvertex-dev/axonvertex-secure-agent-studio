export class GovernanceDeniedError extends Error {
  constructor(
    public readonly decision: "DENY",
    public readonly reasons: string[],
    public readonly resolutionId: string,
  ) {
    super(`Registry denied invocation: ${reasons.join(", ") || "unspecified reason"}`);
    this.name = "GovernanceDeniedError";
  }
}

export class RuntimeMappingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RuntimeMappingError";
  }
}

export class SecretResolutionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SecretResolutionError";
  }
}

export class RuntimeInvocationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RuntimeInvocationError";
  }
}
