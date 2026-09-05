<script setup lang="ts">
import { computed, onMounted } from "vue";
import StateBlock from "../components/StateBlock.vue";
import { useAsync } from "../composables/useAsync";
import { api } from "../services/api";
import { dateTime, money, seatLabel } from "../utils/format";

const props = defineProps<{ id: string }>();

const booking = useAsync(() => api.getBooking(props.id));

// The booking carries only showtime_id. There is no GET /api/showtimes/{id}
// in the contract, so the seat-map endpoint supplies the movie / room / time
// header (120 small rows, cheap; a dedicated endpoint is a trivial follow-up).
const showtime = useAsync(async () => {
  const b = booking.data.value;
  return b ? (await api.getSeatMap(b.showtime_id)).showtime : null;
});

async function load() {
  await booking.run();
  if (booking.data.value) await showtime.run();
}
onMounted(load);

const seats = computed(() => booking.data.value?.seats ?? []);
const confirmed = computed(() => booking.data.value?.status === "CONFIRMED");
</script>

<template>
  <section>
    <StateBlock
      :loading="booking.loading.value"
      :error="booking.error.value"
      loading-text="Loading booking…"
      @retry="load"
    />

    <div v-if="booking.data.value" class="card">
      <header class="head" :class="{ 'head--cancelled': !confirmed }">
        <span class="badge" aria-hidden="true">{{ confirmed ? "✓" : "✕" }}</span>
        <div>
          <h2>{{ confirmed ? "You're booked!" : "Booking cancelled" }}</h2>
          <p class="muted">
            Confirmation
            <code class="id">{{ booking.data.value.booking_id }}</code>
          </p>
        </div>
      </header>

      <dl class="details">
        <template v-if="showtime.data.value">
          <dt>Movie</dt>
          <dd>{{ showtime.data.value.movie_title }}</dd>
          <dt>When</dt>
          <dd>{{ dateTime(showtime.data.value.starts_at) }}</dd>
          <dt>Room</dt>
          <dd>{{ showtime.data.value.auditorium_name }}</dd>
        </template>
        <dt>Name</dt>
        <dd>{{ booking.data.value.customer_name }}</dd>
        <dt>Email</dt>
        <dd>{{ booking.data.value.customer_email }}</dd>
        <dt>Booked at</dt>
        <dd>{{ dateTime(booking.data.value.created_at) }}</dd>
        <dt>Status</dt>
        <dd>{{ booking.data.value.status }}</dd>
      </dl>

      <h3>Seats</h3>
      <ul class="seats">
        <li v-for="s in seats" :key="s.seat_id">
          <span class="seat-chip">{{ seatLabel(s.row_label, s.seat_number) }}</span>
          <span class="muted">{{ s.seat_type }}</span>
          <span class="price">{{ money(s.price) }}</span>
        </li>
      </ul>
      <div class="total">
        <span>Total paid</span>
        <strong>{{ money(booking.data.value.total_amount) }}</strong>
      </div>

      <nav class="actions">
        <router-link
          :to="{ name: 'showtime', params: { id: booking.data.value.showtime_id } }"
          class="btn btn--ghost"
        >
          View seat map
        </router-link>
        <router-link to="/" class="btn">Book another movie</router-link>
      </nav>
    </div>
  </section>
</template>

<style scoped>
.muted {
  color: var(--color-text-muted);
}

.card {
  max-width: 640px;
  margin: 0 auto;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--spacing-xl);
  box-shadow: var(--shadow-md);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
}

.head {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
}

.head h2 {
  font-size: var(--font-size-xl);
  line-height: 1.2;
}

.badge {
  display: grid;
  place-items: center;
  width: 3rem;
  height: 3rem;
  border-radius: 50%;
  background: var(--color-accent);
  color: #fff;
  font-size: var(--font-size-xl);
  flex-shrink: 0;
}

.head--cancelled .badge {
  background: var(--color-danger);
}

.id {
  font-size: var(--font-size-sm);
  user-select: all;
}

.details {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: var(--spacing-xs) var(--spacing-lg);
}

.details dt {
  color: var(--color-text-muted);
}

.card h3 {
  font-size: var(--font-size-lg);
  margin-bottom: calc(-1 * var(--spacing-sm));
}

.seats {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.seats li {
  display: grid;
  grid-template-columns: 4rem 1fr auto;
  align-items: center;
  gap: var(--spacing-md);
}

.seat-chip {
  display: inline-block;
  text-align: center;
  padding: 2px var(--spacing-sm);
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  color: #fff;
  font-weight: 600;
}

.total {
  display: flex;
  justify-content: space-between;
  padding-top: var(--spacing-sm);
  border-top: 1px solid var(--color-border);
  font-size: var(--font-size-lg);
}

.actions {
  display: flex;
  gap: var(--spacing-sm);
  justify-content: flex-end;
  flex-wrap: wrap;
}

.btn {
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  color: #fff;
  text-decoration: none;
  font-weight: 600;
}

.btn:hover {
  background: var(--color-primary-hover);
}

.btn--ghost {
  background: transparent;
  color: var(--color-primary);
  border: 1px solid var(--color-primary);
}

.btn--ghost:hover {
  background: color-mix(in srgb, var(--color-primary) 8%, transparent);
}
</style>
