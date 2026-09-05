import { shallowRef } from "vue";

/**
 * Minimal loading/error/data state for a fetch. No state library: each view
 * owns the handful of requests it needs (CLAUDE.md §3, "no Pinia").
 * Callers that need to branch on the HTTP status (the 409 flow) call the
 * API directly and inspect ApiError; this helper only renders outcomes.
 */
export function useAsync<T>(fn: () => Promise<T>) {
  const data = shallowRef<T | null>(null);
  const loading = shallowRef(false);
  const error = shallowRef<string | null>(null);

  async function run(): Promise<T | null> {
    loading.value = true;
    error.value = null;
    try {
      data.value = await fn();
      return data.value;
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      return null;
    } finally {
      loading.value = false;
    }
  }

  return { data, loading, error, run };
}
