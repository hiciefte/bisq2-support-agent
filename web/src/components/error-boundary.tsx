"use client"

import { Component, ErrorInfo, ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { AlertTriangle } from "lucide-react"

interface Props {
    children: ReactNode
    fallback?: ReactNode
}

interface State {
    hasError: boolean
    error?: Error
}

export class ErrorBoundary extends Component<Props, State> {
    state: State = { hasError: false }

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error }
    }

    componentDidCatch(error: Error, errorInfo: ErrorInfo) {
        if (process.env.NODE_ENV !== 'production') {
            console.error("ErrorBoundary caught:", error, errorInfo)
        }
    }

    render() {
        if (this.state.hasError) {
            return this.props.fallback || (
                <div className="flex flex-col items-center justify-center p-8 text-center">
                    <AlertTriangle className="h-12 w-12 text-destructive mb-4" aria-hidden="true" />
                    <h2 className="text-lg font-semibold mb-2">Something went wrong</h2>
                    <p className="text-muted-foreground mb-4">
                        An error occurred while rendering this section.
                    </p>
                    <Button onClick={() => this.setState({ hasError: false, error: undefined })}>
                        Try again
                    </Button>
                </div>
            )
        }
        return this.props.children
    }
}
