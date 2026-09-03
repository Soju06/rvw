export const REVIEW_ARTIFACT_NAMES = [
  "report.md",
  "discover.json",
  "merge.json",
  "outcome.json",
  "run.log",
] as const;

export type ReviewArtifactName = (typeof REVIEW_ARTIFACT_NAMES)[number];

export function artifactKey(jobId: string, name: ReviewArtifactName): string {
  return `jobs/${jobId}/${name}`;
}

export function artifactPath(name: ReviewArtifactName): string {
  return `/workspace/result/${name}`;
}
