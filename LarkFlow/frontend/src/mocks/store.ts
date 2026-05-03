import type { PipelineState } from "../types/api";
import { pipelineFixtures } from "./fixtures/pipelines";

type PipelineListener = (pipelines: PipelineState[]) => void;

const STORAGE_KEY = "larkflow:mock-pipelines";

function loadPipelines() {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as PipelineState[];
  } catch {
    // sessionStorage 不可用时退回静态 fixtures
  }
  return structuredClone(pipelineFixtures) as PipelineState[];
}

function persistPipelines() {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(pipelines));
  } catch {
    // 持久化失败不影响 mock 的内存态演示
  }
}

let pipelines = loadPipelines();
const listeners = new Set<PipelineListener>();

function emit() {
  persistPipelines();
  const snapshot = getPipelineSnapshot();
  for (const listener of listeners) {
    listener(snapshot);
  }
}

export function getPipelineSnapshot() {
  return structuredClone(pipelines) as PipelineState[];
}

export function findPipeline(id: string) {
  return pipelines.find((item) => item.id === id) ?? null;
}

export function clonePipeline(id: string) {
  const pipeline = findPipeline(id);
  return pipeline ? (structuredClone(pipeline) as PipelineState) : null;
}

export function prependPipeline(next: PipelineState) {
  pipelines = [structuredClone(next) as PipelineState, ...pipelines];
  emit();
}

export function replacePipeline(next: PipelineState) {
  pipelines = pipelines.map((item) => (item.id === next.id ? structuredClone(next) : item));
  emit();
}

export function subscribePipelines(listener: PipelineListener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
