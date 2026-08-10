import assert from "node:assert/strict";
import test from "node:test";

import {
  groupSourceTags,
  markProgressError,
  pipelineElapsedMs,
  upsertProgressStep,
} from "../src/streamPresentation.js";

test("progress updates replace a phase without losing arrival order", () => {
  let steps = upsertProgressStep([], {
    phase: "routing",
    state: "running",
    message: "Analyzing",
  });
  steps = upsertProgressStep(steps, {
    phase: "retrieval",
    state: "running",
    message: "Searching",
  });
  steps = upsertProgressStep(steps, {
    phase: "routing",
    state: "completed",
    message: "Complete",
    elapsed_ms: 1200,
  });

  assert.deepEqual(steps.map((step) => step.phase), ["routing", "retrieval"]);
  assert.equal(steps[0].state, "completed");
  assert.equal(steps[0].elapsedMs, 1200);
});

test("a stream error marks the actual failed phase", () => {
  const steps = markProgressError(
    [{ phase: "retrieval", state: "running", metadata: {} }],
    "retrieval",
    "Unable to retrieve",
  );

  assert.equal(steps[0].state, "error");
  assert.equal(steps[0].message, "Unable to retrieve");
});

test("source chunks collapse into document tags without retrieval scores", () => {
  const tags = groupSourceTags([
    { source: "project/backend/guide.pdf", page: 0, score: 0.91 },
    { source: "project/backend/guide.pdf", page: 2, score: 0.72 },
    { source: "project/frontend/README.md", page: null, score: 0.64 },
  ]);

  assert.equal(tags.length, 2);
  assert.equal(tags[0].chunkCount, 2);
  assert.deepEqual(tags[0].pages, [1, 3]);
  assert.equal(tags[0].meta, "p. 1, 3 · 2 chunks");
  assert.equal("score" in tags[0], false);
});

test("pipeline total comes from factual finalization metadata", () => {
  const steps = upsertProgressStep([], {
    phase: "finalizing",
    state: "completed",
    message: "Done",
    metadata: { total_elapsed_ms: 4321 },
  });

  assert.equal(pipelineElapsedMs(steps), 4321);
});

test("persistence warnings remain non-fatal and keep total timing metadata", () => {
  const steps = upsertProgressStep([], {
    phase: "finalizing",
    state: "warning",
    message: "Answer ready, but conversation history was not saved",
    metadata: { total_elapsed_ms: 987 },
  });

  assert.equal(steps[0].state, "warning");
  assert.equal(pipelineElapsedMs(steps), 987);
});
