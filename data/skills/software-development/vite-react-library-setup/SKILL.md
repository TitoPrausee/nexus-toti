---
name: vite-react-library-setup
description: Set up Vite 5 library mode for a React component library — ESM + CJS dual output, CSS bundling, proper package.json exports map, private=false for npm publish.
version: 1.0.0
author: Hermes Agent
---

# Vite React Library Build Setup

## Überblick
Konvertiert ein React-Projekt ohne Build-System in eine publishbare npm-Bibliothek mit Vite 5 Library Mode. Produziert ESM (.mjs) + CJS (.cjs) Dual-Output und bundled CSS automatisch.

## Wann verwenden
- React-Komponenten-Bibliothek hat noch kein Build-System
- `.js`-Dateien enthalten JSX aber es gibt keine Transpilierung
- `package.json` hat `"main": "./src/index.js"` (funktioniert nicht für Konsumenten ohne eigenen Build-Step)
- Package muss als npm-Bibliothek publishbar sein

## Schritt-für-Schritt

### 1. Vite installieren
```bash
cd /path/to/project
npm install --save-dev vite@5 @vitejs/plugin-react@4
```

### 2. vite.config.js erstellen
```js
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    lib: {
      entry: 'src/index.js',
      name: 'LibraryName',
      formats: ['es', 'cjs'],
      fileName: (fmt) => `index.${fmt === 'es' ? 'mjs' : 'cjs'}`
    },
    rollupOptions: {
      external: ['react', 'react-dom'],
      output: {
        globals: { react: 'React', reactDOM: 'ReactDOM' }
      }
    },
    cssCodeSplit: false
  }
});
```

### 3. CSS import in der Entry-Datei
Die `src/index.js` MUSS das CSS importieren, sonst wird es nicht gebundelt:
```js
import './styles.css';

export { ComponentA } from './components/ComponentA';
// ...
```

### 4. package.json updaten
```json
{
  "type": "module",
  "main": "./dist/index.cjs",
  "module": "./dist/index.mjs",
  "exports": {
    ".": {
      "import": "./dist/index.mjs",
      "require": "./dist/index.cjs"
    },
    "./styles": "./dist/style.css"
  },
  "files": ["dist", "README.md", "LICENSE"],
  "scripts": {
    "dev": "vite build --watch",
    "build": "vite build",
    "prepublishOnly": "npm run build"
  },
  "private": false
}
```

### 5. .gitignore updaten
```gitignore
/node_modules
/dist
```

### 6. Build testen
```bash
npm run build
# Expected output:
# dist/index.mjs   # ESM version
# dist/index.cjs   # CJS version
# dist/style.css   # Bundled CSS
```

### 7. Commit + Release
```bash
git add -A
git commit -m "feat: add Vite build system with ESM/CJS + CSS bundle (Closes #1)"
git push
git tag v2.0.0
git push origin v2.0.0
# Create GitHub Release via API
```

## Wichtige Details
- `cssCodeSplit: false` = ALLE CSS in eine Datei (style.css), sonst pro Component split
- `external: ['react', 'react-dom']` = React nicht mit-bundlen (bleibt peer dep)
- `formats: ['es', 'cjs']` = modern (ESM) + legacy (CJS) Support
- Ohne CSS-Import in `index.js` wird kein style.css generiert!
- `files: ["dist"]` in package.json = nur dist/ published, kein src/
- `private: false` = npm publish erlaubt (vorher war true)

## Pitfalls
- Wenn `cssCodeSplit: true` (default), kommt CSS als separater Chunk pro Component — schwer zu konsumieren. Immer auf `false` setzen für Bibliotheken.
- `package-lock.json` nicht in .gitignore — die gehört in git für reproduzierbare Builds
- Ohne `type: "module"` in package.json importiert Node CJS by default
- `"exports"` Map ist strikt — nur die angegebenen Pfade sind importierbar, `./components/*` Wildcards gehen nicht in modernen Bundlern
- Bei `"private": false` in package.json: vor dem ersten npm publish ggf. `npm login` ausführen
