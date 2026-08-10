const PHASE_LABELS = {
  memory: "Memory",
  routing: "Query analysis",
  retrieval: "Retrieval",
  rerank: "Rerank",
  context: "Context",
  generation: "Generation",
  responding: "Response",
  finalizing: "Finalizing",
  network: "Connection",
};

export function phaseLabel(phase) {
  return PHASE_LABELS[phase] || phase || "Progress";
}

export function upsertProgressStep(steps = [], update = {}) {
  const phase = update.phase || "progress";
  const nextStep = {
    phase,
    state: update.state || "running",
    message: update.message || phaseLabel(phase),
    detail: update.detail || "",
    elapsedMs:
      Number.isFinite(Number(update.elapsed_ms))
        ? Number(update.elapsed_ms)
        : null,
    metadata: update.metadata || {},
  };
  const index = steps.findIndex((step) => step.phase === phase);
  if (index < 0) return [...steps, nextStep];

  return steps.map((step, stepIndex) =>
    stepIndex === index
      ? {
          ...step,
          ...nextStep,
          metadata: { ...step.metadata, ...nextStep.metadata },
        }
      : step,
  );
}

export function markProgressError(steps = [], phase, message) {
  return upsertProgressStep(steps, {
    phase: phase || "network",
    state: "error",
    message: message || "This stage failed",
  });
}

function compactSourceLabel(source) {
  if (source.length <= 42) return source;
  const segments = source.replaceAll("\\", "/").split("/");
  return segments.length > 1
    ? `…/${segments.slice(-2).join("/")}`
    : `${source.slice(0, 39)}…`;
}

export function groupSourceTags(sources = []) {
  const groups = new Map();
  for (const source of sources) {
    const identity =
      source.source || source.file_name || source.file_path || "Unknown source";
    const group = groups.get(identity) || {
      key: identity,
      label: compactSourceLabel(identity),
      fullSource: identity,
      chunkCount: 0,
      pages: new Set(),
    };
    group.chunkCount += 1;
    if (source.page !== null && source.page !== undefined) {
      const page = Number(source.page);
      group.pages.add(Number.isFinite(page) ? page + 1 : source.page);
    }
    groups.set(identity, group);
  }

  return Array.from(groups.values()).map((group) => {
    const pages = Array.from(group.pages).sort((left, right) => left - right);
    const meta = [];
    if (pages.length > 0) {
      meta.push(`p. ${pages.join(", ")}`);
    }
    if (group.chunkCount > 1) {
      meta.push(`${group.chunkCount} chunks`);
    }
    return {
      key: group.key,
      label: group.label,
      meta: meta.join(" · "),
      title: [group.fullSource, ...meta].join(" · "),
      chunkCount: group.chunkCount,
      pages,
    };
  });
}

export function pipelineElapsedMs(steps = []) {
  const finalizing = steps.find((step) => step.phase === "finalizing");
  const total = Number(finalizing?.metadata?.total_elapsed_ms);
  return Number.isFinite(total) ? total : null;
}
