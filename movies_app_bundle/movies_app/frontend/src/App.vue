<template>
  <div id="app">
    <header class="app-header">
      <div class="app-header__inner">
        <router-link to="/" class="brand">
          <span class="brand__mark" aria-hidden="true">▶</span>
          <span class="brand__name">Movies Booking</span>
        </router-link>
        <span class="tagline">Databricks App · Lakebase</span>
      </div>
    </header>
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.app-header {
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  box-shadow: var(--shadow-sm);
}

.app-header__inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: var(--spacing-md) var(--spacing-xl);
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--spacing-md);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-sm);
  text-decoration: none;
  color: var(--color-primary);
  font-size: var(--font-size-lg);
  font-weight: 600;
}

.brand__mark {
  display: inline-grid;
  place-items: center;
  width: 1.6rem;
  height: 1.6rem;
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  color: #fff;
  font-size: 0.75rem;
}

.tagline {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}

.app-main {
  max-width: 1200px;
  margin: 0 auto;
  padding: var(--spacing-lg) var(--spacing-xl);
}

@media (max-width: 640px) {
  .app-header__inner,
  .app-main {
    padding-left: var(--spacing-md);
    padding-right: var(--spacing-md);
  }
  .tagline {
    display: none;
  }
}
</style>
