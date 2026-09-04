import {DurableObject} from "cloudflare:workers";
import type {Process} from "@cloudflare/sandbox";

import {
  REVIEW_RESULT_ARTIFACT_NAMES,
  artifactKey,
  artifactPath,
  type ReviewArtifactName,
} from "./artifacts";
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
  summarizeArtifacts,
  type ArtifactSummary,
  type CheckConclusion,
  type JobState,
  type ReviewResultMapping,
} from "./review-job-contract";
import {
  combinedProcessLog,
  missingArtifactDiagnostics,
  processFacts,
  processJson,
  type CapturedProcessLogs,
  type ProcessFacts,
} from "./review-job-observability";
import {
  buildGitCloneUrl,
  buildReviewProcessEnv,
  buildRvwAutoInvocation,
} from "./sandbox-auth";
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

function reviewScript(message: ReviewJobMessage): string {
  const cloneUrl = buildGitCloneUrl(message.owner, message.repo);
  return String.raw`#!/usr/bin/env bash
set -euo pipefail
RESULT=/workspace/result
TARGET=/workspace/target
ADJ=/workspace/adjudication
OUT=/tmp/rvw
mkdir -p "$RESULT" /root/.config/gh
exec > >(tee -a "$RESULT/run.log") 2> >(tee -a "$RESULT/run.log" >&2)
cat > /root/.config/gh/hosts.yml <<'RVW_GH_CONFIG'
github.com:
    user: x-access-token
    oauth_token: placeholder-not-a-secret
    git_protocol: https
RVW_GH_CONFIG
chmod 0600 /root/.config/gh/hosts.yml
unset GH_TOKEN GITHUB_TOKEN RVW_CODEX_DEFAULT_BASE_URL RVW_CODEX_SANDBOX
printenv | LC_ALL=C sort | sed -E '/(bearer|token|key=)/I s/=.*/=[REDACTED]/' > "$RESULT/environment.txt"
git clone --no-checkout '${cloneUrl}' "$TARGET"
git -C "$TARGET" fetch --no-tags origin 'refs/pull/${message.prNumber}/head' '${message.baseSha}'
git -C "$TARGET" checkout --detach '${message.headSha}'
git clone --no-checkout '${cloneUrl}' "$ADJ"
git -C "$ADJ" fetch --no-tags origin 'refs/pull/${message.prNumber}/head' '${message.baseSha}'
git -C "$ADJ" checkout --detach '${message.headSha}'
cd "$TARGET"
set +e
${buildRvwAutoInvocation(message.owner, message.repo, message.prNumber)} > "$RESULT/rvw-auto.json"
review_rc=$?
python - "$RESULT/rvw-auto.json" "$OUT" "$RESULT" <<'PY'
import json
import pathlib
import re
import shutil
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
run_id = payload.get("run_id")
if not isinstance(run_id, str) or re.fullmatch(r"[A-Za-z0-9._-]+", run_id) is None:
    raise SystemExit("rvw auto output has no safe run_id")
run_dir = pathlib.Path(sys.argv[2]) / run_id
result = pathlib.Path(sys.argv[3])
for name in ("report.md", "discover.json", "merge.json", "outcome.json"):
    source = run_dir / name
    if source.is_file():
        shutil.copyfile(source, result / name)
PY
copy_rc=$?
set -e
printf '%s\n' "$review_rc" > "$RESULT/process-exit-code"
printf 'rvw_artifact_copy_exit=%s\n' "$copy_rc"
exit "$review_rc"
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
  processDiagnostics?: string,
): string {
  const lines = [mapping.reason];
  if (summary !== null) {
    lines.push(
      `Lanes: ${summary.lanesValid}/${summary.lanesDispatched} valid; uncovered: ${summary.uncovered}.`,
      `Findings: ${summary.findings} (${Object.entries(summary.findingsBySeverity)
        .map(([name, count]) => `${name}=${count}`)
        .join(", ") || "none"}).`,
      `Verdicts: ${Object.entries(summary.verdicts)
        .map(([name, count]) => `${name}=${count}`)
        .join(", ") || "none"}.`,
    );
  }
  if (processDiagnostics !== undefined) lines.push(processDiagnostics);
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
    name: ReviewArtifactName,
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
    name: ReviewArtifactName,
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

  private async persistTerminalDiagnostics(
    record: JobRecord,
    process: Process | null,
    exitCode: number | null,
  ): Promise<{record: JobRecord; facts: ProcessFacts; stderr: string}> {
    if (record.sandboxId === undefined) {
      const facts = processFacts(
        {command: record.processCommand ?? "/workspace/run-review.sh", exitCode},
        Date.now(),
      );
      return {record, facts, stderr: ""};
    }
    const sandbox = sandboxFor(this.env, record.sandboxId);
    const observedAt = Date.now();
    const startedAt =
      process?.startTime ??
      (record.processStartedAt === undefined ? undefined : new Date(record.processStartedAt));
    const facts = processFacts(
      {
        command: process?.command ?? record.processCommand ?? "/workspace/run-review.sh",
        exitCode: process?.exitCode ?? exitCode,
        startTime: startedAt,
        endTime: process?.endTime,
      },
      observedAt,
    );
    let logs: CapturedProcessLogs | null = null;
    if (record.processId !== undefined) {
      try {
        logs = await sandbox.getProcessLogs(record.processId);
      } catch (error) {
        console.error(
          JSON.stringify({
            event: "review_job_process_logs_unavailable",
            jobId: record.jobId,
            error: errorMessage(error),
          }),
        );
      }
    }

    const additions: ArtifactMetadata[] = [];
    const processArtifact = await this.putArtifactBestEffort(
      record,
      "process.json",
      processJson(facts),
    );
    if (processArtifact !== null) additions.push(processArtifact);

    const runLog =
      logs === null
        ? await optionalFile(sandbox, artifactPath("run.log"))
        : combinedProcessLog(logs);
    if (runLog !== null) {
      const runArtifact = await this.putArtifactBestEffort(record, "run.log", runLog);
      if (runArtifact !== null) additions.push(runArtifact);
    }

    const environment = await optionalFile(sandbox, artifactPath("environment.txt"));
    if (environment !== null) {
      const environmentArtifact = await this.putArtifactBestEffort(
        record,
        "environment.txt",
        environment,
      );
      if (environmentArtifact !== null) additions.push(environmentArtifact);
    }

    const next = {
      ...record,
      artifacts: this.mergeArtifactMetadata(record.artifacts, additions),
      updatedAt: new Date().toISOString(),
    };
    await this.save(next);
    return {record: next, facts, stderr: logs?.stderr ?? ""};
  }

  private async persistArtifacts(record: JobRecord): Promise<ArtifactMetadata[]> {
    if (record.sandboxId === undefined) return [];
    const sandbox = sandboxFor(this.env, record.sandboxId);
    const artifacts: ArtifactMetadata[] = [];
    for (const name of REVIEW_RESULT_ARTIFACT_NAMES) {
      let content: string;
      try {
        content = await readTextFile(sandbox, artifactPath(name));
      } catch (error) {
        console.log(
          JSON.stringify({
            event: "review_job_artifact_unavailable",
            jobId: record.jobId,
            artifact: name,
            error: errorMessage(error),
          }),
        );
        continue;
      }
      artifacts.push(await this.putArtifact(record, name, content));
    }
    return artifacts;
  }

  private async persistArtifactsBestEffort(record: JobRecord): Promise<JobRecord> {
    try {
      const artifacts = await this.persistArtifacts(record);
      const next = {
        ...record,
        artifacts: this.mergeArtifactMetadata(record.artifacts, artifacts),
        updatedAt: new Date().toISOString(),
      };
      await this.save(next);
      return next;
    } catch (error) {
      console.error(
        JSON.stringify({
          event: "review_job_terminal_artifact_failure",
          jobId: record.jobId,
          error: errorMessage(error),
        }),
      );
      return record;
    }
  }

  private async finishPublishing(
    record: JobRecord,
    process: Process | null,
    exitCode: number | null,
    resultOutput: string,
    config: RequiredConfig,
    overrideReason?: string,
  ): Promise<void> {
    if (record.message === undefined || record.checkRunId === undefined) {
      throw new Error("publishing job is missing GitHub metadata");
    }
    const message = record.message;
    const checkRunId = record.checkRunId;
    const sandbox = sandboxFor(this.env, record.sandboxId ?? "missing");
    const diagnostics = await this.persistTerminalDiagnostics(record, process, exitCode);
    record = diagnostics.record;
    const [discoverJson, outcomeJson] = await Promise.all([
      optionalFile(sandbox, artifactPath("discover.json")),
      optionalFile(sandbox, artifactPath("outcome.json")),
    ]);
    let mapping = checkConclusionForResult(exitCode, resultOutput);
    if (overrideReason !== undefined) {
      mapping = {terminalState: "failed", conclusion: "neutral", reason: overrideReason};
    }
    let summary: ArtifactSummary | null = null;
    let processSummary: string | undefined;
    try {
      if (discoverJson === null || outcomeJson === null) {
        processSummary = missingArtifactDiagnostics(diagnostics.facts, diagnostics.stderr);
        throw new Error("required result artifact is missing");
      }
      summary = summarizeArtifacts(discoverJson, outcomeJson);
    } catch (error) {
      mapping = {
        terminalState: "failed",
        conclusion: "neutral",
        reason: `review artifacts were missing or unparseable: ${errorMessage(error)}`,
      };
    }
    const artifacts = await this.persistArtifacts(record);
    record = {
      ...record,
      artifacts: this.mergeArtifactMetadata(record.artifacts, artifacts),
      updatedAt: new Date().toISOString(),
    };
    await this.save(record);
    const token = await this.token(record, config.githubAppId);
    await updateCheckRun(token, {
      owner: message.owner,
      repo: message.repo,
      checkRunId,
      conclusion: mapping.conclusion,
      title: titleFor(mapping),
      summary: summaryText(record.jobId, mapping, summary, processSummary),
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
    record = await this.persistArtifactsBestEffort(record);
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
        const resultOutput = (await optionalFile(sandbox, "/workspace/result/rvw-auto.json")) ?? "";
        const exitText = await optionalFile(sandbox, "/workspace/result/process-exit-code");
        const recordedExitCode = exitText === null ? null : Number.parseInt(exitText.trim(), 10);
        const exitCode = process?.exitCode ?? recordedExitCode;
        await this.finishPublishing(
          record,
          process,
          Number.isNaN(exitCode) ? null : exitCode,
          resultOutput,
          config,
        );
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
          "",
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
      const resultOutput = (await optionalFile(sandbox, "/workspace/result/rvw-auto.json")) ?? "";
      await this.finishPublishing(
        record,
        process,
        process.exitCode ?? null,
        resultOutput,
        config,
      );
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
