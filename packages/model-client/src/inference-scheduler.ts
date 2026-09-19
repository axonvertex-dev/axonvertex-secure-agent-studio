/** Checkpoint 2E-0.4C: shared, single-process inference admission queue.
 * Task WAITING states live in the durable Agent Runtime, not in the GPU scheduler.
 * Do not instantiate one of these per API request: all callers must share one instance.
 */
export type InferenceLane = "chat" | "workflow" | "background";
export type SchedulerEventType = "QUEUED" | "STARTED" | "FINISHED" | "FAILED" | "CANCELLED";
export interface SchedulerEvent {
  type: SchedulerEventType;
  taskId: string;
  contextId: string;
  lane: InferenceLane;
  timestampMs: number;
  queuedMs?: number;
  executionMs?: number;
  errorCode?: "ABORTED" | "EXECUTION_FAILED";
}
export interface InferenceRequest<T> {
  taskId: string;
  contextId: string;
  lane: InferenceLane;
  /** Only one active model request at a time by default. The signal must reach fetch. */
  execute: (signal: AbortSignal) => Promise<T>;
  signal?: AbortSignal;
  timeoutMs?: number;
}
export interface ScheduleResult<T> {
  value: T;
  taskId: string;
  contextId: string;
  lane: InferenceLane;
  queuedMs: number;
  executionMs: number;
}
type Pending = {
  req: InferenceRequest<unknown>;
  queuedAt: number;
  resolve: (value: ScheduleResult<unknown>) => void;
  reject: (error: Error) => void;
  detachAbort?: () => void;
};

export class SharedInferenceScheduler {
  private readonly lanes: Record<InferenceLane, Pending[]> = {chat: [], workflow: [], background: []};
  private readonly weights: readonly InferenceLane[] = ["chat", "chat", "workflow", "chat", "workflow", "background"];
  private cursor = 0;
  private running = 0;
  private closed = false;
  private pumpQueued = false;
  private readonly ids = new Set<string>();
  private readonly maxQueued: number;
  private readonly onEvent?: (event: SchedulerEvent) => void;

  constructor(options: {maxQueued?: number; onEvent?: (event: SchedulerEvent) => void} = {}) {
    this.maxQueued = options.maxQueued ?? 128;
    if (!Number.isSafeInteger(this.maxQueued) || this.maxQueued < 1) throw new Error("Invalid queue limit");
    this.onEvent = options.onEvent;
  }
  snapshot(): {active: number; queued: Record<InferenceLane, number>; closed: boolean} {
    return {active: this.running, closed: this.closed, queued: {
      chat: this.lanes.chat.length, workflow: this.lanes.workflow.length, background: this.lanes.background.length
    }};
  }
  private notify(type: SchedulerEventType, item: Pending, extra: Partial<SchedulerEvent> = {}): void {
    try { this.onEvent?.({type, taskId: item.req.taskId, contextId: item.req.contextId,
      lane: item.req.lane, timestampMs: Date.now(), ...extra}); } catch { /* audit sink must not block inference */ }
  }
  schedule<T>(req: InferenceRequest<T>): Promise<ScheduleResult<T>> {
    if (this.closed) return Promise.reject(new Error("SCHEDULER_CLOSED"));
    if (!req.taskId || !req.contextId || !["chat", "workflow", "background"].includes(req.lane) ||
      typeof req.execute !== "function") return Promise.reject(new Error("INVALID_INFERENCE_REQUEST"));
    if (req.timeoutMs !== undefined && (!Number.isSafeInteger(req.timeoutMs) || req.timeoutMs < 1))
      return Promise.reject(new Error("INVALID_TIMEOUT"));
    if (this.ids.has(req.taskId)) return Promise.reject(new Error("DUPLICATE_INFERENCE_TASK_ID"));
    if (Object.values(this.lanes).reduce((sum, queue) => sum + queue.length, 0) >= this.maxQueued)
      return Promise.reject(new Error("INFERENCE_QUEUE_FULL"));
    if (req.signal?.aborted) return Promise.reject(new Error("ABORTED"));
    this.ids.add(req.taskId);
    return new Promise<ScheduleResult<T>>((resolve, reject) => {
      const item: Pending = {req: req as InferenceRequest<unknown>, queuedAt: Date.now(),
        resolve: resolve as (result: ScheduleResult<unknown>) => void, reject};
      if (req.signal) {
        const abort = () => {
          const queue = this.lanes[req.lane];
          const index = queue.indexOf(item);
          if (index >= 0) {
            queue.splice(index, 1); item.detachAbort?.(); this.ids.delete(req.taskId);
            this.notify("CANCELLED", item, {errorCode: "ABORTED"}); item.reject(new Error("ABORTED"));
          }
        };
        req.signal.addEventListener("abort", abort, {once: true});
        item.detachAbort = () => req.signal?.removeEventListener("abort", abort);
      }
      this.lanes[req.lane].push(item);
      this.notify("QUEUED", item);
      this.requestPump();
    });
  }
  private requestPump(): void {
    if (this.pumpQueued || this.closed) return;
    this.pumpQueued = true;
    queueMicrotask(() => {this.pumpQueued = false; this.pump();});
  }
  private choose(): Pending | undefined {
    for (let i = 0; i < this.weights.length; i++) {
      const at = (this.cursor + i) % this.weights.length;
      const queue = this.lanes[this.weights[at]];
      if (queue.length) {this.cursor = (at + 1) % this.weights.length; return queue.shift();}
    }
    return undefined;
  }
  private pump(): void {
    if (this.running !== 0 || this.closed) return;
    const item = this.choose(); if (!item) return;
    item.detachAbort?.();
    this.running = 1;
    void this.executeItem(item);
  }
  private async executeItem(item: Pending): Promise<void> {
    const began = Date.now(); const queuedMs = began - item.queuedAt;
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (item.req.signal?.aborted) abort();
    item.req.signal?.addEventListener("abort", abort, {once: true});
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (item.req.timeoutMs) timer = setTimeout(abort, item.req.timeoutMs);
    this.notify("STARTED", item, {queuedMs});
    try {
      // NEVER release admission until execute settles. An abort signal is not proof
      // that the remote model request has stopped; the adapter must settle fetch.
      if (controller.signal.aborted) throw new Error("ABORTED");
      const value = await item.req.execute(controller.signal);
      if (controller.signal.aborted) throw new Error("ABORTED");
      const executionMs = Date.now() - began;
      this.notify("FINISHED", item, {queuedMs, executionMs});
      item.resolve({value, taskId: item.req.taskId, contextId: item.req.contextId,
        lane: item.req.lane, queuedMs, executionMs});
    } catch (error) {
      const aborted = controller.signal.aborted;
      this.notify(aborted ? "CANCELLED" : "FAILED", item,
        {queuedMs, executionMs: Date.now() - began, errorCode: aborted ? "ABORTED" : "EXECUTION_FAILED"});
      item.reject(error instanceof Error ? error : new Error("MODEL_EXECUTION_FAILED"));
    } finally {
      if (timer) clearTimeout(timer);
      item.req.signal?.removeEventListener("abort", abort);
      this.ids.delete(item.req.taskId);
      this.running = 0;
      this.requestPump();
    }
  }
  /** Reject queued requests; an active request is allowed to settle. */
  close(): void {
    this.closed = true;
    for (const queue of Object.values(this.lanes)) {
      for (const item of queue.splice(0)) {
        item.detachAbort?.(); this.ids.delete(item.req.taskId);
        this.notify("CANCELLED", item, {errorCode: "ABORTED"});
        item.reject(new Error("SCHEDULER_CLOSED"));
      }
    }
  }
}
