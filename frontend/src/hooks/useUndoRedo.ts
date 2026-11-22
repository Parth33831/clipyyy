import { useCallback, useRef, useState } from 'react'

type HistoryState<T> = {
  past: T[]
  present: T
  future: T[]
}

type HistoryValue<T> = T | ((previous: T) => T)

export function useUndoRedo<T>(initialValue: T, limit = 40, coalesceMs = 1000) {
  const [history, setHistory] = useState<HistoryState<T>>({
    past: [],
    present: initialValue,
    future: [],
  })
  const lastChangeAt = useRef(0)

  const set = useCallback((next: HistoryValue<T>) => {
    const now = Date.now()
    setHistory((current) => {
      const present = typeof next === 'function'
        ? (next as (previous: T) => T)(current.present)
        : next
      if (Object.is(present, current.present)) return current
      const coalesce = now - lastChangeAt.current < coalesceMs
      lastChangeAt.current = now
      return {
        past: coalesce ? current.past : [...current.past, current.present].slice(-limit),
        present,
        future: [],
      }
    })
  }, [coalesceMs, limit])

  const reset = useCallback((value: T) => {
    lastChangeAt.current = 0
    setHistory({ past: [], present: value, future: [] })
  }, [])

  const undo = useCallback(() => {
    lastChangeAt.current = 0
    setHistory((current) => {
      if (current.past.length === 0) return current
      const present = current.past[current.past.length - 1]
      return {
        past: current.past.slice(0, -1),
        present,
        future: [current.present, ...current.future],
      }
    })
  }, [])

  const redo = useCallback(() => {
    lastChangeAt.current = 0
    setHistory((current) => {
      if (current.future.length === 0) return current
      const present = current.future[0]
      return {
        past: [...current.past, current.present].slice(-limit),
        present,
        future: current.future.slice(1),
      }
    })
  }, [limit])

  return {
    value: history.present,
    set,
    reset,
    undo,
    redo,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
  }
}
