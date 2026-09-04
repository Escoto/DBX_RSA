<template>
  <div id="app">
    <header class="app-header">
      <h1>Movies Booking</h1>
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
  padding: var(--spacing-md) var(--spacing-xl);
  box-shadow: var(--shadow-sm);
}

.app-header h1 {
  font-size: var(--font-size-lg);
  color: var(--color-primary);
}

.app-main {
  max-width: 1200px;
  margin: 0 auto;
  padding: var(--spacing-lg) var(--spacing-xl);
}
</style>
