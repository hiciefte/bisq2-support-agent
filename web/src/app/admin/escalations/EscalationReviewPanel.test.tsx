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
      id: 'bisq2:abc123:Foo.reputation:10',
      kind: 'code_fact',
      type: 'code_fact',
      claim: "Sell offer creation checks the maker's reputation score.",
      support_use: 'Ask whether the account has enough reputation before suggesting a reinstall.',
      audience: 'staff_only',
      repo: 'bisq2',
      commit: 'abc123def456789',
      path: 'bisq-easy/src/main/java/Foo.java',
      line_start: 10,
      line_end: 12,
      symbol: 'Foo.reputation',
      protocol: 'bisq_easy',
      freshness_class: 'main_branch',
      risk_level: 'medium',
      public_guidance:
        'Ask the customer to confirm their reputation setup before changing app settings.',
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
    expect(screen.queryByText('Customer-safe draft')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /use as response draft/i })).not.toBeInTheDocument()
    expect(screen.getByText(/Staff-only codebase context/)).toBeInTheDocument()
    expect(screen.getByText('Ask whether the account has enough reputation before suggesting a reinstall.')).toBeInTheDocument()
    expect(
      screen.getAllByText('Ask the customer to confirm their reputation setup before changing app settings.').length
    ).toBeGreaterThan(0)
    expect(screen.getByText('Do not mention internal class names.')).toBeInTheDocument()

    const rawSourceRef = screen.queryByText(/Foo\.java:10-12/)
    if (rawSourceRef) {
      expect(rawSourceRef).not.toBeVisible()
    }

    fireEvent.click(screen.getByRole('button', { name: /source details/i }))

    expect(await screen.findByText(/Foo\.java:10-12/)).toBeVisible()
  })

  test('does not expose staff-only code guidance as a sendable response draft', async () => {
    makeAuthenticatedRequestMock.mockResolvedValueOnce(
      jsonResponse({
        grounding_brief: {
          ...groundingBrief,
          customer_safe_draft:
            'This stale field must not become editable customer response text.',
        },
      })
    )

    render(
      <EscalationReviewPanel
        escalation={createEscalation()}
        open
        onOpenChange={jest.fn()}
        onUpdated={jest.fn()}
      />
    )

    expect(await screen.findByText('Staff-only code grounding')).toBeInTheDocument()
    expect(screen.queryByText('Customer-safe draft')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /use as response draft/i })).not.toBeInTheDocument()
    expect(
      screen.queryByText('This stale field must not become editable customer response text.')
    ).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }))
    expect(screen.getByRole('textbox', { name: /suggested answer/i })).toHaveValue(
      'Check your Bisq Easy profile and try again.'
    )
  })

  test('drafts an LLM Wiki proposal from code grounding evidence', async () => {
    render(
      <EscalationReviewPanel
        escalation={createEscalation()}
        open
        onOpenChange={jest.fn()}
        onUpdated={jest.fn()}
      />
    )

    const draftButton = await screen.findByRole('button', {
      name: /draft llm wiki proposal/i,
    })
    fireEvent.click(draftButton)

    await waitFor(() => {
      expect(makeAuthenticatedRequestMock).toHaveBeenCalledWith(
        '/admin/knowledge-updates/code-evidence/proposals',
        expect.objectContaining({ method: 'POST' })
      )
    })
    const promotionCall = makeAuthenticatedRequestMock.mock.calls.find(
      ([path]) => path === '/admin/knowledge-updates/code-evidence/proposals'
    )
    expect(promotionCall).toBeDefined()
    const payload = JSON.parse(String(promotionCall?.[1]?.body))
    expect(payload.question).toBe('Why can I not create a Bisq Easy sell offer?')
    expect(payload.public_guidance).toContain('confirm their reputation setup')
    expect(payload.evidence.id).toBe('bisq2:abc123:Foo.reputation:10')
    expect(payload.evidence.source_refs).toEqual([
      'code:bisq2@abc123:bisq-easy/src/main/java/Foo.java:10-12',
    ])

    expect(await screen.findByRole('button', { name: /proposal drafted/i })).toBeDisabled()
  })

  test('allows drafting code evidence proposals when symbol is absent', async () => {
    makeAuthenticatedRequestMock.mockResolvedValueOnce(
      jsonResponse({
        grounding_brief: {
          ...groundingBrief,
          evidence: groundingBrief.evidence.map((item) => ({
            ...item,
            symbol: null,
          })),
        },
      })
    )

    render(
      <EscalationReviewPanel
        escalation={createEscalation()}
        open
        onOpenChange={jest.fn()}
        onUpdated={jest.fn()}
      />
    )

    expect(
      await screen.findByRole('button', { name: /draft llm wiki proposal/i })
    ).toBeEnabled()
  })

  test('requires customer-safe guidance before drafting from raw code evidence', async () => {
    const briefWithoutGuidance = {
      ...groundingBrief,
      evidence: groundingBrief.evidence.map((item) => {
        const evidenceItem: Partial<(typeof groundingBrief.evidence)[number]> = { ...item }
        delete evidenceItem.public_guidance
        return evidenceItem
      }),
    }
    makeAuthenticatedRequestMock.mockResolvedValueOnce(
      jsonResponse({ grounding_brief: briefWithoutGuidance })
    )

    render(
      <EscalationReviewPanel
        escalation={createEscalation()}
        open
        onOpenChange={jest.fn()}
        onUpdated={jest.fn()}
      />
    )

    expect(await screen.findByLabelText(/customer-safe guidance/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /draft llm wiki proposal/i })).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/customer-safe guidance/i), {
      target: {
        value:
          'Ask the customer to check whether their profile has enough reputation before retrying the sell offer.',
      },
    })
    fireEvent.click(screen.getByRole('button', { name: /draft llm wiki proposal/i }))

    await waitFor(() => {
      expect(makeAuthenticatedRequestMock).toHaveBeenCalledWith(
        '/admin/knowledge-updates/code-evidence/proposals',
        expect.objectContaining({ method: 'POST' })
      )
    })
    const promotionCall = makeAuthenticatedRequestMock.mock.calls.find(
      ([path]) => path === '/admin/knowledge-updates/code-evidence/proposals'
    )
    const payload = JSON.parse(String(promotionCall?.[1]?.body))
    expect(payload.public_guidance).toContain('enough reputation')
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
