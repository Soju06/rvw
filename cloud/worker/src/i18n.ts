import type {Locale} from "./presentation";

export const catalogEn = {
  check_started: "{display_name} review in progress",
  check_passed: "{display_name} review passed",
  check_blocked: "{display_name} review found blockers",
  check_incomplete: "{display_name} review could not complete",
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
  check_started: "{display_name} 검토 중",
  check_passed: "{display_name} 검토 완료",
  check_blocked: "{display_name} 수정 필요",
  check_incomplete: "{display_name} 검토 미완료",
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
