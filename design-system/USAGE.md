# Using kone-design-system in a web page project

The `design-system` folder builds as a real installable npm package: components
compiled to JS + type declarations, plus a standalone compiled CSS file so a
consuming project doesn't need Tailwind configured at all.

## Build tooling

- `src/index.ts` -- the library's public entry point, re-exporting everything
  from `components/`
- `tsup.config.ts` -- bundles to `dist/index.js` (ESM), `dist/index.cjs`
  (CJS), and `dist/index.d.ts` (types); `react`/`react-dom` are marked
  external so they don't get duplicated in consumer apps
- `build:css` script -- runs the Tailwind CLI standalone to compile
  `dist/style.css`, containing every utility class the components use (not
  just whatever the demo `App.tsx` happens to render)
- `package.json` -- proper `main`/`module`/`types`/`exports` map,
  `peerDependencies` on react/react-dom, `files: ["dist"]` so only compiled
  output ships

## Build it

```bash
cd design-system
npm run build   # typecheck -> tsup -> tailwind CLI -> dist/
```

## Use it in another web page project

Pick one:

### 1. Local file dependency (simplest, no publishing)

```bash
cd your-web-project
npm install "../KONE Design/design-system"
```

npm will symlink/copy it in. Re-run `npm install` after rebuilding the
library to pick up changes.

### 2. `npm link` for active side-by-side development

```bash
cd design-system && npm link
cd ../your-web-project && npm link kone-design-system
```

### 3. Packed tarball (closest to real publishing)

```bash
cd design-system && npm pack
cd your-web-project && npm install ../design-system/kone-design-system-0.1.0.tgz
```

## Import and use

```tsx
import { Button, Input, Snackbar } from "kone-design-system";
import "kone-design-system/style.css";
```

This full chain (pack a tarball, install it into a throwaway Vite app,
confirm Vite pre-bundles the dependency and both the `Button` export and the
compiled CSS serve correctly) has been verified end-to-end, not just assumed.
