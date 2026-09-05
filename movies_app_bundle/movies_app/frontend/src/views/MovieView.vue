<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import PosterImage from "../components/PosterImage.vue";
import StateBlock from "../components/StateBlock.vue";
import { useAsync } from "../composables/useAsync";
import { api, type Showtime } from "../services/api";
import { dateKey, longDate, money, time } from "../utils/format";

const props = defineProps<{ id: string }>();

// One request each; the theater filter is applied client-side because the
// full list for one movie is small (a few dozen rows over 7 days).
const movie = useAsync(() => api.getMovie(props.id));
const theaters = useAsync(() => api.listTheaters());
const showtimes = useAsync(() => api.listShowtimes({ movie_id: props.id }));

const selectedTheater = ref<string | null>(null);

const loading = computed(
  () => movie.loading.value || theaters.loading.value || showtimes.loading.value,
);
const error = computed(
  () => movie.error.value ?? theaters.error.value ?? showtimes.error.value,
);

function load() {
  movie.run();
  theaters.run();
  showtimes.run();
}
onMounted(load);

/** Theaters that actually have a future showtime for this movie. */
const theaterOptions = computed(() => {
  const ids = new Set((showtimes.data.value ?? []).map((s) => s.theater_id));
  return (theaters.data.value ?? []).filter((t) => ids.has(t.theater_id));
});

const filtered = computed(() =>
  (showtimes.data.value ?? []).filter(
    (s) => !selectedTheater.value || s.theater_id === selectedTheater.value,
  ),
);

/** Showtimes grouped by UTC day, in chronological order. */
const byDay = computed(() => {
  const groups = new Map<string, Showtime[]>();
  for (const s of filtered.value) {
    const key = dateKey(s.starts_at);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(s);
  }
  return [...groups.entries()].map(([day, items]) => ({ day, items }));
});

function meta(): string {
  const m = movie.data.value;
  if (!m) return "";
  return [m.genre, m.rating, m.runtime_min ? `${m.runtime_min} min` : null]
    .filter(Boolean)
    .join(" · ");
}
</script>

<template>
  <section>
    <router-link to="/" class="back">← All movies</router-link>

    <StateBlock :loading="loading" :error="error" @retry="load" />

    <template v-if="!loading && movie.data.value">
      <header class="movie-head">
        <PosterImage
          class="poster"
          :src="movie.data.value.poster_url"
          :title="movie.data.value.title"
        />
        <div>
          <h2>{{ movie.data.value.title }}</h2>
          <p class="muted">{{ meta() }}</p>
          <p v-if="movie.data.value.synopsis" class="synopsis">
            {{ movie.data.value.synopsis }}
          </p>
        </div>
      </header>

      <h3 class="section-title">Pick a theater</h3>
      <div class="chips" role="radiogroup" aria-label="Theater">
        <button
          type="button"
          class="chip"
          :class="{ 'chip--active': selectedTheater === null }"
          role="radio"
          :aria-checked="selectedTheater === null"
          @click="selectedTheater = null"
        >
          All theaters
        </button>
        <button
          v-for="t in theaterOptions"
          :key="t.theater_id"
          type="button"
          class="chip"
          :class="{ 'chip--active': selectedTheater === t.theater_id }"
          role="radio"
          :aria-checked="selectedTheater === t.theater_id"
          @click="selectedTheater = t.theater_id"
        >
          {{ t.name }}
          <span class="chip__city">{{ t.city }}</span>
        </button>
      </div>

      <h3 class="section-title">Showtimes</h3>
      <p v-if="byDay.length === 0" class="muted">
        No upcoming showtimes for this selection.
      </p>

      <div v-for="group in byDay" :key="group.day" class="day">
        <h4 class="day__title">{{ longDate(group.day) }}</h4>
        <div class="showtimes">
          <router-link
            v-for="s in group.items"
            :key="s.showtime_id"
            :to="{ name: 'showtime', params: { id: s.showtime_id } }"
            class="showtime"
          >
            <span class="showtime__time">{{ time(s.starts_at) }}</span>
            <span class="showtime__where">
              {{ s.theater_name }} · {{ s.auditorium_name }}
            </span>
            <span class="showtime__price">
              from {{ money(s.price_standard) }}
            </span>
          </router-link>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.back {
  display: inline-block;
  margin-bottom: var(--spacing-md);
  color: var(--color-primary);
  text-decoration: none;
  font-size: var(--font-size-sm);
}

.muted {
  color: var(--color-text-muted);
}

.movie-head {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: var(--spacing-lg);
  margin-bottom: var(--spacing-xl);
}

.movie-head h2 {
  font-size: var(--font-size-xl);
  line-height: 1.2;
}

.synopsis {
  margin-top: var(--spacing-sm);
  max-width: 60ch;
}

.poster {
  border-radius: var(--radius-md);
}

.section-title {
  font-size: var(--font-size-lg);
  margin: var(--spacing-lg) 0 var(--spacing-sm);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
}

.chip {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-start;
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
  cursor: pointer;
  line-height: 1.3;
}

.chip:hover {
  border-color: var(--color-primary);
}

.chip--active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
}

.chip__city {
  font-size: var(--font-size-sm);
  opacity: 0.75;
}

.day {
  margin-bottom: var(--spacing-lg);
}

.day__title {
  font-size: var(--font-size-base);
  color: var(--color-text-muted);
  margin-bottom: var(--spacing-sm);
}

.showtimes {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--spacing-sm);
}

.showtime {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  text-decoration: none;
  color: inherit;
  box-shadow: var(--shadow-sm);
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}

.showtime:hover,
.showtime:focus-visible {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--color-primary);
}

.showtime__time {
  font-weight: 600;
  color: var(--color-primary);
}

.showtime__where,
.showtime__price {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

@media (max-width: 640px) {
  .movie-head {
    grid-template-columns: 100px 1fr;
  }
}
</style>
