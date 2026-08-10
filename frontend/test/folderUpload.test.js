import assert from "node:assert/strict";
import test from "node:test";

import {
  collectDroppedEntries,
  collectInputEntries,
  prepareUploadEntries,
} from "../src/folderUpload.js";

function fakeFile(name, size = 10) {
  return { name, size, lastModified: 1 };
}

test("same basenames remain distinct when their relative paths differ", () => {
  const { accepted, skipped } = prepareUploadEntries([
    {
      file: fakeFile("README.md"),
      relativePath: "project/backend/README.md",
    },
    {
      file: fakeFile("README.md"),
      relativePath: "project/frontend/README.md",
    },
  ]);

  assert.deepEqual(
    accepted.map((entry) => entry.relativePath),
    ["project/backend/README.md", "project/frontend/README.md"],
  );
  assert.equal(skipped.length, 0);
});

test("unsupported, system, and duplicate paths are ignored independently", () => {
  const existing = [
    { file: fakeFile("guide.md"), relativePath: "docs/guide.md" },
  ];
  const { accepted, skipped } = prepareUploadEntries(
    [
      { file: fakeFile("diagram.png"), relativePath: "docs/diagram.png" },
      { file: fakeFile(".DS_Store"), relativePath: "docs/.DS_Store" },
      { file: fakeFile("guide.md"), relativePath: "docs/guide.md" },
      { file: fakeFile("new.md"), relativePath: "docs/new.md" },
    ],
    existing,
  );

  assert.deepEqual(
    accepted.map((entry) => entry.relativePath),
    ["docs/new.md"],
  );
  assert.deepEqual(
    skipped.map((entry) => entry.reason),
    ["Unsupported type .png", "System file", "Duplicate relative path"],
  );
});

test("directory input keeps webkitRelativePath", () => {
  const file = fakeFile("guide.md");
  file.webkitRelativePath = "knowledge/backend/guide.md";

  assert.equal(
    collectInputEntries([file])[0].relativePath,
    "knowledge/backend/guide.md",
  );
});

test("modern dropped directory handles are traversed asynchronously", async () => {
  const backendFile = fakeFile("README.md");
  const rootHandle = {
    kind: "directory",
    name: "project",
    async *values() {
      yield {
        kind: "directory",
        name: "backend",
        async *values() {
          yield {
            kind: "file",
            name: "README.md",
            async getFile() {
              return backendFile;
            },
          };
        },
      };
    },
  };
  const dataTransfer = {
    items: [
      {
        kind: "file",
        async getAsFileSystemHandle() {
          return rootHandle;
        },
      },
    ],
    files: [],
  };

  const entries = await collectDroppedEntries(dataTransfer);

  assert.equal(entries.length, 1);
  assert.equal(entries[0].relativePath, "project/backend/README.md");
  assert.equal(entries[0].file, backendFile);
});

test("WebKit directory entries read every asynchronous batch", async () => {
  const guideFile = fakeFile("guide.md");
  const fileEntry = {
    name: "guide.md",
    isFile: true,
    isDirectory: false,
    file(resolve) {
      resolve(guideFile);
    },
  };
  const batches = [[fileEntry], []];
  const directoryEntry = {
    name: "knowledge",
    isFile: false,
    isDirectory: true,
    createReader() {
      return {
        readEntries(resolve) {
          resolve(batches.shift());
        },
      };
    },
  };
  const dataTransfer = {
    items: [
      {
        kind: "file",
        webkitGetAsEntry() {
          return directoryEntry;
        },
      },
    ],
    files: [],
  };

  const entries = await collectDroppedEntries(dataTransfer);

  assert.equal(entries[0].relativePath, "knowledge/guide.md");
  assert.equal(entries[0].file, guideFile);
});
