export interface TextFileReader {
  readFile(
    path: string,
    options: {encoding: "utf8"},
  ): Promise<{content: unknown}>;
}

export async function readTextFile(reader: TextFileReader, path: string): Promise<string> {
  const file = await reader.readFile(path, {encoding: "utf8"});
  if (typeof file.content !== "string") {
    throw new Error(`Sandbox text file did not return string content: ${path}`);
  }
  return file.content;
}

export async function optionalTextFile(
  reader: TextFileReader,
  path: string,
): Promise<string | null> {
  try {
    return await readTextFile(reader, path);
  } catch {
    return null;
  }
}
