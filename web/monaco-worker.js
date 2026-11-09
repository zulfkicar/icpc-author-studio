/*
 * Same-origin Monaco worker entry point.
 *
 * The workbench CSP does not allow blob:/data: workers. Monaco's AMD worker
 * bootstrap is designed to be wrapped exactly like this: point it at the
 * vendored `vs` root and load the worker main script.
 */
self.MonacoEnvironment = {
  baseUrl: self.location.origin + "/vendor/monaco/vs/",
};
importScripts("/vendor/monaco/vs/base/worker/workerMain.js");
