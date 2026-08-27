import path from 'node:path';
import { fileURLToPath } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

const dirname = path.dirname(fileURLToPath(import.meta.url));

// PT-54 (architect ruling §1/§4): two settings here are not optional.
//
// - `base: '/dashboard/'` -- the board server mounts the built app under
//   that prefix (scripts/cairn/cairn.py's do_GET), so every emitted asset
//   URL must be absolute under it or a relative reference (e.g. a nested
//   route) would resolve against the wrong path.
// - `rollupOptions.output.*FileNames` set to stable `[name]` forms, no
//   content hash -- the server already sends `Cache-Control: no-store` on
//   every dashboard asset (matching board.js/board.css's existing
//   PT-49 §7 policy), so a hash buys nothing and would make the committed
//   `dist/` grow monotonically with every rebuild (architect ruling §3).
//
// `server.proxy` only matters for `npm run dev` (never touches `build`) --
// it lets the Vite dev server forward /api/* to the real cairn board
// server on 8766 so local dashboard development runs against real data.
export default defineConfig({
	plugins: [tailwindcss(), svelte()],
	base: '/dashboard/',
	resolve: {
		alias: {
			$lib: path.resolve(dirname, './src/lib'),
		},
	},
	build: {
		rollupOptions: {
			output: {
				entryFileNames: 'assets/[name].js',
				chunkFileNames: 'assets/[name].js',
				assetFileNames: 'assets/[name].[ext]',
			},
		},
	},
	server: {
		proxy: {
			'/api': 'http://127.0.0.1:8766',
		},
	},
});
