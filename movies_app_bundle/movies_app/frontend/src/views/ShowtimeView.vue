<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import SeatMap from "../components/SeatMap.vue";
import StateBlock from "../components/StateBlock.vue";
import { useAsync } from "../composables/useAsync";
import { api, ApiError, type SeatDetail } from "../services/api";
import { dateTime, money, seatLabel } from "../utils/format";

const props = defineProps<{ id: string }>();
const router = useRouter();

// Same cap as CreateBookingRequest.seat_ids (1..8) on the backend.
const MAX_SEATS = 8;

const seatMap = useAsync(() => api.getSeatMap(props.id));
onMounted(seatMap.run);

const selected = ref<string[]>([]);
const taken = ref<string[]>([]);
const customer = ref({ name: "", email: "" });
const submitting = ref(false);
const submitError = ref<string | null>(null);

/** seat_id → seat + row label, for the summary and the running total. */
const seatIndex = computed(() => {
  const idx = new Map<string, SeatDetail & { label: string }>();
  for (const row of seatMap.data.value?.rows ?? []) {
    for (const s of row.seats) {
      idx.set(s.seat_id, { ...s, label: seatLabel(row.row_label, s.seat_number) });
    }
  }
  return idx;
});

const selectedSeats = computed(() =>
  selected.value
    .map((id) => seatIndex.value.get(id))
    .filter((s): s is SeatDetail & { label: string } => s !== undefined),
);

const total = computed(() =>
  selectedSeats.value.reduce((sum, s) => sum + s.price, 0),
);

const canSubmit = computed(
  () =>
    selected.value.length > 0 &&
    customer.value.name.trim().length > 0 &&
    customer.value.email.trim().length > 0 &&
    !submitting.value,
);

const submitLabel = computed(() => {
  if (submitting.value) return "Booking…";
  const n = selected.value.length;
  return n === 0 ? "Book seats" : `Book ${n} ${n === 1 ? "seat" : "seats"}`;
});

// The seat map payload has no movie_id, so "back" is the browser history
// when there is one (the normal funnel) and the movies grid otherwise.
function goBack() {
  if (window.history.state?.back) router.back();
  else router.push({ name: "movies" });
}

function toggle(seatId: string) {
  submitError.value = null;
  const i = selected.value.indexOf(seatId);
  if (i >= 0) selected.value.splice(i, 1);
  else if (selected.value.length < MAX_SEATS) selected.value.push(seatId);
}

async function book() {
  if (!canSubmit.value) return;
  submitting.value = true;
  submitError.value = null;
  taken.value = [];
  try {
    const booking = await api.createBooking({
      showtime_id: props.id,
      seat_ids: [...selected.value],
      customer: {
        name: customer.value.name.trim(),
        email: customer.value.email.trim(),
      },
    });
    router.push({ name: "booking", params: { id: booking.booking_id } });
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      // Someone else committed first. The database said no (UNIQUE on
      // (showtime_id, seat_id)); re-fetch so the map shows the truth, keep
      // the seats that are still free selected, highlight the ones lost.
      taken.value = err.takenSeatIds;
      selected.value = selected.value.filter((id) => !taken.value.includes(id));
      await seatMap.run();
      const lost = taken.value
        .map((id) => seatIndex.value.get(id)?.label ?? id)
        .join(", ");
      submitError.value = `${err.detail}: ${lost}. The seat map has been refreshed.`;
    } else if (err instanceof ApiError) {
      submitError.value = err.detail;
    } else {
      submitError.value = String(err);
    }
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <section>
    <button type="button" class="back" @click="goBack">
      ← Back to showtimes
    </button>

    <StateBlock
      :loading="seatMap.loading.value && !seatMap.data.value"
      :error="seatMap.error.value"
      loading-text="Loading seat map…"
      @retry="seatMap.run"
    />

    <div v-if="seatMap.data.value" class="layout">
      <div class="map-panel">
        <header class="show-head">
          <h2>{{ seatMap.data.value.showtime.movie_title }}</h2>
          <p class="muted">
            {{ seatMap.data.value.showtime.auditorium_name }} ·
            {{ dateTime(seatMap.data.value.showtime.starts_at) }}
          </p>
          <p class="muted prices">
            Standard {{ money(seatMap.data.value.showtime.price_standard) }} ·
            Premium {{ money(seatMap.data.value.showtime.price_premium) }} ·
            Accessible {{ money(seatMap.data.value.showtime.price_standard) }}
          </p>
        </header>

        <SeatMap
          :rows="seatMap.data.value.rows"
          :selected="selected"
          :taken="taken"
          :max-seats="MAX_SEATS"
          @toggle="toggle"
        />
      </div>

      <aside class="side-panel">
        <h3>Your seats</h3>
        <p v-if="selectedSeats.length === 0" class="muted">
          Select up to {{ MAX_SEATS }} seats on the map.
        </p>
        <ul v-else class="seat-list">
          <li v-for="s in selectedSeats" :key="s.seat_id">
            <span>
              <strong>{{ s.label }}</strong>
              <span class="muted"> · {{ s.seat_type }}</span>
            </span>
            <span>{{ money(s.price) }}</span>
          </li>
        </ul>
        <div class="total">
          <span>Total</span>
          <strong>{{ money(total) }}</strong>
        </div>

        <form class="form" @submit.prevent="book">
          <label>
            Name
            <input
              v-model="customer.name"
              type="text"
              name="name"
              autocomplete="name"
              required
              maxlength="120"
            />
          </label>
          <label>
            Email
            <input
              v-model="customer.email"
              type="email"
              name="email"
              autocomplete="email"
              required
              maxlength="200"
            />
          </label>

          <p v-if="submitError" class="error" role="alert">
            {{ submitError }}
          </p>

          <button type="submit" class="btn" :disabled="!canSubmit">
            {{ submitLabel }}
          </button>
          <p class="fine-print">
            No payment is taken. Bookings are confirmed immediately.
          </p>
        </form>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.back {
  display: inline-block;
  margin-bottom: var(--spacing-md);
  color: var(--color-primary);
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.muted {
  color: var(--color-text-muted);
}

.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: var(--spacing-xl);
  align-items: start;
}

.map-panel {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--spacing-lg);
  box-shadow: var(--shadow-sm);
}

.show-head {
  margin-bottom: var(--spacing-lg);
}

.show-head h2 {
  font-size: var(--font-size-xl);
  line-height: 1.2;
}

.prices {
  font-size: var(--font-size-sm);
}

.side-panel {
  position: sticky;
  top: var(--spacing-lg);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--spacing-lg);
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.side-panel h3 {
  font-size: var(--font-size-lg);
}

.seat-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.seat-list li {
  display: flex;
  justify-content: space-between;
}

.total {
  display: flex;
  justify-content: space-between;
  padding-top: var(--spacing-sm);
  border-top: 1px solid var(--color-border);
  font-size: var(--font-size-lg);
}

.form {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.form label {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.form input {
  padding: var(--spacing-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font: inherit;
  color: var(--color-text);
}

.form input:focus {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
  border-color: var(--color-primary);
}

.btn {
  padding: var(--spacing-sm) var(--spacing-md);
  border: none;
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  color: #fff;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.btn:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error {
  padding: var(--spacing-sm);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-danger) 8%, var(--color-surface));
  border: 1px solid var(--color-danger);
  color: var(--color-danger);
  font-size: var(--font-size-sm);
}

.fine-print {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  text-align: center;
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .side-panel {
    position: static;
  }
}
</style>
