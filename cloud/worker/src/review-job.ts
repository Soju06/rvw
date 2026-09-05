import {DurableObject} from "cloudflare:workers";
import type {Process} from "@cloudflare/sandbox";

import {artifactKey, artifactPath, artifactManifest} from "./artifacts";
import {requiredConfig, type RequiredConfig} from "./config";
import {
  clearInstallationToken,
  createCheckRun,
  getInstallationToken,
  updateCheckRun,
  type CreatedCheckRun,
} from "./github-app";
import {
  canTransition,
  checkConclusionForResult,
  deadlineMinutes,
  isDeadlineReached,
  isTerminalState,
  shouldRestartForRerequest,
  parseArtifactSummary,
  type ArtifactSummary,
  type CheckConclusion,
  type JobState,
  type ReviewResultMapping,
} from "./review-job-contract";
import {buildReviewProcessEnv, buildRvwRunInvocation, shellQuote} from "./sandbox-auth";
import {configureOutbound, optionalFile, readTextFile, sandboxFor} from "./sandbox";
import {validateReviewJobMessage, type ReviewJobMessage} from "./webhook";

const JOB_STORAGE_KEY = "job";
const POLL_INTERVAL_MS = 30_000;

interface ArtifactMetadata {
  name: string;
  key: string;
  size: number;
  etag: string;
  uploadedAt: string;
}

interface JobRecord {
  schemaVersion: 1;
  jobId: string;
  state: JobState;
  message?: ReviewJobMessage;
  createdAt: string;
  updatedAt: string;
  deadlineAt?: string;
  sandboxId?: string;
  processId?: string;
  processCommand?: string;
  processStartedAt?: string;
  checkRunId?: number;
  checkRunUrl?: string;
  conclusion?: CheckConclusion;
  reason?: string;
  checkUpdatePending?: boolean;
  cleanupPending?: boolean;
  diagnosticsFinalized?: boolean;
  artifactContractInvalid?: boolean;
  artifacts: ArtifactMetadata[];
}

export interface JobStatus {
  jobId: string;
  state: JobState;
  event?: string;
  createdAt: string;
  updatedAt: string;
  deadlineAt?: string;
  sandboxId?: string;
  processId?: string;
  checkRunId?: number;
  checkRunUrl?: string;
  conclusion?: CheckConclusion;
  reason?: string;
  checkUpdatePending?: boolean;
  cleanupPending?: boolean;
  artifacts: ArtifactMetadata[];
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function initializeInvocation(message: ReviewJobMessage): string {
  return "python -m rvw.store initialize --out /workspace/result " +
    `--target ${shellQuote(`https://github.com/${message.owner}/${message.repo}/pull/${message.prNumber}`)} ` +
    `--base-ref ${shellQuote(message.baseSha)} --head-ref ${shellQuote(message.headSha)}`;
}

export function reviewScript(message: ReviewJobMessage): string {
  return String.raw`#!/usr/bin/env bash
set -euo pipefail
mkdir -p /workspace/result /root/.config/gh
${initializeInvocation(message)}
cat > /root/.config/gh/hosts.yml <<'RVW_GH_CONFIG'
github.com:
    user: x-access-token
    oauth_token: placeholder-not-a-secret
    git_protocol: https
RVW_GH_CONFIG
chmod 0600 /root/.config/gh/hosts.yml
unset GH_TOKEN GITHUB_TOKEN RVW_CODEX_DEFAULT_BASE_URL RVW_CODEX_SANDBOX
exec ${buildRvwRunInvocation(message)}
`;
}

function statusView(record: JobRecord): JobStatus {
  return {
    jobId: record.jobId,
    state: record.state,
    ...(record.message === undefined ? {} : {event: record.message.event}),
    createdAt: record.createdAt,
    updatedAt: record.updatedAt,
    ...(record.deadlineAt === undefined ? {} : {deadlineAt: record.deadlineAt}),
    ...(record.sandboxId === undefined ? {} : {sandboxId: record.sandboxId}),
    ...(record.processId === undefined ? {} : {processId: record.processId}),
    ...(record.checkRunId === undefined ? {} : {checkRunId: record.checkRunId}),
    ...(record.checkRunUrl === undefined ? {} : {checkRunUrl: record.checkRunUrl}),
    ...(record.conclusion === undefined ? {} : {conclusion: record.conclusion}),
    ...(record.reason === undefined ? {} : {reason: record.reason}),
    ...(record.checkUpdatePending === undefined
      ? {}
      : {checkUpdatePending: record.checkUpdatePending}),
    ...(record.cleanupPending === undefined ? {} : {cleanupPending: record.cleanupPending}),
    artifacts: record.artifacts,
  };
}

function titleFor(mapping: ReviewResultMapping): string {
  if (mapping.conclusion === "success") return "rvw review passed";
  if (mapping.conclusion === "failure") return "rvw review found blockers";
  return "rvw review could not complete";
}

function summaryText(
  jobId: string,
  mapping: ReviewResultMapping,
  summary: ArtifactSummary | null,
): string {
  const lines = [mapping.reason];
  if (summary !== null) lines.push(summary.markdown);
  lines.push(`Artifacts: job ${jobId}`);
  return lines.join("\n\n");
}

export class RvwReviewJob extends DurableObject<Env> {
  private async load(): Promise<JobRecord | undefined> {
    return await this.ctx.storage.get<JobRecord>(JOB_STORAGE_KEY);
  }

  private async save(record: JobRecord): Promise<void> {
    await this.ctx.storage.put(JOB_STORAGE_KEY, record);
  }

  private async transition(
    record: JobRecord,
    state: JobState,
    reason?: string,
  ): Promise<JobRecord> {
    if (!canTransition(record.state, state)) {
      throw new Error(`invalid review job transition ${record.state} -> ${state}`);
    }
    const previous = record.state;
    const next: JobRecord = {
      ...record,
      state,
      updatedAt: new Date().toISOString(),
      ...(reason === undefined ? {} : {reason}),
    };
    await this.save(next);
    console.log(
      JSON.stringify({
        event: "review_job_state_transition",
        jobId: next.jobId,
        from: previous,
        to: state,
        at: next.updatedAt,
        ...(reason === undefined ? {} : {reason}),
      }),
    );
    return next;
  }

  private token(record: JobRecord, appId: string): Promise<string> {
    if (record.message === undefined) throw new Error("review job message is missing");
    return getInstallationToken({
      storage: this.ctx.storage,
      appId,
      privateKey: this.env.GITHUB_APP_PRIVATE_KEY,
      installationId: record.message.installationId,
      repoId: record.message.repoId,
    });
  }

  private async clearToken(record: JobRecord): Promise<void> {
    if (record.message === undefined) return;
    await clearInstallationToken(
      this.ctx.storage,
      record.message.installationId,
      record.message.repoId,
    );
  }

  async status(): Promise<JobStatus | null> {
    const record = await this.load();
    return record === undefined ? null : statusView(record);
  }

  async start(value: ReviewJobMessage): Promise<{started: boolean; state: JobState}> {
    const config = requiredConfig(this.env);
    const message = validateReviewJobMessage(value);
    let record = await this.load();
    if (record === undefined) {
      const now = new Date().toISOString();
      record = {
        schemaVersion: 1,
        jobId: message.jobId,
        state: "queued",
        message,
        createdAt: now,
        updatedAt: now,
        artifacts: [],
      };
      await this.save(record);
      console.log(
        JSON.stringify({
          event: "review_job_state_transition",
          jobId: record.jobId,
          from: null,
          to: "queued",
          at: now,
        }),
      );
    } else if (record.jobId !== message.jobId) {
      throw new Error("Durable Object job identity does not match its message");
    }

    if (
      shouldRestartForRerequest(
        record.state,
        record.message?.deliveryId,
        message.event,
        message.deliveryId,
      )
    ) {
      const previous = record.state;
      const now = new Date().toISOString();
      record = {
        schemaVersion: 1,
        jobId: message.jobId,
        state: "queued",
        message,
        createdAt: now,
        updatedAt: now,
        artifacts: [],
      };
      await this.save(record);
      console.log(
        JSON.stringify({
          event: "review_job_state_transition",
          jobId: record.jobId,
          from: previous,
          to: "queued",
          reason: "check_run.rerequested",
          at: now,
        }),
      );
    } else if (
      isTerminalState(record.state) ||
      record.state === "running" ||
      record.state === "publishing"
    ) {
      return {started: false, state: record.state};
    }
    if (record.message === undefined) record = {...record, message};
    if (record.state === "queued") record = await this.transition(record, "provisioning");

    const token = await this.token(record, config.githubAppId);
    let check: CreatedCheckRun | undefined;
    if (record.checkRunId === undefined) {
      check = await createCheckRun(token, {
        owner: message.owner,
        repo: message.repo,
        headSha: message.headSha,
        jobId: message.jobId,
      });
      record = {
        ...record,
        checkRunId: check.id,
        ...(check.htmlUrl === undefined ? {} : {checkRunUrl: check.htmlUrl}),
        updatedAt: new Date().toISOString(),
      };
      await this.save(record);
    }

    const sandboxId = record.sandboxId ?? `rvw-review-${crypto.randomUUID()}`;
    const sandbox = sandboxFor(this.env, sandboxId);
    if (record.sandboxId === undefined) {
      record = {...record, sandboxId, updatedAt: new Date().toISOString()};
      await this.save(record);
    }
    await sandbox.exec(initializeInvocation(message));
    await configureOutbound(sandbox, config.codexProxyHost, token);
    await sandbox.writeFile("/workspace/run-review.sh", reviewScript(message));
    await sandbox.exec("chmod 0755 /workspace/run-review.sh");
    const process = await sandbox.startProcess("/workspace/run-review.sh", {
      autoCleanup: false,
      env: buildReviewProcessEnv(config.codexProxyHost),
    });
    const deadlineAtMs =
      Date.now() + deadlineMinutes(this.env.RVW_JOB_DEADLINE_MINUTES) * 60 * 1_000;
    record = {
      ...record,
      sandboxId,
      processId: process.id,
      processCommand: process.command,
      processStartedAt: process.startTime.toISOString(),
      deadlineAt: new Date(deadlineAtMs).toISOString(),
      updatedAt: new Date().toISOString(),
    };
    await this.save(record);
    record = await this.transition(record, "running");
    await this.ctx.storage.setAlarm(Date.now() + POLL_INTERVAL_MS);
    return {started: true, state: record.state};
  }

  async failStart(value: ReviewJobMessage, reason: string): Promise<void> {
    const config = requiredConfig(this.env);
    const message = validateReviewJobMessage(value);
    let record = await this.load();
    if (record === undefined) {
      const now = new Date().toISOString();
      record = {
        schemaVersion: 1,
        jobId: message.jobId,
        state: "queued",
        message,
        createdAt: now,
        updatedAt: now,
        artifacts: [],
      };
      await this.save(record);
      console.log(
        JSON.stringify({
          event: "review_job_state_transition",
          jobId: record.jobId,
          from: null,
          to: "queued",
          at: now,
        }),
      );
      record = await this.transition(record, "provisioning");
    }
    if (record.state !== "queued" && record.state !== "provisioning") return;
    if (record.state === "queued") record = await this.transition(record, "provisioning");
    record = {
      ...record,
      conclusion: "neutral",
      checkUpdatePending: record.checkRunId !== undefined,
      cleanupPending: record.sandboxId !== undefined,
      updatedAt: new Date().toISOString(),
    };
    await this.save(record);
    record = await this.transition(record, "failed", reason);
    record = await this.settleCleanup(record);
    await this.settleNeutralCheck(record, reason, config.githubAppId);
  }

  async supersede(jobId: string, reason: string): Promise<void> {
    const config = requiredConfig(this.env);
    let record = await this.load();
    if (record === undefined) {
      const now = new Date().toISOString();
      record = {
        schemaVersion: 1,
        jobId,
        state: "superseded",
        createdAt: now,
        updatedAt: now,
        reason,
        conclusion: "neutral",
        checkUpdatePending: false,
        cleanupPending: false,
        artifacts: [],
      };
      await this.save(record);
      console.log(
        JSON.stringify({
          event: "review_job_state_transition",
          jobId,
          from: null,
          to: "superseded",
          at: now,
          reason,
        }),
      );
      return;
    }
    if (isTerminalState(record.state)) return;
    record = {
      ...record,
      conclusion: "neutral",
      checkUpdatePending: record.checkRunId !== undefined,
      cleanupPending: record.sandboxId !== undefined,
      updatedAt: new Date().toISOString(),
    };
    await this.save(record);
    record = await this.transition(record, "superseded", reason);
    record = await this.settleCleanup(record);
    await this.settleNeutralCheck(record, reason, config.githubAppId);
  }

  private async updateNeutralBestEffort(
    record: JobRecord,
    reason: string,
    appId: string,
  ): Promise<boolean> {
    if (record.message === undefined || record.checkRunId === undefined) return true;
    try {
      const token = await this.token(record, appId);
      await updateCheckRun(token, {
        owner: record.message.owner,
        repo: record.message.repo,
        checkRunId: record.checkRunId,
        conclusion: "neutral",
        title: "rvw review could not complete",
        summary: `${reason}\n\nArtifacts: job ${record.jobId}`,
      });
      return true;
    } catch (error) {
      console.error(
        JSON.stringify({
          event: "review_job_check_update_failure",
          jobId: record.jobId,
          error: errorMessage(error),
        }),
      );
      return false;
    }
  }

  private async settleNeutralCheck(
    record: JobRecord,
    reason: string,
    appId: string,
  ): Promise<JobRecord> {
    const updated = await this.updateNeutralBestEffort(record, reason, appId);
    record = {
      ...record,
      conclusion: "neutral",
      checkUpdatePending: !updated,
      updatedAt: new Date().toISOString(),
    };
    await this.save(record);
    if (updated) {
      await this.clearToken(record);
    } else {
      await this.ctx.storage.setAlarm(Date.now() + POLL_INTERVAL_MS);
    }
    return record;
  }

  private async destroyBestEffort(record: JobRecord): Promise<boolean> {
    if (record.sandboxId === undefined) return true;
    const sandbox = sandboxFor(this.env, record.sandboxId);
    try {
      if (record.processId !== undefined) await sandbox.killProcess(record.processId, "SIGTERM");
    } catch (error) {
      console.error(
        JSON.stringify({
          event: "review_job_process_kill_failure",
          jobId: record.jobId,
          error: errorMessage(error),
        }),
      );
    }
    try {
      await sandbox.removeOutboundByHost("api.github.com");
      await sandbox.removeOutboundByHost("github.com");
    } catch (error) {
      console.error(
        JSON.stringify({
          event: "review_job_egress_cleanup_failure",
          jobId: record.jobId,
          error: errorMessage(error),
        }),
      );
    }
    try {
      await sandbox.destroy();
      return true;
    } catch (error) {
      console.error(
        JSON.stringify({
          event: "review_job_sandbox_destroy_failure",
          jobId: record.jobId,
          error: errorMessage(error),
        }),
      );
      return false;
    }
  }

  private async settleCleanup(record: JobRecord): Promise<JobRecord> {
    record = await this.persistTerminalDiagnostics(record);
    const destroyed = await this.destroyBestEffort(record);
    const next = {
      ...record,
      cleanupPending: !destroyed,
      updatedAt: new Date().toISOString(),
    };
    await this.save(next);
    if (!destroyed) await this.ctx.storage.setAlarm(Date.now() + POLL_INTERVAL_MS);
    return next;
  }

  private async putArtifact(
    record: JobRecord,
    name: string,
    content: string,
  ): Promise<ArtifactMetadata> {
    const stored = await this.env.RVW_ARTIFACTS.put(
      artifactKey(record.jobId, name),
      content,
      {
        httpMetadata: {
          contentType: name.endsWith(".json")
            ? "application/json"
            : name.endsWith(".md")
              ? "text/markdown; charset=utf-8"
              : "text/plain; charset=utf-8",
        },
      },
    );
    return {
      name,
      key: stored.key,
      size: stored.size,
      etag: stored.etag,
      uploadedAt: stored.uploaded.toISOString(),
    };
  }

  private async putArtifactBestEffort(
    record: JobRecord,
    name: string,
    content: string,
  ): Promise<ArtifactMetadata | null> {
    try {
      return await this.putArtifact(record, name, content);
    } catch (error) {
      console.error(
        JSON.stringify({
          event: "review_job_diagnostic_persistence_failure",
          jobId: record.jobId,
          artifact: name,
          error: errorMessage(error),
        }),
      );
      return null;
    }
  }

  private mergeArtifactMetadata(
    current: ArtifactMetadata[],
    additions: ArtifactMetadata[],
  ): ArtifactMetadata[] {
    const merged = new Map(current.map((artifact) => [artifact.name, artifact]));
    for (const artifact of additions) merged.set(artifact.name, artifact);
    return [...merged.values()];
  }

  /** Every terminal route reaches this before destruction, including failed starts. */
  private async persistTerminalDiagnostics(
    record: JobRecord,
    process: Process | null = null,
    forcedFailure?: {code: string; detail: string},
  ): Promise<JobRecord> {
    if (record.sandboxId === undefined) return record;
    if (record.diagnosticsFinalized) return await this.persistArtifactsBestEffort(record);
    const sandbox = sandboxFor(this.env, record.sandboxId);
    // Pinned SDK killProcess discards its signal argument and result; do not infer a signal.
    const signal: string | null = null;
    let canFinalize = true;
    const forced = forcedFailure ?? (
      record.state === "timed_out" || record.state === "superseded" || record.state === "failed"
        ? {code: record.state === "failed" ? "start_failed" : record.state,
          detail: record.reason ?? record.state} : undefined
    );
    if (process === null && record.processId !== undefined) {
      try { process = await sandbox.getProcess(record.processId); } catch { /* SDK observation only. */ }
    }
    if (forced !== undefined && record.processId !== undefined &&
        (process === null || process.status === "running" || process.status === "starting")) {
      try {
        await sandbox.killProcess(record.processId, "SIGTERM");
        for (let attempt = 0; attempt < 5; attempt += 1) {
          const observed = await sandbox.getProcess(record.processId);
          if (observed === null || !["running", "starting"].includes(observed.status)) {
            process = observed;
            break;
          }
          if (attempt === 4) throw new Error("Sandbox process remained active after termination request");
          await new Promise((resolve) => setTimeout(resolve, 100));
        }
      } catch (error) {
        canFinalize = false;
        console.error(JSON.stringify({event: "review_job_process_kill_failure",
          jobId: record.jobId, error: errorMessage(error)}));
      }
    }
    const started = process?.startTime?.getTime() ??
      (record.processStartedAt === undefined ? Date.now() : Date.parse(record.processStartedAt));
    const observations = {
      exit_code: process?.exitCode ?? null,
      signal,
      duration_ms: Math.max(0, (process?.endTime?.getTime() ?? Date.now()) - started),
      command: process?.command ?? record.processCommand ?? null,
    };
    try {
      if (!canFinalize) throw new Error("terminal finalization deferred because the review may still be writing");
      if (await optionalFile(sandbox, artifactPath("process.json")) === null && record.message !== undefined) {
        await sandbox.exec(initializeInvocation(record.message));
      }
      const finalize = "python -m rvw.store finalize --out /workspace/result " +
        `--sdk-observations-json ${shellQuote(JSON.stringify(observations))}` +
        (forced === undefined ? "" : ` --failure-code ${shellQuote(forced.code)} --failure-detail ${shellQuote(forced.detail)}`);
      const result = await sandbox.exec(finalize);
      if (!result.success) throw new Error("Python terminal contract finalization failed");
      record = {...record, diagnosticsFinalized: true};
    } catch (error) {
      console.error(JSON.stringify({event: "review_job_diagnostic_finalization_failure",
        jobId: record.jobId, error: errorMessage(error)}));
    }
    return await this.persistArtifactsBestEffort(record);
  }

  private async persistArtifactsBestEffort(record: JobRecord): Promise<JobRecord> {
    if (record.sandboxId === undefined) return record;
    const sandbox = sandboxFor(this.env, record.sandboxId);
    const additions: ArtifactMetadata[] = [];
    const contents = new Map<string, string>();
    const persist = async (name: string): Promise<void> => {
      try {
        const content = await readTextFile(sandbox, artifactPath(name));
        contents.set(name, content);
        const artifact = await this.putArtifactBestEffort(record, name, content);
        if (artifact !== null) additions.push(artifact);
      } catch (error) {
        console.error(JSON.stringify({event: "review_job_artifact_unavailable",
          jobId: record.jobId, artifact: name, error: errorMessage(error)}));
      }
    };
    // These are required bootstrap diagnostics. Read each independently even when
    // process.json cannot be read or parsed; stage/runtime names come from its manifest.
    await persist("run.log");
    await persist("process.json");
    await persist("environment.txt");
    let invalid = false;
    try {
      const processJson = contents.get("process.json");
      if (processJson === undefined) throw new Error("process.json unavailable");
      const manifest = artifactManifest(processJson);
      for (const name of contents.keys()) {
        if (!manifest.some((entry) => entry.path === name)) {
          invalid = true;
          console.error(JSON.stringify({event: "review_job_artifact_manifest_missing_entry",
            jobId: record.jobId, artifact: name}));
        }
      }
      for (const entry of manifest) {
        if (!contents.has(entry.path)) await persist(entry.path);
        const content = contents.get(entry.path);
        if (content === undefined) invalid = true;
        if (content !== undefined && new TextEncoder().encode(content).length !== entry.size_bytes) {
          invalid = true;
          console.error(JSON.stringify({event: "review_job_artifact_size_mismatch",
            jobId: record.jobId, artifact: entry.path, expected: entry.size_bytes,
            actual: new TextEncoder().encode(content).length}));
        }
      }
    } catch (error) {
      invalid = true;
      console.error(JSON.stringify({event: "review_job_terminal_artifact_failure",
        jobId: record.jobId, error: errorMessage(error)}));
    }
    const next = {...record, artifacts: this.mergeArtifactMetadata(record.artifacts, additions),
      artifactContractInvalid: invalid, updatedAt: new Date().toISOString()};
    await this.save(next);
    return next;
  }

  private async finishPublishing(
    record: JobRecord,
    process: Process | null,
    exitCode: number | null,
    config: RequiredConfig,
    overrideReason?: string,
  ): Promise<void> {
    if (record.message === undefined || record.checkRunId === undefined) {
      throw new Error("publishing job is missing GitHub metadata");
    }
    const message = record.message;
    const checkRunId = record.checkRunId;
    const sandbox = sandboxFor(this.env, record.sandboxId ?? "missing");
    record = await this.persistTerminalDiagnostics(record, process,
      overrideReason === undefined ? undefined : {code: "process_disappeared", detail: overrideReason});
    const [processJson, summaryJson] = await Promise.all([
      optionalFile(sandbox, artifactPath("process.json")),
      optionalFile(sandbox, artifactPath("summary.json")),
    ]);
    let mapping = checkConclusionForResult(exitCode, processJson ?? "");
    if (record.artifactContractInvalid) {
      mapping = {terminalState: "failed", conclusion: "neutral", reason: "review artifact manifest was invalid or inconsistent"};
    }
    if (overrideReason !== undefined) {
      mapping = {terminalState: "failed", conclusion: "neutral", reason: overrideReason};
    }
    let summary: ArtifactSummary | null = null;
    try {
      if (summaryJson === null) throw new Error("summary.json is missing");
      summary = parseArtifactSummary(summaryJson);
    } catch (error) {
      if (mapping.terminalState === "completed") {
        mapping = {terminalState: "failed", conclusion: "neutral",
          reason: `review summary was invalid: ${errorMessage(error)}`};
      }
    }
    const token = await this.token(record, config.githubAppId);
    await updateCheckRun(token, {
      owner: message.owner,
      repo: message.repo,
      checkRunId,
      conclusion: mapping.conclusion,
      title: titleFor(mapping),
      summary: summaryText(record.jobId, mapping, summary),
    });
    record = {
      ...record,
      conclusion: mapping.conclusion,
      cleanupPending: record.sandboxId !== undefined,
      updatedAt: new Date().toISOString(),
    };
    await this.save(record);
    record = await this.transition(record, mapping.terminalState, mapping.reason);
    await this.settleCleanup(record);
    await this.clearToken(record);
  }

  private async timeOut(record: JobRecord, config: RequiredConfig): Promise<void> {
    const minutes = deadlineMinutes(this.env.RVW_JOB_DEADLINE_MINUTES);
    const reason = `rvw review exceeded the ${minutes}-minute hard deadline`;
    record = {
      ...record,
      conclusion: "neutral",
      checkUpdatePending: record.checkRunId !== undefined,
      cleanupPending: record.sandboxId !== undefined,
      updatedAt: new Date().toISOString(),
    };
    await this.save(record);
    record = await this.transition(record, "timed_out", reason);
    record = await this.settleCleanup(record);
    await this.settleNeutralCheck(record, reason, config.githubAppId);
  }

  async alarm(): Promise<void> {
    const config = requiredConfig(this.env);
    let record = await this.load();
    if (record === undefined) return;
    if (isTerminalState(record.state)) {
      if (record.cleanupPending === true) record = await this.settleCleanup(record);
      if (record.checkUpdatePending === true) {
        await this.settleNeutralCheck(
          record,
          record.reason ?? "rvw review ended without a publishable result",
          config.githubAppId,
        );
      }
      return;
    }
    try {
      const deadlineAtMs = record.deadlineAt === undefined ? Number.POSITIVE_INFINITY : Date.parse(record.deadlineAt);
      if (isDeadlineReached(Date.now(), deadlineAtMs)) {
        await this.timeOut(record, config);
        return;
      }
      if (record.state === "publishing") {
        const sandbox = sandboxFor(this.env, record.sandboxId ?? "missing");
        const process =
          record.processId === undefined ? null : await sandbox.getProcess(record.processId);
        await this.finishPublishing(record, process, process?.exitCode ?? null, config);
        return;
      }
      if (record.state !== "running" || record.sandboxId === undefined || record.processId === undefined) {
        throw new Error("active review job is missing Sandbox process metadata");
      }
      const token = await this.token(record, config.githubAppId);
      const sandbox = sandboxFor(this.env, record.sandboxId);
      await configureOutbound(sandbox, config.codexProxyHost, token);
      const process = await sandbox.getProcess(record.processId);
      if (process === null) {
        record = await this.transition(record, "publishing", "Sandbox process record disappeared");
        await this.finishPublishing(
          record,
          null,
          null,
          config,
          "Sandbox process record disappeared",
        );
        return;
      }
      if (process.status === "starting" || process.status === "running") {
        await this.ctx.storage.setAlarm(Date.now() + POLL_INTERVAL_MS);
        return;
      }
      record = await this.transition(record, "publishing");
      await this.finishPublishing(record, process, process.exitCode ?? null, config);
    } catch (error) {
      console.error(
        JSON.stringify({
          event: "review_job_alarm_failure",
          jobId: record.jobId,
          state: record.state,
          error: errorMessage(error),
        }),
      );
      await this.ctx.storage.setAlarm(Date.now() + POLL_INTERVAL_MS);
    }
  }
}
