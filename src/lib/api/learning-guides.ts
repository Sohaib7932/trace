import { protectedApiRequest, type Schema } from "./client";

// These aliases come from the actual exported backend schema. Private instructional
// guides remain separate from reviewed, verified executable LessonSpecV1 content.
export type GuideLevel = Schema["GuideCreate"]["start_level"];
export type GuideCreate = Schema["GuideCreate"];
export type GuideContent = Schema["GuideContent"];
export type GuideSummary = Schema["GuideSummary"];
export type GuideDetail = Schema["GuideDetail"];

export const learningGuidesApi = {
  list: (signal?: AbortSignal) => protectedApiRequest<GuideSummary[]>("/learning-guides", undefined, undefined, signal),
  get: (id: string, signal?: AbortSignal) => protectedApiRequest<GuideDetail>(`/learning-guides/${encodeURIComponent(id)}`, undefined, undefined, signal),
  create: (body: GuideCreate, key: string, signal?: AbortSignal) => protectedApiRequest<GuideDetail>("/learning-guides", body, key, signal),
};
