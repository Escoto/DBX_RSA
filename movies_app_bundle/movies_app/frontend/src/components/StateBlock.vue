<script setup lang="ts">
// Shared loading / error presentation so every view handles the two
// non-happy states the same way. Renders nothing when neither applies.
defineProps<{
  loading: boolean;
  error: string | null;
  loadingText?: string;
}>();
defineEmits<{ retry: [] }>();
</script>

<template>
  <div v-if="loading" class="state state--loading" role="status">
    <span class="spinner" aria-hidden="true"></span>
    <span>{{ loadingText ?? "Loading…" }}</span>
  </div>
  <div v-else-if="error" class="state state--error" role="alert">
    <p class="state__title">Something went wrong</p>
    <p class="state__detail">{{ error }}</p>
    <button type="button" class="btn--ghost" @click="$emit('retry')">
      Try again
    </button>
  </div>
</template>

<style scoped>
.state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-xl);
  color: var(--color-text-muted);
  text-align: center;
}

.state--loading {
  flex-direction: row;
  justify-content: center;
}

.state--error {
  border: 1px solid var(--color-danger);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-danger) 6%, var(--color-surface));
}

.state__title {
  font-weight: 600;
  color: var(--color-danger);
}

.state__detail {
  font-size: var(--font-size-sm);
}

.btn--ghost {
  padding: var(--spacing-xs) var(--spacing-md);
  border: 1px solid var(--color-primary);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-primary);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.btn--ghost:hover {
  background: color-mix(in srgb, var(--color-primary) 8%, transparent);
}

.spinner {
  width: 1rem;
  height: 1rem;
  border: 2px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
