import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { EscalationReviewPanel } from './EscalationReviewPanel'
import { makeAuthenticatedRequest } from '@/lib/auth'
import type { EscalationItem } from './page'
import type React from 'react'

jest.mock('@/lib/auth', () => ({
  makeAuthenticatedRequest: jest.fn(),
}))

jest.mock('sonner', () => ({
  toast: {
    error: jest.fn(),
    success: jest.fn(),
  },
}))

jest.mock('@/components/ui/dialog', () => ({
  Dialog: ({
    children,
    open,
  }: {
    children: React.ReactNode
    open: boolean
  }) => (open ? <div>{children}</div> : null),
  DialogClose: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  DialogContent: ({ children }: { children: React.ReactNode }) => (
    <div role="dialog">{children}</div>
  ),
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}))

jest.mock('@/components/ui/tooltip', () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TooltipTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

jest.mock('lucide-react', () => {
  const Icon = ({ className }: { className?: string }) => (
    <svg className={className} data-testid="icon" />
  )
  return {
    AlertCircle: Icon,
    AlertTriangle: Icon,
    Bot: Icon,
    Check: Icon,
    ChevronDown: Icon,
    Clock: Icon,
    Code2: Icon,
    GitCommit: Icon,
    Loader2: Icon,
    LockKeyhole: Icon,
    MessageSquare: Icon,
    Pencil: Icon,
    Send: Icon,
    ShieldCheck: Icon,
    X: Icon,
    XCircle: Icon,
  }
})

jest.mock('@/components/chat/components/markdown-content', () => ({
  MarkdownContent: ({ content }: { content: string }) => <div>{content}</div>,
}))

jest.mock('@/components/chat/components/source-badges', () => ({
  SourceBadges: ({ sources }: { sources: unknown[] }) => (
    <div data-testid="source-badges">{sources.length} sources</div>
  ),
}))

jest.mock('@/components/chat/components/confidence-badge', () => ({
  ConfidenceBadge: ({ confidence }: { confidence: number }) => (
    <div data-testid="confidence-badge">{Math.round(confidence * 100)}% confidence</div>
  ),
}))

jest.mock('@/components/admin/SimilarFaqsPanel', () => ({
  SimilarFaqsPanel: () => <div data-testid="similar-faqs-panel" />,
}))

const makeAuthenticatedRequestMock =
  makeAuthenticatedRequest as jest.MockedFunction<typeof makeAuthenticatedRequest>

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

function createEscalation(overrides: Partial<EscalationItem> = {}): EscalationItem {
  return {
    id: 42,
    message_id: '12345678-1234-1234-1234-123456789abc',
    channel: 'bisq2',
    user_id: '@alice:bisq.chat',
    username: 'alice',
    channel_metadata: {},
    question: 'Why can I not create a Bisq Easy sell offer?',
    ai_draft_answer: 'Check your Bisq Easy profile and try again.',
    confidence_score: 0.62,
    routing_action: 'needs_human',
    routing_reason: 'Low confidence on protocol-specific support request',
    priority: 'normal',
    status: 'pending',
    sources: [],
    created_at: '2026-06-26T10:00:00Z',
    claimed_at: null,
    responded_at: null,
    closed_at: null,
    ...overrides,
  }
}

const groundingBrief = {
  summary: 'Codebase evidence points to reputation gating in the offer flow.',
  likely_protocol: 'bisq_easy',
  evidence: [
    {
      kind: 'code_fact',
      claim: "Sell offer creation checks the maker's reputation score.",
      support_use: 'Ask whether the account has enough reputation before suggesting a reinstall.',
      audience: 'staff_only',
      repo: 'bisq2',
      commit: 'abc123def456789',
      protocol: 'bisq_easy',
      freshness_class: 'main_branch',
      risk_level: 'medium',
      source_ref: 'code:bisq2@abc123:bisq-easy/src/main/java/Foo.java:10-12',
      source_refs: ['code:bisq2@abc123:bisq-easy/src/main/java/Foo.java:10-12'],
      score: 0.91,
    },
  ],
  safe_customer_guidance: [
    'Ask the customer to confirm their reputation setup before changing app settings.',
  ],
  uncertainties: ['Main-branch behavior may not match older releases.'],
  do_not_say: ['Do not mention internal class names.'],
  staff_enriched_answer:
    'Check your Bisq Easy profile and try again.\n\nStaff-only codebase context:\n- Sell offer creation checks reputation score.',
}

describe('EscalationReviewPanel grounding brief', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    makeAuthenticatedRequestMock.mockResolvedValue(
      jsonResponse({ grounding_brief: groundingBrief })
    )
  })

  test('loads and displays staff-only code grounding in the review flow', async () => {
    render(
      <EscalationReviewPanel
        escalation={createEscalation()}
        open
        onOpenChange={jest.fn()}
        onUpdated={jest.fn()}
      />
    )

    expect(await screen.findByText('Staff-only code grounding')).toBeInTheDocument()
    expect(makeAuthenticatedRequestMock).toHaveBeenCalledWith(
      '/admin/escalations/42/grounding-brief'
    )
    expect(await screen.findByText("Sell offer creation checks the maker's reputation score.")).toBeInTheDocument()
    expect(screen.getByText('Internal enriched answer')).toBeInTheDocument()
    expect(screen.getByText('Not sent')).toBeInTheDocument()
    expect(screen.getByText(/Staff-only codebase context/)).toBeInTheDocument()
    expect(screen.getByText('Ask whether the account has enough reputation before suggesting a reinstall.')).toBeInTheDocument()
    expect(screen.getByText('Ask the customer to confirm their reputation setup before changing app settings.')).toBeInTheDocument()
    expect(screen.getByText('Do not mention internal class names.')).toBeInTheDocument()

    const rawSourceRef = screen.queryByText(/Foo\.java:10-12/)
    if (rawSourceRef) {
      expect(rawSourceRef).not.toBeVisible()
    }

    fireEvent.click(screen.getByRole('button', { name: /source details/i }))

    expect(await screen.findByText(/Foo\.java:10-12/)).toBeVisible()
  })

  test('keeps escalation review usable when grounding cannot be loaded', async () => {
    makeAuthenticatedRequestMock.mockResolvedValueOnce(
      jsonResponse({ detail: 'unavailable' }, 503)
    )

    render(
      <EscalationReviewPanel
        escalation={createEscalation()}
        open
        onOpenChange={jest.fn()}
        onUpdated={jest.fn()}
      />
    )

    expect(await screen.findByText(/Code grounding unavailable/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /send response/i })).toBeEnabled()

    await waitFor(() => {
      expect(makeAuthenticatedRequestMock).toHaveBeenCalledTimes(1)
    })
  })
})
