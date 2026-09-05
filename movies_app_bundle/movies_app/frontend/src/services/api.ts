// Typed client for the FastAPI backend (CLAUDE.md §4.5).
// The shapes below mirror backend/models.py one-to-one; keep them in sync.
// Timestamps arrive as ISO-8601 strings in UTC and are displayed as-is.

export interface Movie {
  movie_id: string;
  title: string;
  synopsis: string | null;
  genre: string | null;
  rating: string | null;
  runtime_min: number | null;
  poster_url: string | null;
}

export interface Theater {
  theater_id: string;
  name: string;
  city: string;
  address: string | null;
}

export interface Showtime {
  showtime_id: string;
  movie_id: string;
  auditorium_id: string;
  starts_at: string;
  price_standard: number;
  price_premium: number;
  movie_title: string | null;
  theater_id: string | null;
  theater_name: string | null;
  auditorium_name: string | null;
}

export type SeatType = "standard" | "premium" | "accessible";
export type SeatStatus = "available" | "booked";

export interface SeatDetail {
  seat_id: string;
  seat_number: number;
  seat_type: SeatType;
  price: number;
  status: SeatStatus;
}

export interface SeatRow {
  row_label: string;
  seats: SeatDetail[];
}

export interface SeatMapShowtime {
  showtime_id: string;
  movie_title: string;
  auditorium_name: string;
  starts_at: string;
  price_standard: number;
  price_premium: number;
}

export interface SeatMapResponse {
  showtime: SeatMapShowtime;
  rows: SeatRow[];
}

export interface CreateBookingRequest {
  showtime_id: string;
  seat_ids: string[];
  customer: { name: string; email: string };
}

export interface BookingSeat {
  seat_id: string;
  row_label: string;
  seat_number: number;
  seat_type: SeatType;
  price: number;
}

export interface Booking {
  booking_id: string;
  showtime_id: string;
  customer_name: string;
  customer_email: string;
  status: "CONFIRMED" | "CANCELLED";
  total_amount: number;
  created_at: string;
  cancelled_at: string | null;
  seats: BookingSeat[] | null;
}

/** Body of a 409 from POST /api/bookings: the seats somebody else got first. */
export interface ConflictBody {
  detail: string;
  taken_seat_ids: string[];
}

/**
 * Any non-2xx response. `status` lets callers branch (409 → conflict flow,
 * 422 → validation message); `detail` is always a human-readable string,
 * whether FastAPI sent a plain string or a pydantic error list.
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly body: unknown,
  ) {
    super(detail);
    this.name = "ApiError";
  }

  get takenSeatIds(): string[] {
    const body = this.body as Partial<ConflictBody> | null;
    return this.status === 409 && Array.isArray(body?.taken_seat_ids)
      ? body.taken_seat_ids
      : [];
  }
}

function detailFromBody(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // pydantic validation errors: [{loc: [...], msg: "...", type: "..."}]
    return detail
      .map((d) => {
        const loc = Array.isArray(d?.loc) ? d.loc.slice(1).join(".") : "";
        return loc ? `${loc}: ${d.msg}` : String(d?.msg ?? "");
      })
      .join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { Accept: "application/json", ...(init?.headers ?? {}) },
    });
  } catch (err) {
    throw new ApiError(0, "Network error: could not reach the API", err);
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    throw new ApiError(
      res.status,
      detailFromBody(body, `${res.status} ${res.statusText}`),
      body,
    );
  }
  return body as T;
}

function qs(params: Record<string, string | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) sp.set(k, v);
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  listMovies: () => request<Movie[]>("/api/movies"),
  getMovie: (movieId: string) =>
    request<Movie>(`/api/movies/${encodeURIComponent(movieId)}`),
  listTheaters: () => request<Theater[]>("/api/theaters"),
  listShowtimes: (filters: {
    movie_id?: string;
    theater_id?: string;
    date?: string;
  }) => request<Showtime[]>(`/api/showtimes${qs(filters)}`),
  getSeatMap: (showtimeId: string) =>
    request<SeatMapResponse>(
      `/api/showtimes/${encodeURIComponent(showtimeId)}/seats`,
    ),
  createBooking: (body: CreateBookingRequest) =>
    request<Booking>("/api/bookings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getBooking: (bookingId: string) =>
    request<Booking>(`/api/bookings/${encodeURIComponent(bookingId)}`),
};
