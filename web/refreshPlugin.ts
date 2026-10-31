import { spawn } from 'node:child_process'
import { createWriteStream, mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Plugin } from 'vite'

/**
 * Dev-server endpoint behind the app's Refresh button: POST /api/refresh runs
 * the daily light ingest and then rebuilds the weekly brief, the same two
 * engines launchd runs every morning. It exists only while `vite` serves the
 * app on this Mac — a production build has no server to run Python on.
 */

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const PYTHON = join(REPO_ROOT, '.venv', 'bin', 'python')
// Same log the scheduled runs append to. Never inside ~/Documents (decision #12).
const LOG_PATH = join(homedir(), 'Library', 'Logs', 'fplsniper', 'cron.log')

const STEPS = [
  { name: 'daily ingest', args: ['fpl_engine.py', '--daily'] },
  { name: 'weekly brief', args: ['fpl_brief_engine.py'] },
] as const

interface StepResult {
  name: string
  ok: boolean
  seconds: number
}

/** Run one engine to completion, appending its output to the shared log. */
function runStep(args: readonly string[], log: NodeJS.WritableStream): Promise<{ ok: boolean; tail: string }> {
  return new Promise((done) => {
    const child = spawn(PYTHON, args, { cwd: REPO_ROOT })
    let tail = ''
    const capture = (chunk: Buffer) => {
      log.write(chunk)
      tail = (tail + chunk.toString()).slice(-2000)
    }
    child.stdout.on('data', capture)
    child.stderr.on('data', capture)
    child.on('error', (err) => done({ ok: false, tail: err.message }))
    child.on('close', (code) => done({ ok: code === 0, tail }))
  })
}

/** The last line that looks like an error, for the toast when a step fails. */
function errorLine(tail: string): string {
  const lines = tail.trim().split('\n').filter(Boolean)
  return [...lines].reverse().find((l) => /error|failed|exception/i.test(l)) ?? lines.at(-1) ?? 'no output'
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(body))
}

/** Only the app itself may trigger a run: reject cross-site POSTs from other pages. */
function isSameOrigin(req: IncomingMessage): boolean {
  const origin = req.headers.origin
  return !!origin && !!req.headers.host && new URL(origin).host === req.headers.host
}

export function refreshPlugin(): Plugin {
  let running = false

  return {
    name: 'fplsniper-refresh',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/api/refresh', async (req, res) => {
        if (req.method !== 'POST') return sendJson(res, 405, { ok: false, error: 'POST only' })
        if (!isSameOrigin(req)) return sendJson(res, 403, { ok: false, error: 'cross-origin request refused' })
        if (running) return sendJson(res, 409, { ok: false, error: 'a refresh is already running' })

        running = true
        mkdirSync(dirname(LOG_PATH), { recursive: true })
        const log = createWriteStream(LOG_PATH, { flags: 'a' })
        log.write(`\n=== manual refresh from the app, ${new Date().toISOString()} ===\n`)
        const steps: StepResult[] = []
        try {
          for (const step of STEPS) {
            const started = Date.now()
            const { ok, tail } = await runStep(step.args, log)
            steps.push({ name: step.name, ok, seconds: Math.round((Date.now() - started) / 1000) })
            if (!ok) {
              return sendJson(res, 500, { ok: false, steps, error: `${step.name} failed: ${errorLine(tail)}` })
            }
          }
          sendJson(res, 200, { ok: true, steps })
        } finally {
          log.end()
          running = false
        }
      })
    },
  }
}
