# Vendored Monaco Editor

- Package: `monaco-editor@0.44.0`
- Source: npm tarball `monaco-editor-0.44.0.tgz`
- Vendored path: `min/vs` → `web/vendor/monaco/vs`
- License: MIT (`LICENSE`, `ThirdPartyNotices.txt`)

The app is a no-build, classic-script frontend. The AMD loader is injected
lazily on the first file edit, so the workbench does not pay the ~12 MB
editor cost at page load. If the loader, the module, or the worker fails, the
existing textarea editor is used and a single diagnostic is shown.

To refresh:

```powershell
npm pack monaco-editor@0.44.0
tar -xzf monaco-editor-0.44.0.tgz
Copy-Item -Recurse -Force package\min\vs web\vendor\monaco\vs
```
