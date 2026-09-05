import { createRouter, createWebHistory } from "vue-router";

// Four routes, one per step of the booking funnel (CLAUDE.md §4.5).
// History mode: the backend serves index.html for any non-/api path.
export const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    {
      path: "/",
      name: "movies",
      component: () => import("./views/MoviesView.vue"),
    },
    {
      path: "/movies/:id",
      name: "movie",
      component: () => import("./views/MovieView.vue"),
      props: true,
    },
    {
      path: "/showtimes/:id",
      name: "showtime",
      component: () => import("./views/ShowtimeView.vue"),
      props: true,
    },
    {
      path: "/bookings/:id",
      name: "booking",
      component: () => import("./views/BookingView.vue"),
      props: true,
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
