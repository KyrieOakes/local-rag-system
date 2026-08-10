const SUPPORTED_EXTENSIONS = new Set([
  ".pdf",
  ".txt",
  ".md",
  ".markdown",
  ".docx",
]);

const SYSTEM_FILENAMES = new Set([".ds_store", "thumbs.db", "desktop.ini"]);

function normalizeClientRelativePath(path, fallbackName = "") {
  const normalized = String(path || fallbackName)
    .normalize("NFC")
    .replaceAll("\\", "/");
  const segments = normalized.split("/");
  if (
    !normalized ||
    normalized.startsWith("/") ||
    segments.some((segment) => !segment || segment === "." || segment === "..")
  ) {
    return null;
  }
  return segments.join("/");
}

function extensionOf(path) {
  const basename = path.slice(path.lastIndexOf("/") + 1);
  const dotIndex = basename.lastIndexOf(".");
  return dotIndex >= 0 ? basename.slice(dotIndex).toLowerCase() : "";
}

export function prepareUploadEntries(entries, existingEntries = []) {
  const accepted = [];
  const skipped = [];
  const knownPaths = new Set(
    existingEntries.map((entry) => entry.relativePath.normalize("NFC")),
  );

  for (const entry of entries) {
    const relativePath = normalizeClientRelativePath(
      entry.relativePath,
      entry.file?.name,
    );
    const displayPath = relativePath || entry.relativePath || entry.file?.name || "Unknown file";
    if (!entry.file || !relativePath) {
      skipped.push({ relativePath: displayPath, reason: "Unsafe or invalid path" });
      continue;
    }

    const basename = relativePath.slice(relativePath.lastIndexOf("/") + 1);
    if (SYSTEM_FILENAMES.has(basename.toLowerCase())) {
      skipped.push({ relativePath, reason: "System file" });
      continue;
    }

    const extension = extensionOf(relativePath);
    if (!SUPPORTED_EXTENSIONS.has(extension)) {
      skipped.push({
        relativePath,
        reason: extension ? `Unsupported type ${extension}` : "Missing file extension",
      });
      continue;
    }

    if (knownPaths.has(relativePath)) {
      skipped.push({ relativePath, reason: "Duplicate relative path" });
      continue;
    }

    knownPaths.add(relativePath);
    accepted.push({ file: entry.file, relativePath });
  }

  return { accepted, skipped };
}

export function collectInputEntries(fileList) {
  return Array.from(fileList || []).map((file) => ({
    file,
    relativePath: file.webkitRelativePath || file.name,
  }));
}

async function walkFileSystemHandle(handle, parentPath, entries) {
  const relativePath = parentPath ? `${parentPath}/${handle.name}` : handle.name;
  if (handle.kind === "file") {
    entries.push({ file: await handle.getFile(), relativePath });
    return;
  }

  for await (const childHandle of handle.values()) {
    await walkFileSystemHandle(childHandle, relativePath, entries);
  }
}

function fileFromEntry(entry) {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

function readEntryBatch(reader) {
  return new Promise((resolve, reject) => reader.readEntries(resolve, reject));
}

async function readAllDirectoryEntries(directoryEntry) {
  const reader = directoryEntry.createReader();
  const entries = [];
  while (true) {
    const batch = await readEntryBatch(reader);
    if (batch.length === 0) break;
    entries.push(...batch);
  }
  return entries;
}

async function walkWebkitEntry(entry, parentPath, entries) {
  const relativePath = parentPath ? `${parentPath}/${entry.name}` : entry.name;
  if (entry.isFile) {
    entries.push({ file: await fileFromEntry(entry), relativePath });
    return;
  }
  if (!entry.isDirectory) return;

  const children = await readAllDirectoryEntries(entry);
  for (const child of children) {
    await walkWebkitEntry(child, relativePath, entries);
  }
}

export async function collectDroppedEntries(dataTransfer) {
  const entries = [];
  const items = Array.from(dataTransfer?.items || []).filter(
    (item) => item.kind === "file",
  );

  for (const item of items) {
    let handled = false;

    if (typeof item.getAsFileSystemHandle === "function") {
      try {
        const handle = await item.getAsFileSystemHandle();
        if (handle) {
          await walkFileSystemHandle(handle, "", entries);
          handled = true;
        }
      } catch {
        // The WebKit entry fallback below covers browsers without permission.
      }
    }

    if (!handled && typeof item.webkitGetAsEntry === "function") {
      const entry = item.webkitGetAsEntry();
      if (entry) {
        await walkWebkitEntry(entry, "", entries);
        handled = true;
      }
    }

    if (!handled) {
      const file = item.getAsFile();
      if (file) entries.push({ file, relativePath: file.name });
    }
  }

  if (entries.length === 0) {
    entries.push(...collectInputEntries(dataTransfer?.files));
  }

  return entries.sort((left, right) =>
    left.relativePath.localeCompare(right.relativePath),
  );
}
