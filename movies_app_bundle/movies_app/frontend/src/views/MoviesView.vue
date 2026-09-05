<script setup lang="ts">
import { onMounted } from "vue";
import PosterImage from "../components/PosterImage.vue";
import StateBlock from "../components/StateBlock.vue";
import { useAsync } from "../composables/useAsync";
import { api, type Movie } from "../services/api";

const movies = useAsync(() => api.listMovies());
onMounted(movies.run);

function meta(m: Movie): string {
  return [m.genre, m.rating, m.runtime_min ? `${m.runtime_min} min` : null]
    .filter(Boolean)
    .join(" · ");
}
</script>

<template>
  <section>
    <div class="page-head">
      <h2>Now showing</h2>
      <p class="muted">Pick a movie to see theaters and showtimes.</p>
    </div>

    <StateBlock
      :loading="movies.loading.value"
      :error="movies.error.value"
      loading-text="Loading movies…"
      @retry="movies.run"
    />

    <div v-if="movies.data.value" class="grid">
      <router-link
        v-for="m in movies.data.value"
        :key="m.movie_id"
        :to="{ name: 'movie', params: { id: m.movie_id } }"
        class="card"
      >
        <PosterImage :src="m.poster_url" :title="m.title" />
        <div class="card__body">
          <h3 class="card__title">{{ m.title }}</h3>
          <p class="card__meta">{{ meta(m) }}</p>
          <p v-if="m.synopsis" class="card__synopsis">{{ m.synopsis }}</p>
        </div>
      </router-link>
    </div>
  </section>
</template>

<style scoped>
.page-head {
  margin-bottom: var(--spacing-lg);
}

.page-head h2 {
  font-size: var(--font-size-xl);
}

.muted {
  color: var(--color-text-muted);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--spacing-lg);
}

.card {
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  text-decoration: none;
  color: inherit;
  box-shadow: var(--shadow-sm);
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}

.card:hover,
.card:focus-visible {
  transform: translateY(-3px);
  box-shadow: var(--shadow-md);
}

.card__body {
  padding: var(--spacing-md);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.card__title {
  font-size: var(--font-size-base);
  line-height: 1.3;
}

.card__meta {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.card__synopsis {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
