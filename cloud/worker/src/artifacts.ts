export const REVIEW_RESULT_ARTIFACT_NAMES = [
  "report.md",
  "discover.json",
  "merge.json",
  "outcome.json",
] as const;

export const REVIEW_DIAGNOSTIC_ARTIFACT_NAMES = [
  "run.log",
  "process.json",
  "environment.txt",
] as const;

export const REVIEW_ARTIFACT_NAMES = [
  ...REVIEW_RESULT_ARTIFACT_NAMES,
  ...REVIEW_DIAGNOSTIC_ARTIFACT_NAMES,
] as const;

export type ReviewArtifactName = (typeof REVIEW_ARTIFACT_NAMES)[number];

export function artifactKey(jobId: string, name: ReviewArtifactName): string {
  return `jobs/${jobId}/${name}`;
}

export function artifactPath(name: ReviewArtifactName): string {
  return `/workspace/result/${name}`;
}
