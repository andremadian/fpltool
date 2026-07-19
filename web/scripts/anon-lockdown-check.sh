#!/usr/bin/env bash
# Repeatable curl checklist for the anon-key lockdown (Phase 3B brief, done
# criterion 2 / loophole #1). Confirms the anon key — the one that ships in
# this PWA's JS bundle by definition — gets zero read and zero write access
# once migration 0008's lockdown is applied. Re-run after any RLS/policy
# change to the schema.
#
# Usage: web/scripts/anon-lockdown-check.sh
# Reads VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY from web/.env.local.

set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env.local ]; then
  echo "web/.env.local not found — copy .env.example and fill in real values first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source <(grep -E '^VITE_(SUPABASE_URL|SUPABASE_ANON_KEY)=' .env.local)

if [ -z "${VITE_SUPABASE_URL:-}" ] || [ -z "${VITE_SUPABASE_ANON_KEY:-}" ]; then
  echo "VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY missing from web/.env.local." >&2
  exit 1
fi

echo "== 1. anon SELECT on players_master (expect: empty array or permission error) =="
curl -s "${VITE_SUPABASE_URL}/rest/v1/players_master?select=id&limit=1" \
  -H "apikey: ${VITE_SUPABASE_ANON_KEY}" \
  -H "Authorization: Bearer ${VITE_SUPABASE_ANON_KEY}"
echo

echo "== 2. anon INSERT into players_master (expect: 401/403 rejection) =="
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST \
  "${VITE_SUPABASE_URL}/rest/v1/players_master" \
  -H "apikey: ${VITE_SUPABASE_ANON_KEY}" \
  -H "Authorization: Bearer ${VITE_SUPABASE_ANON_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"id": 999999, "web_name": "lockdown-check", "position": "MID", "price": 4.0}'

echo "== 3. anon UPSERT/UPDATE on players_master (expect: 401/403 rejection) =="
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X PATCH \
  "${VITE_SUPABASE_URL}/rest/v1/players_master?id=eq.1" \
  -H "apikey: ${VITE_SUPABASE_ANON_KEY}" \
  -H "Authorization: Bearer ${VITE_SUPABASE_ANON_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"web_name": "lockdown-check"}'

echo
echo "Expected: (1) an empty JSON array (RLS silently filters rows) or a permission-denied"
echo "error; (2) and (3) both HTTP 401 or 403. Any 2xx/200 on the writes means the"
echo "lockdown migration (0008) hasn't been applied or didn't take — stop and investigate"
echo "before deploying."
