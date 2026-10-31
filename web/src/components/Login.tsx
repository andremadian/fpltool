import { useState, type FormEvent } from 'react'
import { supabase } from '../lib/supabaseClient'
import { useToast } from './ToastContext'

type Phase = 'enter-email' | 'sending' | 'awaiting-code' | 'verifying'

export function Login() {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [phase, setPhase] = useState<Phase>('enter-email')
  const { showError } = useToast()

  async function sendLoginEmail(e: FormEvent) {
    e.preventDefault()
    setPhase('sending')
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: window.location.origin,
        shouldCreateUser: false,
      },
    })
    if (error) {
      showError(error.message)
      setPhase('enter-email')
      return
    }
    setPhase('awaiting-code')
  }

  async function verifyCode(e: FormEvent) {
    e.preventDefault()
    setPhase('verifying')
    const { error } = await supabase.auth.verifyOtp({
      email,
      token: code,
      type: 'email',
    })
    if (error) {
      showError(error.message)
      setPhase('awaiting-code')
    }
    // On success, useAuth's onAuthStateChange picks up the new session.
  }

  return (
    <div className="login-screen">
      <div className="login-pitch" aria-hidden="true" />

      <div className="login-brand">
        <CrosshairMark />
        <h1>FPL Sniper</h1>
        <p className="login-tagline">
          Transfers, best XI, captain and your mini-league — one brief, every
          gameweek.
        </p>
      </div>

      <div className="login-card">
        {phase === 'enter-email' || phase === 'sending' ? (
          <form onSubmit={sendLoginEmail}>
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={phase === 'sending'}
            />
            <button type="submit" className="login-primary" disabled={phase === 'sending'}>
              {phase === 'sending' ? 'Sending…' : 'Send login link'}
            </button>
          </form>
        ) : (
          <form onSubmit={verifyCode}>
            <p className="login-sent">
              Link sent to <strong>{email}</strong>. Open it on this device, or
              enter the code from the email — the code works inside the
              installed app.
            </p>
            <label htmlFor="code">Login code</label>
            <input
              id="code"
              className="login-code"
              inputMode="numeric"
              pattern="[0-9]{6,10}"
              maxLength={10}
              required
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              disabled={phase === 'verifying'}
            />
            <button type="submit" className="login-primary" disabled={phase === 'verifying'}>
              {phase === 'verifying' ? 'Verifying…' : 'Verify code'}
            </button>
            <button type="button" className="login-link" onClick={() => setPhase('enter-email')}>
              Use a different email
            </button>
          </form>
        )}
      </div>

      <p className="login-footnote">Invite only · no password, just a magic link</p>
    </div>
  )
}

function CrosshairMark() {
  return (
    <svg className="login-mark" viewBox="0 0 48 48" aria-hidden="true">
      <circle cx="24" cy="24" r="17" fill="none" stroke="currentColor" strokeWidth="2.5" />
      <circle cx="24" cy="24" r="8" fill="none" stroke="currentColor" strokeWidth="2.5" />
      <circle cx="24" cy="24" r="2.5" fill="currentColor" />
      <path d="M24 2v10M24 36v10M2 24h10M36 24h10" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}
