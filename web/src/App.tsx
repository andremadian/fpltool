import { AuthProvider, useAuth } from './hooks/useAuth'
import { ToastProvider } from './components/ToastContext'
import { Login } from './components/Login'
import { Shell } from './components/Shell'
import './App.css'

function Gate() {
  const { session, loading } = useAuth()

  if (loading) return <div className="app-loading">loading…</div>

  return session ? <Shell /> : <Login />
}

function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </ToastProvider>
  )
}

export default App
