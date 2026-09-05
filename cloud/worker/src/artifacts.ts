export interface ArtifactEntry {
  path: string;
  size_bytes: number;
}

export function safeArtifactName(name: string): string {
  if (!name || name.startsWith("/") || name.includes("\\") ||
      name.split("/").some((part) => part === ".." || part === "." || part === "")) {
    throw new Error("artifact path must be relative to the result directory");
  }
  return name;
}

export function artifactManifest(processJson: string): ArtifactEntry[] {
  const value: unknown = JSON.parse(processJson);
  if (typeof value !== "object" || value === null ||
      !("schema_version" in value) || value.schema_version !== 1 ||
      !("artifacts" in value) || !Array.isArray(value.artifacts)) {
    throw new Error("process artifact manifest is missing or unsupported");
  }
  const seen = new Set<string>();
  return value.artifacts.map((entry: unknown) => {
    if (typeof entry !== "object" || entry === null ||
        !("path" in entry) || typeof entry.path !== "string" ||
        !("size_bytes" in entry) || typeof entry.size_bytes !== "number" ||
        !Number.isSafeInteger(entry.size_bytes) || entry.size_bytes < 0) {
      throw new Error("process artifact manifest entry is invalid");
    }
    if (Object.keys(entry).some((key) => key !== "path" && key !== "size_bytes")) {
      throw new Error("process artifact manifest entry has unsupported fields");
    }
    const path = safeArtifactName(entry.path);
    if (seen.has(path)) throw new Error("process artifact manifest repeats a path");
    seen.add(path);
    return {path, size_bytes: entry.size_bytes};
  });
}

export function artifactKey(jobId: string, name: string): string {
  return `jobs/${jobId}/${safeArtifactName(name)}`;
}

export function artifactPath(name: string): string {
  return `/workspace/result/${safeArtifactName(name)}`;
}
