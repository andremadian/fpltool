import { useEffect, useState, type DependencyList } from 'react'
import type { PostgrestError } from '@supabase/supabase-js'
import { useToast } from '../components/ToastContext'

export type QueryState<T> =
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'empty' }
  | { status: 'data'; data: T[] }

/**
 * Every tab needs the same three states (loading / data / empty) plus a
 * visible-toast error surface instead of a silent console failure — this
 * hook is the one place that logic lives.
 */
export function useSupabaseQuery<T>(
  queryFn: () => PromiseLike<{ data: T[] | null; error: PostgrestError | null }>,
  deps: DependencyList,
): QueryState<T> {
  const [state, setState] = useState<QueryState<T>>({ status: 'loading' })
  const { showError } = useToast()

  useEffect(() => {
    let cancelled = false
    setState({ status: 'loading' })

    queryFn().then(({ data, error }) => {
      if (cancelled) return
      if (error) {
        setState({ status: 'error', error: error.message })
        showError(error.message)
        return
      }
      if (!data || data.length === 0) {
        setState({ status: 'empty' })
        return
      }
      setState({ status: 'data', data })
    })

    return () => {
      cancelled = true
    }
    // deps is caller-controlled and intentionally the effect's only trigger
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return state
}
