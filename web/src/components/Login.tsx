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
      <h1>FPL Sniper</h1>

      {phase === 'enter-email' || phase === 'sending' ? (
        <form onSubmit={sendLoginEmail}>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={phase === 'sending'}
          />
          <button type="submit" disabled={phase === 'sending'}>
            {phase === 'sending' ? 'Sending…' : 'Send login email'}
          </button>
        </form>
      ) : (
        <form onSubmit={verifyCode}>
          <p>
            Check your email for a link to sign in, or enter the login code
            below — the code works from inside the installed app.
          </p>
          <label htmlFor="code">Login code</label>
          <input
            id="code"
            inputMode="numeric"
            pattern="[0-9]{6,10}"
            maxLength={10}
            required
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
            disabled={phase === 'verifying'}
          />
          <button type="submit" disabled={phase === 'verifying'}>
            {phase === 'verifying' ? 'Verifying…' : 'Verify code'}
          </button>
          <button type="button" onClick={() => setPhase('enter-email')}>
            Use a different email
          </button>
        </form>
      )}
    </div>
  )
}
