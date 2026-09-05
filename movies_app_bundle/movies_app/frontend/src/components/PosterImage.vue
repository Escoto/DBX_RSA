<script setup lang="ts">
import { ref, watch } from "vue";

// Seed posters are external URLs (picsum.photos). If the network blocks them
// or the URL is null, fall back to a gradient with the title initial so the
// grid still looks intentional during a demo on a locked-down network.
const props = defineProps<{ src: string | null; title: string }>();
const failed = ref(false);
watch(() => props.src, () => (failed.value = false));
</script>

<template>
  <div class="poster" :class="{ 'poster--placeholder': !src || failed }">
    <img
      v-if="src && !failed"
      :src="src"
      :alt="`${title} poster`"
      loading="lazy"
      @error="failed = true"
    />
    <span v-else aria-hidden="true">{{ title.charAt(0) }}</span>
  </div>
</template>

<style scoped>
.poster {
  aspect-ratio: 2 / 3;
  background: var(--color-border);
  overflow: hidden;
}

.poster img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.poster--placeholder {
  display: grid;
  place-items: center;
  font-size: 4rem;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(
    135deg,
    var(--color-primary),
    var(--color-accent)
  );
}
</style>
