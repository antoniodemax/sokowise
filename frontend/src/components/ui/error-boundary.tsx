import { Component, type ErrorInfo, type ReactNode } from 'react'

import { ErrorState } from './error-state'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * Last line of defence for a render-time exception: the shell and navigation stay usable
 * and the section can be retried, instead of the whole app going blank.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('render error', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return <ErrorState error={new Error('This screen hit a problem it could not recover from.')} title="Something went wrong" onRetry={() => this.setState({ error: null })} />
    }
    return this.props.children
  }
}
