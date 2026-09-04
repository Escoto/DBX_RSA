<template>
  <div class="page">
    <header class="hero">
      <h1>GxP Validation Platform</h1>
      <p class="subtitle">Vue.js Feasibility Test on Databricks Apps</p>
    </header>

    <main class="content">
      <section class="card">
        <h2>What is this?</h2>
        <p>
          This is a lightweight Vue 3 + Vite application deployed as a
          <strong>Databricks App</strong> to evaluate whether a Node-based
          frontend can replace the current Streamlit UI for the GxP Validation
          Document Analysis Platform.
        </p>
      </section>

      <section class="card">
        <h2>What we are testing</h2>
        <ul>
          <li>Vue 3 SPA renders correctly inside a Databricks App container</li>
          <li>CSS design tokens propagate through components</li>
          <li>Vite build + preview serves on the expected port (<code>8080</code>)</li>
          <li>Bundle deployment works alongside the existing Streamlit app</li>
        </ul>
      </section>

      <section class="card">
        <h2>Design Tokens Preview</h2>
        <div class="token-grid">
          <div class="swatch" style="background: var(--color-primary)">primary</div>
          <div class="swatch" style="background: var(--color-accent); color: #fff">accent</div>
          <div class="swatch" style="background: var(--color-danger); color: #fff">danger</div>
          <div class="swatch" style="background: var(--color-text); color: #fff">text</div>
          <div class="swatch" style="background: var(--color-text-muted); color: #fff">muted</div>
          <div class="swatch" style="background: var(--color-border)">border</div>
        </div>
      </section>

      <section class="card">
        <h2>Reactive counter (Vue sanity check)</h2>
        <p>
          <button class="btn" @click="count++">Clicked {{ count }} times</button>
        </p>
      </section>
    </main>

    <footer class="footer">
      <p>
        Built with Vue {{ vueVersion }} + Vite &middot; Deployed via
        Databricks Asset Bundles
      </p>
    </footer>
  </div>
</template>

<script setup>
import { ref, version as vueVersion } from "vue";

const count = ref(0);
</script>

<style scoped>
.page {
  max-width: 760px;
  margin: 0 auto;
  padding: var(--spacing-xl) var(--spacing-md);
}

.hero {
  text-align: center;
  margin-bottom: var(--spacing-xl);
}

.hero h1 {
  font-size: var(--font-size-xxl);
  color: var(--color-primary);
}

.subtitle {
  font-size: var(--font-size-lg);
  color: var(--color-text-muted);
  margin-top: var(--spacing-xs);
}

.content {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
}

.card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--spacing-lg);
  box-shadow: var(--shadow-sm);
}

.card h2 {
  font-size: var(--font-size-lg);
  margin-bottom: var(--spacing-sm);
}

.card ul {
  padding-left: var(--spacing-lg);
}

.card li {
  margin-bottom: var(--spacing-xs);
}

.token-grid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
  margin-top: var(--spacing-sm);
}

.swatch {
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  color: #fff;
  min-width: 80px;
  text-align: center;
}

.btn {
  background: var(--color-primary);
  color: #fff;
  border: none;
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-base);
  cursor: pointer;
  transition: background 0.15s;
}

.btn:hover {
  background: var(--color-primary-hover);
}

.footer {
  text-align: center;
  margin-top: var(--spacing-xl);
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}
</style>
