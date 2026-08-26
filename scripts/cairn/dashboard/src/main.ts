// PT-54 (architect ruling §2): self-hosted fonts, imported as JS
// side-effect imports (default entry only -- wght axis, normal style, all
// unicode subsets, font-display: swap) so `@import "tailwindcss";` can
// stay first in app.css, which Tailwind v4 requires.
import '@fontsource-variable/merriweather';
import '@fontsource-variable/space-grotesk';
import '@fontsource-variable/geist-mono';

import { mount } from 'svelte';
import './app.css';
import App from './App.svelte';

const app = mount(App, {
	target: document.getElementById('app')!,
});

export default app;
