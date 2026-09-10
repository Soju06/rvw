import type {Locale} from "./presentation";

export const catalogEn = {
  bootstrap_summary: "Review is in progress.",
  details: "Review details",
  reason_deadline: "The review could not finish within the available time.",
  reason_superseded: "A newer change replaced this review.",
  reason_queue_exhausted: "The review could not start after repeated attempts.",
  reason_artifacts: "The review could not complete because its results are unavailable.",
  reason_process: "The review stopped before it could complete.",
  reason_config: "The repository presentation configuration is invalid.",
  reason_publish_policy: "The repository publish policy is invalid.",
  reason_language: "The review text could not be verified in the configured language.",
  reason_incomplete: "The review could not complete.",
  review_without_check_details: "Review published without Check details.",

  check_started: "{display_name} · Review in progress",
  check_passed: "{display_name} · Review complete",
  check_blocked: "{display_name} · Changes needed",
  check_incomplete: "{display_name} · Review incomplete",
  job: "Job {job_id}",
  artifacts: "Artifacts: job {job_id}",
  process_passed: "{display_name} run passed",
  process_blocked: "{display_name} run found a blocking result",
  process_status: "{display_name} run {status}",
  process_invalid: "{display_name} process result was missing or invalid: {error}",
  manifest_invalid: "review artifact manifest was invalid or inconsistent",
  summary_invalid: "review summary was invalid: {error}",
  deadline: "{display_name} review exceeded the {minutes}-minute hard deadline",
  ended: "{display_name} review ended without a publishable result",
  process_disappeared: "Sandbox process record disappeared",
  superseded: "superseded by {job_id}",
  queue_exhausted: "Queue retries exhausted: {error}",
} as const;
export type MessageKey = keyof typeof catalogEn;
export const catalogKo: Record<MessageKey, string> = {
  bootstrap_summary: "검토 중입니다.",
  details: "검토 상세 정보",
  reason_deadline: "주어진 시간 안에 검토를 마치지 못했습니다.",
  reason_superseded: "새로운 변경으로 이 검토가 대체되었습니다.",
  reason_queue_exhausted: "여러 차례 시도했으나 검토를 시작하지 못했습니다.",
  reason_artifacts: "검토 결과를 불러올 수 없어 검토를 마치지 못했습니다.",
  reason_process: "검토를 마치기 전에 실행이 중단되었습니다.",
  reason_config: "저장소의 표시 설정이 올바르지 않습니다.",
  reason_publish_policy: "저장소의 게시 정책이 올바르지 않습니다.",
  reason_language: "설정된 언어로 검토 내용을 확인하지 못했습니다.",
  reason_incomplete: "검토를 마치지 못했습니다.",
  review_without_check_details: "Check 상세 정보 없이 검토를 게시했습니다.",

  check_started: "{display_name} · 검토 중",
  check_passed: "{display_name} · 검토 완료",
  check_blocked: "{display_name} · 수정 필요",
  check_incomplete: "{display_name} · 검토 미완료",
  job: "작업 {job_id}",
  artifacts: "산출물: 작업 {job_id}",
  process_passed: "{display_name} 실행 통과",
  process_blocked: "{display_name} 실행에서 차단 결과 발견",
  process_status: "{display_name} 실행 {status}",
  process_invalid: "{display_name} 실행 결과가 없거나 잘못되었습니다: {error}",
  manifest_invalid: "검토 산출물 목록이 잘못되었거나 일치하지 않습니다",
  summary_invalid: "검토 요약이 잘못되었습니다: {error}",
  deadline: "{display_name} 검토가 제한 시간 {minutes}분을 초과했습니다",
  ended: "{display_name} 검토가 게시 가능한 결과 없이 종료되었습니다",
  process_disappeared: "샌드박스 프로세스 기록이 사라졌습니다",
  superseded: "새 작업 {job_id}으로 대체되었습니다",
  queue_exhausted: "대기열 재시도 횟수를 초과했습니다: {error}",
};

export function t(key: MessageKey, locale: Locale = "en", args: Record<string, string | number> = {}): string {
  const template = (locale === "ko" ? catalogKo : catalogEn)[key];
  return template.replace(/\{(\w+)\}/g, (_match, name: string) => {
    if (!(name in args)) throw new Error(`Missing translation argument: ${key}.${name}`);
    return String(args[name]);
  });
}
