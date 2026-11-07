// Test-only process transport. It cannot override the production route's target.
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { resolve } from "node:path";

export async function fastapiFixture() {
  const python = process.env.TRACE_TEST_PYTHON ?? resolve("backend/.venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const env = { PYTHONDONTWRITEBYTECODE: "1" };
  for (const name of ["PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "COMSPEC", "LANG"])
    if (process.env[name]) env[name] = process.env[name];
  const child = spawn(python, ["-B", resolve("tests/fixtures/relay_fastapi.py")], { env, stdio: ["pipe", "pipe", "pipe"] });
  const queued = [], waiters = [];
  let stderr = "", failed;
  child.stderr.on("data", chunk => { stderr = (stderr + chunk).slice(-8192); });
  const fail = error => { failed = error; while (waiters.length) waiters.shift().reject(error); };
  child.on("error", fail);
  child.on("exit", code => { if (code !== 0) fail(new Error(`Offline FastAPI fixture exited ${code}: ${stderr}`)); });
  const lines = createInterface({ input: child.stdout });
  lines.on("line", line => {
    let value;
    try { value = JSON.parse(line); } catch { fail(new Error("Invalid offline fixture protocol")); return; }
    const waiter = waiters.shift(); if (waiter) waiter.resolve(value); else queued.push(value);
  });
  function next() {
    if (failed) return Promise.reject(failed);
    if (queued.length) return Promise.resolve(queued.shift());
    return new Promise((resolve, reject) => waiters.push({ resolve, reject }));
  }
  let timer;
  let ready;
  try {
    ready = await Promise.race([next(), new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error("Offline FastAPI fixture startup deadline")), 20_000);
    })]);
  } catch (error) { child.stdin.end(); child.kill(); lines.close(); throw error; }
  finally { clearTimeout(timer); }
  if (ready.ready !== true) throw new Error("Offline fixture not ready");
  const packet = value => { child.stdin.write(JSON.stringify(value) + "\n"); return next(); };
  return {
    tokens: ready.tokens,
    packet,
    async transport(url, options) {
      const target = new URL(url);
      if (target.origin !== "https://trace-backend-1lio.onrender.com") throw new Error("Unexpected production destination");
      const response = await packet({ path: target.pathname + target.search, method: options.method,
        headers: [...options.headers], body: Buffer.from(options.body ?? []).toString("base64") });
      return new Response(response.status === 204 ? null : Buffer.from(response.body, "base64"),
        { status: response.status, headers: response.headers });
    },
    async close() {
      child.stdin.end();
      if (child.exitCode === null) await new Promise(resolve => child.once("exit", resolve));
      lines.close();
    },
  };
}
