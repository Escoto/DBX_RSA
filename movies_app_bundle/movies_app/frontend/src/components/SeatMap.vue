<script setup lang="ts">
import { computed } from "vue";
import type { SeatDetail, SeatRow } from "../services/api";
import { money, seatLabel } from "../utils/format";

// Pure presentation: the parent owns the selection and the conflict list.
// A seat is one <button>; `booked` seats are disabled, `taken` seats are the
// ones a 409 just reported (they are also booked after the re-fetch, the
// extra class only makes them stand out).
const props = defineProps<{
  rows: SeatRow[];
  selected: string[];
  taken: string[];
  maxSeats: number;
}>();
const emit = defineEmits<{ toggle: [seatId: string] }>();

const selectedSet = computed(() => new Set(props.selected));
const takenSet = computed(() => new Set(props.taken));
const atLimit = computed(() => props.selected.length >= props.maxSeats);

function classes(seat: SeatDetail) {
  return {
    seat: true,
    [`seat--${seat.seat_type}`]: true,
    "seat--booked": seat.status === "booked",
    "seat--selected": selectedSet.value.has(seat.seat_id),
    "seat--taken": takenSet.value.has(seat.seat_id),
  };
}

function isDisabled(seat: SeatDetail): boolean {
  if (seat.status === "booked") return true;
  return atLimit.value && !selectedSet.value.has(seat.seat_id);
}

function title(seat: SeatDetail, row: SeatRow): string {
  const label = seatLabel(row.row_label, seat.seat_number);
  if (takenSet.value.has(seat.seat_id)) return `${label} · just taken`;
  if (seat.status === "booked") return `${label} · booked`;
  return `${label} · ${seat.seat_type} · ${money(seat.price)}`;
}
</script>

<template>
  <div class="seatmap">
    <div class="screen" aria-hidden="true">Screen</div>

    <div class="grid" role="group" aria-label="Seat map">
      <div v-for="row in rows" :key="row.row_label" class="row">
        <span class="row__label" aria-hidden="true">{{ row.row_label }}</span>
        <button
          v-for="seat in row.seats"
          :key="seat.seat_id"
          type="button"
          :class="classes(seat)"
          :disabled="isDisabled(seat)"
          :aria-pressed="selectedSet.has(seat.seat_id)"
          :aria-label="title(seat, row)"
          :title="title(seat, row)"
          @click="emit('toggle', seat.seat_id)"
        >
          <span v-if="seat.seat_type === 'accessible'" aria-hidden="true">♿</span>
          <span v-else>{{ seat.seat_number }}</span>
        </button>
        <span class="row__label" aria-hidden="true">{{ row.row_label }}</span>
      </div>
    </div>

    <ul class="legend" aria-label="Legend">
      <li><span class="swatch seat seat--standard"></span> Standard</li>
      <li><span class="swatch seat seat--premium"></span> Premium</li>
      <li><span class="swatch seat seat--accessible"></span> Accessible</li>
      <li><span class="swatch seat seat--selected"></span> Selected</li>
      <li><span class="swatch seat seat--booked"></span> Booked</li>
      <li v-if="taken.length">
        <span class="swatch seat seat--booked seat--taken"></span> Just taken
      </li>
    </ul>
  </div>
</template>

<style scoped>
.seatmap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-lg);
}

.screen {
  width: 70%;
  padding: var(--spacing-xs);
  text-align: center;
  font-size: var(--font-size-sm);
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--color-text-muted);
  border-top: 4px solid var(--color-text-muted);
  border-radius: 50% 50% 0 0 / 100% 100% 0 0;
  opacity: 0.7;
}

/* The grid, not the whole map, scrolls sideways on narrow screens; a centered
   flex child with overflow would clip its left edge unreachably. */
.grid {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  max-width: 100%;
  overflow-x: auto;
  padding-bottom: var(--spacing-xs);
}

.row {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.row__label {
  width: 1.5rem;
  text-align: center;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.seat {
  width: 2.1rem;
  height: 2.1rem;
  border-radius: var(--radius-sm) var(--radius-sm) var(--radius-md)
    var(--radius-md);
  border: 2px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
  font-size: var(--font-size-sm);
  cursor: pointer;
  transition: transform 0.08s ease, background 0.12s ease;
}

.seat:hover:not(:disabled) {
  transform: translateY(-2px);
  border-color: var(--color-primary);
}

.seat:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.seat--premium {
  border-color: #d9a520;
  background: #fff8e5;
}

.seat--accessible {
  border-color: var(--color-accent);
}

.seat--selected,
.seat--selected.seat--premium,
.seat--selected.seat--accessible {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
  font-weight: 600;
}

.seat--booked,
.seat--booked.seat--premium,
.seat--booked.seat--accessible {
  background: var(--color-border);
  border-color: var(--color-border);
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.seat--taken,
.seat--booked.seat--taken {
  background: var(--color-danger);
  border-color: var(--color-danger);
  color: #fff;
  animation: pulse 0.6s ease 2;
}

.seat:disabled:not(.seat--booked) {
  opacity: 0.45;
  cursor: not-allowed;
}

@keyframes pulse {
  50% {
    transform: scale(1.15);
  }
}

.legend {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--spacing-md);
  list-style: none;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.legend li {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.swatch {
  width: 1.1rem;
  height: 1.1rem;
  cursor: default;
  pointer-events: none;
}
</style>
