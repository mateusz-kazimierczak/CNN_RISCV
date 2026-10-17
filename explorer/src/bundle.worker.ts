import { readBundle } from "./bundle";
let files: Record<string, Uint8Array> = {};
self.onmessage = async ({ data }) => {
  try {
    if (data.type === "load") {
      const result = await readBundle(new Uint8Array(data.bytes));
      files = result.files;
      self.postMessage({
        id: data.id,
        type: "loaded",
        evidence: result.evidence,
      });
    } else if (data.type === "text") {
      if (!Object.hasOwn(files, data.path))
        throw new Error("Missing bundle text");
      self.postMessage({
        id: data.id,
        type: "text",
        text: new TextDecoder().decode(files[data.path]),
      });
    }
  } catch (error) {
    self.postMessage({
      id: data.id,
      type: "error",
      error: error instanceof Error ? error.message : String(error),
    });
  }
};
