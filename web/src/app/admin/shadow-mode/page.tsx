"use client"

import { useState, useEffect, useCallback, useRef } from 'react';
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { toast as sonnerToast } from "sonner";
import { useHotkeys } from "react-hotkeys-hook";
import {
  Loader2,
  MessageCircle,
  MessageSquare,
  CheckCircle,
  XCircle,
  Edit,
  X,
  Trash2,
  Clock,
  TrendingUp,
  Target,
  RefreshCw,
  AlertTriangle,
  SkipForward,
  ChevronDown,
  Check
} from 'lucide-react';
import { makeAuthenticatedRequest } from '@/lib/auth';
import { cn } from "@/lib/utils";

// V2 Interfaces
interface Message {
  content: string;
  timestamp: string;
  sender_type: string;
  message_id: string;
}

interface Source {
  title: string;
  type: string;
  content: string;
  bisq_version: string;
}

interface ShadowResponse {
  id: string;
  channel_id: string;
  user_id: string;
  messages: Message[];
  synthesized_question: string | null;
  detected_version: string | null;
  version_confidence: number;
  detection_signals: Record<string, number>;
  confirmed_version: string | null;
  version_change_reason: string | null;
  // Unknown version enhancement fields
  training_version: string | null;
  requires_clarification: boolean;
  clarifying_question: string | null;
  source: string;
  clarification_answer: string | null;
  // Response generation fields
  generated_response: string | null;
  sources: Source[];
  edited_response: string | null;
  confidence: number | null;
  routing_action: string | null;
  status: string;
  rag_error: string | null;
  retry_count: number;
  created_at: string;
  updated_at: string;
  version_confirmed_at: string | null;
  response_generated_at: string | null;
}

interface ShadowStats {
  total: number;
  pending_version_review: number;
  pending_response_review: number;
  rag_failed: number;
  approved: number;
  edited: number;
  rejected: number;
  skipped: number;
  avg_confidence: number;
}

// Helper functions
const formatVersionLabel = (version: string | null): string => {
  if (!version) return 'Unknown';
  switch (version.toLowerCase()) {
    case 'bisq2':
      return 'Bisq 2';
    case 'bisq1':
      return 'Bisq 1';
    case 'unknown':
      return 'Unknown';
    default:
      return version;
  }
};

const getConfidenceColor = (confidence: number) => {
  if (confidence >= 0.8) return 'bg-green-500';
  if (confidence >= 0.5) return 'bg-yellow-500';
  return 'bg-red-500';
};

const getConfidenceTextColor = (confidence: number) => {
  if (confidence >= 0.8) return 'text-green-600';
  if (confidence >= 0.5) return 'text-yellow-600';
  return 'text-red-600';
};

const getConfidenceLabel = (confidence: number) => {
  if (confidence >= 0.8) return 'High';
  if (confidence >= 0.5) return 'Medium';
  return 'Low';
};

const getRoutingBadgeStyle = (routing: string | null) => {
  switch (routing) {
    case 'auto_send':
      return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400';
    case 'queue_medium':
      return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400';
    case 'needs_human':
      return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400';
    default:
      return 'bg-gray-100 text-gray-800 dark:bg-gray-800/50 dark:text-gray-400';
  }
};

const getRoutingLabel = (routing: string | null) => {
  switch (routing) {
    case 'auto_send':
      return 'Auto-Send';
    case 'queue_medium':
      return 'Review';
    case 'needs_human':
      return 'Escalate';
    default:
      return 'Unknown';
  }
};

const getStatusDotColor = (status: string) => {
  switch (status) {
    case 'pending_version_review':
      return 'bg-yellow-500';
    case 'pending_response_review':
      return 'bg-blue-500';
    case 'rag_failed':
      return 'bg-red-500';
    case 'approved':
      return 'bg-green-500';
    case 'edited':
      return 'bg-purple-500';
    case 'rejected':
      return 'bg-red-500';
    case 'skipped':
      return 'bg-gray-500';
    default:
      return 'bg-gray-300';
  }
};

const getStatusLabel = (status: string) => {
  switch (status) {
    case 'pending_version_review':
      return 'Version Review';
    case 'pending_response_review':
      return 'Response Review';
    case 'rag_failed':
      return 'Failed Generation';
    case 'approved':
      return 'Approved';
    case 'edited':
      return 'Edited';
    case 'rejected':
      return 'Rejected';
    case 'skipped':
      return 'Skipped';
    default:
      return 'Unknown';
  }
};

export default function ShadowModePage() {
  // Data state
  const [responses, setResponses] = useState<ShadowResponse[]>([]);
  const [stats, setStats] = useState<ShadowStats | null>(null);
  const [isLoadingData, setIsLoadingData] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [statusFilter, setStatusFilter] = useState('all');

  // UI state
  const [selectedResponse, setSelectedResponse] = useState<ShadowResponse | null>(null);
  const [showVersionDialog, setShowVersionDialog] = useState(false);
  const [showResponseDialog, setShowResponseDialog] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [hoveredCardId, setHoveredCardId] = useState<string | null>(null);

  // Inline version change state (per card)
  const [inlineVersionChanges, setInlineVersionChanges] = useState<Record<string, { version: string; reason: string; trainingVersion?: string; customQuestion?: string }>>({});

  // Skip reason state (per card)
  const [skipReasons, setSkipReasons] = useState<Record<string, string>>({});
  const [showCustomSkipInput, setShowCustomSkipInput] = useState<Record<string, boolean>>({});
  const [customSkipText, setCustomSkipText] = useState<Record<string, string>>({});

  // Generating state (per card) - tracks which responses are currently generating RAG
  const [generatingIds, setGeneratingIds] = useState<Set<string>>(new Set());

  // Inline response editing state
  const [editingResponseId, setEditingResponseId] = useState<string | null>(null);
  const [editedResponses, setEditedResponses] = useState<Record<string, string>>({});

  // Keyboard navigation state
  const [selectedIndex, setSelectedIndex] = useState<number>(-1);

  // Collapsible state - track which cards are expanded
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  // Track which sources are expanded (per response ID + source index)
  const [expandedSources, setExpandedSources] = useState<Set<string>>(new Set());

  // Refs for card elements
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // Command palette state
  const [showCommandPalette, setShowCommandPalette] = useState(false);

  // Version confirmation state
  const [selectedVersion, setSelectedVersion] = useState<string>('');
  const [versionChangeReason, setVersionChangeReason] = useState('');
  const [isConfirmingVersion, setIsConfirmingVersion] = useState(false);

  // Response review state
  const [editedResponse, setEditedResponse] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const fetchResponses = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        limit: '50',
        offset: '0',
      });

      if (statusFilter !== 'all') {
        params.set('status', statusFilter);
      }

      const response = await makeAuthenticatedRequest(`/admin/shadow-mode/responses?${params}`);
      if (response.ok) {
        const data = await response.json();
        setResponses(data);
      } else {
        throw new Error(`Failed to fetch responses. Status: ${response.status}`);
      }
    } catch (err) {
      console.error('Error fetching responses:', err);
      setError('Failed to fetch shadow mode responses');
    }
  }, [statusFilter]);

  const fetchStats = useCallback(async () => {
    try {
      const response = await makeAuthenticatedRequest('/admin/shadow-mode/stats');
      if (response.ok) {
        const data = await response.json();
        setStats(data);
      }
    } catch (err) {
      console.error('Error fetching stats:', err);
    }
  }, []);

  const fetchData = useCallback(async () => {
    setIsLoadingData(true);
    try {
      await Promise.all([fetchResponses(), fetchStats()]);
      setError(null);
    } catch (err) {
      console.error('Error fetching data:', err);
    } finally {
      setIsLoadingData(false);
    }
  }, [fetchResponses, fetchStats]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh every 30 seconds
  useEffect(() => {
    const intervalId = setInterval(() => {
      fetchResponses();
      fetchStats();
    }, 30000);
    return () => clearInterval(intervalId);
  }, [fetchResponses, fetchStats]);

  // Keyboard shortcuts using react-hotkeys-hook
  // Navigate down (j key)
  useHotkeys(
    'j',
    (e) => {
      e.preventDefault();
      if (responses.length) {
        setSelectedIndex((prev) =>
          prev < responses.length - 1 ? prev + 1 : prev
        );
        // Scroll into view
        const newIndex = selectedIndex < responses.length - 1 ? selectedIndex + 1 : selectedIndex;
        if (newIndex >= 0 && responses[newIndex]) {
          const el = cardRefs.current.get(responses[newIndex].id);
          el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    },
    { enableOnFormTags: false },
    [responses, selectedIndex]
  );

  // Navigate up (k key)
  useHotkeys(
    'k',
    (e) => {
      e.preventDefault();
      if (responses.length) {
        setSelectedIndex((prev) => (prev > 0 ? prev - 1 : prev === -1 ? 0 : prev));
        // Scroll into view
        const newIndex = selectedIndex > 0 ? selectedIndex - 1 : selectedIndex === -1 ? 0 : selectedIndex;
        if (newIndex >= 0 && responses[newIndex]) {
          const el = cardRefs.current.get(responses[newIndex].id);
          el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    },
    { enableOnFormTags: false },
    [responses, selectedIndex]
  );

  // Confirm with Enter on selected card
  useHotkeys(
    'enter',
    (e) => {
      e.preventDefault();
      if (selectedIndex >= 0 && responses[selectedIndex]) {
        const resp = responses[selectedIndex];
        if (resp.status === 'pending_version_review') {
          handleConfirmWithInlineChanges(resp);
        } else if (resp.status === 'pending_response_review') {
          openResponseDialog(resp);
        }
      }
    },
    { enableOnFormTags: false },
    [selectedIndex, responses]
  );

  // Skip with 's' key
  useHotkeys(
    's',
    (e) => {
      e.preventDefault();
      if (selectedIndex >= 0 && responses[selectedIndex]) {
        handleSkip(responses[selectedIndex].id);
      }
    },
    { enableOnFormTags: false },
    [selectedIndex, responses]
  );

  // Delete with 'd' key
  useHotkeys(
    'd',
    (e) => {
      e.preventDefault();
      if (selectedIndex >= 0 && responses[selectedIndex]) {
        setDeleteConfirmId(responses[selectedIndex].id);
      }
    },
    { enableOnFormTags: false },
    [selectedIndex, responses]
  );

  // Toggle expand/collapse with 'x' key
  useHotkeys(
    'x',
    (e) => {
      e.preventDefault();
      if (selectedIndex >= 0 && responses[selectedIndex]) {
        const id = responses[selectedIndex].id;
        setExpandedIds(prev => {
          const newSet = new Set(prev);
          if (newSet.has(id)) {
            newSet.delete(id);
          } else {
            newSet.add(id);
          }
          return newSet;
        });
      }
    },
    { enableOnFormTags: false },
    [selectedIndex, responses]
  );

  // Escape to deselect
  useHotkeys(
    'escape',
    (e) => {
      e.preventDefault();
      setSelectedIndex(-1);
      setShowCommandPalette(false);
    },
    { enableOnFormTags: true }
  );

  // Command palette (Cmd+K / Ctrl+K)
  useHotkeys(
    'mod+k',
    (e) => {
      e.preventDefault();
      setShowCommandPalette(true);
    },
    { enableOnFormTags: true }
  );

  // Keyboard shortcut 'e' for Edit mode
  useEffect(() => {
    const handleKeyPress = (e: KeyboardEvent) => {
      // Only trigger if 'e' is pressed and not already in edit mode
      if (e.key === 'e' && !editingResponseId && selectedIndex >= 0 && responses[selectedIndex]) {
        const response = responses[selectedIndex];
        // Only for Response Review cards
        if (response.status === 'pending_response_review') {
          e.preventDefault();
          setEditingResponseId(response.id);
          setEditedResponses({
            ...editedResponses,
            [response.id]: response.generated_response || ''
          });
        }
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [selectedIndex, editingResponseId, responses, editedResponses]);

  // ESC key handler for edit mode cancellation
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && editingResponseId !== null) {
        // Same logic as Cancel button
        setEditingResponseId(null);
        setEditedResponses(prev => {
          const updated = { ...prev };
          delete updated[editingResponseId];
          return updated;
        });
      }
    };

    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [editingResponseId]);

  // Helper function to format timestamps consistently (matches FAQ section)
  const formatTimestamp = (timestamp?: string | null): string => {
    if (!timestamp) return "N/A";
    try {
      const date = new Date(timestamp);
      return new Intl.DateTimeFormat("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "UTC",
        timeZoneName: "short",
      }).format(date);
    } catch {
      return "Invalid date";
    }
  };

  // Version confirmation handlers
  const handleConfirmVersion = async () => {
    if (!selectedResponse) return;

    setIsConfirmingVersion(true);

    // Optimistic update
    setResponses(prev => prev.filter(r => r.id !== selectedResponse.id));
    setShowVersionDialog(false);

    try {
      const body: Record<string, string> = {
        confirmed_version: selectedVersion,
      };
      if (selectedVersion !== selectedResponse.detected_version && versionChangeReason) {
        body.version_change_reason = versionChangeReason;
      }

      const response = await makeAuthenticatedRequest(
        `/admin/shadow-mode/responses/${selectedResponse.id}/confirm-version`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }
      );

      if (response.ok) {
        sonnerToast.success('✓ Version confirmed - response generation in progress');
        fetchStats();
      } else {
        const errorData = await response.json();
        sonnerToast.error(`✕ ${errorData.detail || 'Failed to confirm version - please try again'}`);
        fetchData();
      }
    } catch (err) {
      console.error('Error confirming version:', err);
      sonnerToast.error('✕ Failed to confirm version - please try again or contact support');
      fetchData();
    } finally {
      setIsConfirmingVersion(false);
    }
  };

  // Response review handlers
  const openResponseDialog = (response: ShadowResponse) => {
    setSelectedResponse(response);
    setEditedResponse(response.generated_response || '');
    setShowResponseDialog(true);
  };

  const handleApprove = async (responseId: string) => {
    setIsSubmitting(true);
    setResponses(prev => prev.filter(r => r.id !== responseId));
    setShowResponseDialog(false);
    setEditingResponseId(null);

    try {
      const response = await makeAuthenticatedRequest(
        `/admin/shadow-mode/responses/${responseId}/approve`,
        { method: 'POST' }
      );

      if (response.ok) {
        sonnerToast.success('✓ Response approved and ready for deployment');
        fetchStats();
      } else {
        sonnerToast.error('⚠️ Failed to approve - please try again or contact support');
        fetchData();
      }
    } catch (err) {
      console.error('Error approving:', err);
      sonnerToast.error('⚠️ Failed to approve - please try again or contact support');
      fetchData();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleEdit = async () => {
    if (!selectedResponse) return;

    setIsSubmitting(true);
    setResponses(prev => prev.filter(r => r.id !== selectedResponse.id));
    setShowResponseDialog(false);

    try {
      const response = await makeAuthenticatedRequest(
        `/admin/shadow-mode/responses/${selectedResponse.id}/edit`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ edited_response: editedResponse }),
        }
      );

      if (response.ok) {
        sonnerToast.success('✓ Edits saved - response updated');
        fetchStats();
      } else {
        sonnerToast.error('⚠️ Failed to save edits - please try again or contact support');
        fetchData();
      }
    } catch (err) {
      console.error('Error editing:', err);
      sonnerToast.error('⚠️ Failed to save edits - please try again or contact support');
      fetchData();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSaveEdit = async (responseId: string) => {
    const editedText = editedResponses[responseId];
    if (!editedText) return;

    setIsSubmitting(true);

    try {
      const response = await makeAuthenticatedRequest(
        `/admin/shadow-mode/responses/${responseId}/edit`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ edited_response: editedText }),
        }
      );

      if (response.ok) {
        sonnerToast.success('✓ Edits saved - response updated');
        // Update local state
        setResponses(prev => prev.map(r =>
          r.id === responseId ? { ...r, generated_response: editedText, edited_response: editedText } : r
        ));
        setEditingResponseId(null);
        setEditedResponses(prev => {
          const updated = { ...prev };
          delete updated[responseId];
          return updated;
        });
        fetchStats();
      } else {
        sonnerToast.error('⚠️ Failed to save edits - please try again or contact support');
      }
    } catch (err) {
      console.error('Error editing:', err);
      sonnerToast.error('⚠️ Failed to save edits - please try again or contact support');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReject = async () => {
    if (!selectedResponse) return;

    setIsSubmitting(true);
    setResponses(prev => prev.filter(r => r.id !== selectedResponse.id));
    setShowResponseDialog(false);

    try {
      const response = await makeAuthenticatedRequest(
        `/admin/shadow-mode/responses/${selectedResponse.id}/reject`,
        { method: 'POST' }
      );

      if (response.ok) {
        sonnerToast.success('✓ Response rejected - will not be sent');
        fetchStats();
      } else {
        sonnerToast.error('⚠️ Failed to reject - please try again or contact support');
        fetchData();
      }
    } catch (err) {
      console.error('Error rejecting:', err);
      sonnerToast.error('⚠️ Failed to reject - please try again or contact support');
      fetchData();
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSkip = async (responseId: string, customReason?: string) => {
    // Use custom reason if provided, otherwise use skipReasons state
    const skipReason = customReason || skipReasons[responseId];

    // Optimistic UI update - remove immediately
    setResponses(prev => prev.filter(r => r.id !== responseId));

    // Clear all skip-related state for this response
    setSkipReasons(prev => {
      const updated = { ...prev };
      delete updated[responseId];
      return updated;
    });
    setShowCustomSkipInput(prev => {
      const updated = { ...prev };
      delete updated[responseId];
      return updated;
    });
    setCustomSkipText(prev => {
      const updated = { ...prev };
      delete updated[responseId];
      return updated;
    });

    try {
      const body = skipReason ? { skip_reason: skipReason } : undefined;
      const response = await makeAuthenticatedRequest(
        `/admin/shadow-mode/responses/${responseId}/skip`,
        {
          method: 'POST',
          headers: body ? { 'Content-Type': 'application/json' } : undefined,
          body: body ? JSON.stringify(body) : undefined
        }
      );

      if (response.ok) {
        const reasonText = skipReason ? ` - reason: ${skipReason}` : '';
        sonnerToast.success(`✓ Response skipped${reasonText}`);
        fetchStats();
      } else {
        sonnerToast.error('⚠️ Failed to skip - please try again or contact support');
        // Revert optimistic update on failure
        fetchData();
      }
    } catch (err) {
      console.error('Error skipping:', err);
      sonnerToast.error('⚠️ Failed to skip - please try again or contact support');
      // Revert optimistic update on failure
      fetchData();
    }
  };

  const handleRetryRag = async (responseId: string) => {
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/shadow-mode/responses/${responseId}/retry-rag`,
        { method: 'POST' }
      );

      if (response.ok) {
        sonnerToast.success('✓ Response regenerated successfully');
        fetchData();
      } else {
        const errorData = await response.json();
        sonnerToast.error(`⚠️ ${errorData.detail || 'Failed to regenerate - please try again or contact support'}`);
      }
    } catch (err) {
      console.error('Error retrying RAG:', err);
      sonnerToast.error('⚠️ Failed to regenerate - please try again or contact support');
    }
  };

  const handleDelete = async (responseId: string) => {
    setDeleteConfirmId(null);
    setResponses(prev => prev.filter(r => r.id !== responseId));

    try {
      const response = await makeAuthenticatedRequest(
        `/admin/shadow-mode/responses/${responseId}`,
        { method: 'DELETE' }
      );
      if (response.ok) {
        sonnerToast.success('✓ Response deleted from queue');
        fetchStats();
      } else {
        sonnerToast.error('⚠️ Failed to delete - please try again or contact support');
        fetchData();
      }
    } catch (err) {
      console.error('Error deleting response:', err);
      sonnerToast.error('⚠️ Failed to delete - please try again or contact support');
      fetchData();
    }
  };

  // Handle inline version change
  const handleInlineVersionChange = (responseId: string, newVersion: string, detectedVersion: string | null) => {
    if (newVersion === detectedVersion) {
      // Reset if selecting original version
      setInlineVersionChanges(prev => {
        const updated = { ...prev };
        delete updated[responseId];
        return updated;
      });
    } else {
      setInlineVersionChanges(prev => ({
        ...prev,
        [responseId]: { version: newVersion, reason: prev[responseId]?.reason || '' }
      }));
    }
  };

  // Handle inline reason change
  const handleInlineReasonChange = (responseId: string, reason: string) => {
    setInlineVersionChanges(prev => ({
      ...prev,
      [responseId]: { ...prev[responseId], reason }
    }));
  };

  // Handle confirm with inline changes
  const handleConfirmWithInlineChanges = async (response: ShadowResponse) => {
    const inlineChange = inlineVersionChanges[response.id];
    const finalVersion = inlineChange?.version || response.detected_version || 'unknown';
    const finalReason = inlineChange?.reason || '';
    const trainingVersion = inlineChange?.trainingVersion;
    const customQuestion = inlineChange?.customQuestion;

    // Mark as generating (show loading state)
    setGeneratingIds(prev => new Set(prev).add(response.id));
    setInlineVersionChanges(prev => {
      const updated = { ...prev };
      delete updated[response.id];
      return updated;
    });

    try {
      const body: Record<string, string> = {
        confirmed_version: finalVersion,
      };
      if (finalVersion !== response.detected_version && finalReason) {
        body.version_change_reason = finalReason;
      }
      // Add Unknown version fields
      if (finalVersion === 'unknown') {
        if (trainingVersion) {
          body.training_version = trainingVersion;
        }
        if (customQuestion) {
          body.custom_clarifying_question = customQuestion;
        }
      }

      const res = await makeAuthenticatedRequest(
        `/admin/shadow-mode/responses/${response.id}/confirm-version`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }
      );

      if (res.ok) {
        sonnerToast.success('✓ Version confirmed - response generated successfully');
        // Fetch the updated response to show the result
        const updatedRes = await makeAuthenticatedRequest(
          `/admin/shadow-mode/responses/${response.id}`
        );
        if (updatedRes.ok) {
          const updatedData = await updatedRes.json();
          setResponses(prev => prev.map(r =>
            r.id === response.id ? updatedData : r
          ));
        }
        fetchStats();
      } else {
        const errorData = await res.json();
        sonnerToast.error(`✕ ${errorData.detail || 'Failed to confirm version - please try again'}`);
        fetchData();
      }
    } catch (err) {
      console.error('Error confirming version:', err);
      sonnerToast.error('✕ Failed to confirm version - please try again or contact support');
      fetchData();
    } finally {
      // Remove from generating set
      setGeneratingIds(prev => {
        const newSet = new Set(prev);
        newSet.delete(response.id);
        return newSet;
      });
    }
  };

  // Render functions for different card types
  const renderVersionReviewCard = (response: ShadowResponse) => {
    const inlineChange = inlineVersionChanges[response.id];
    const currentVersion = inlineChange?.version || response.detected_version || 'unknown';
    const hasVersionChange = inlineChange && inlineChange.version !== response.detected_version;
    const messageTimestamp = response.messages[0]?.timestamp || response.created_at;
    const isGenerating = generatingIds.has(response.id);

    // Show loading state while generating
    if (isGenerating) {
      return (
        <Card
          key={response.id}
          data-testid="version-review-card"
          data-status="generating"
          className="transition-all duration-200 hover:shadow-md"
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-center py-8">
              <div className="text-center space-y-3">
                <Loader2 className="h-8 w-8 animate-spin mx-auto text-blue-500" />
                <p className="text-sm text-muted-foreground">Generating response...</p>
                <p className="text-xs text-muted-foreground/70">
                  {response.synthesized_question || response.messages[0]?.content.slice(0, 100)}...
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      );
    }

    return (
      <Card
        key={response.id}
        data-testid="version-review-card"
        data-status={response.status}
        className={cn(
          "transition-all duration-200 hover:shadow-md",
          hoveredCardId === response.id && "shadow-md"
        )}
        onMouseEnter={() => setHoveredCardId(response.id)}
        onMouseLeave={() => setHoveredCardId(null)}
      >
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            {/* Status indicator - subtle dot */}
            <div className={cn("w-2 h-2 rounded-full", getStatusDotColor(response.status))} />
            <h3 className="text-sm font-semibold">{getStatusLabel(response.status)}</h3>
          </div>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          <div className="flex items-start justify-between">
            <div className="flex-1 space-y-3">
              {/* Confidence indicators - reorganized layout */}
              <div className="flex items-center gap-3">
                <span className="text-xs text-muted-foreground">Confidence:</span>
                <Badge
                  className={cn(
                    "text-xs font-medium px-2 py-1",
                    response.version_confidence >= 0.8
                      ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
                      : response.version_confidence >= 0.5
                      ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400"
                      : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400"
                  )}
                >
                  {getConfidenceLabel(response.version_confidence)}
                </Badge>

                {/* Progress bar */}
                <div className="flex items-center gap-2 flex-1 max-w-[120px]">
                  <div className="relative flex-1 h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all duration-300",
                        getConfidenceColor(response.version_confidence)
                      )}
                      style={{ width: `${response.version_confidence * 100}%` }}
                    />
                  </div>
                  <span className={cn(
                    "text-xs font-medium",
                    getConfidenceTextColor(response.version_confidence)
                  )}>
                    {Math.round(response.version_confidence * 100)}%
                  </span>
                </div>
              </div>

              {/* Messages - collapsible when long */}
              {(() => {
                const isLongContent = response.messages.some(msg => msg.content.length > 200) || response.messages.length > 2;
                const isExpanded = expandedIds.has(response.id);

                if (!isLongContent) {
                  return (
                    <div className="space-y-2">
                      {response.messages.map((msg, idx) => (
                        <div key={idx} className="text-sm">
                          <span className="font-medium text-muted-foreground">
                            {msg.sender_type === 'user' ? 'User' : 'Support'}
                          </span>
                          <p className="mt-1">{msg.content}</p>
                        </div>
                      ))}
                    </div>
                  );
                }

                return (
                  <Collapsible
                    open={isExpanded}
                    onOpenChange={(open) => {
                      setExpandedIds(prev => {
                        const next = new Set(prev);
                        if (open) {
                          next.add(response.id);
                        } else {
                          next.delete(response.id);
                        }
                        return next;
                      });
                    }}
                  >
                    {/* Trigger at TOP with visual indicator */}
                    <CollapsibleTrigger asChild>
                      <button className="w-full text-left group hover:bg-accent/50 rounded p-2 -m-2 transition-colors mb-2">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-medium text-muted-foreground flex items-center gap-2">
                            <ChevronDown className={cn("h-3 w-3 transition-transform", isExpanded && "rotate-180")} />
                            {isExpanded ? "Hide full message" : "Show full message"}
                          </span>
                        </div>
                      </button>
                    </CollapsibleTrigger>

                    <div className="space-y-2">
                      {/* Always show first message preview */}
                      <div className="text-sm">
                        <span className="font-medium text-muted-foreground">
                          {response.messages[0]?.sender_type === 'user' ? 'User' : 'Support'}
                        </span>
                        <p className={cn("mt-1", !isExpanded && "line-clamp-2")}>
                          {response.messages[0]?.content}
                        </p>
                      </div>

                      {/* Remaining messages */}
                      <CollapsibleContent className="space-y-2">
                        {response.messages.slice(1).map((msg, idx) => (
                          <div key={idx} className="text-sm">
                            <span className="font-medium text-muted-foreground">
                              {msg.sender_type === 'user' ? 'User' : 'Support'}
                            </span>
                            <p className="mt-1">{msg.content}</p>
                          </div>
                        ))}
                      </CollapsibleContent>
                    </div>
                  </Collapsible>
                );
              })()}

              {/* Version selector and actions */}
              <div className="space-y-3 pt-2">
                {/* Version Selection - Clean Radio Style */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm font-medium">Bisq Version</Label>
                    {response.detected_version && (
                      <span className="text-xs text-muted-foreground">
                        Auto-detected: <Badge variant="outline" className="ml-1">{formatVersionLabel(response.detected_version)}</Badge>
                      </span>
                    )}
                  </div>

                  <div className="flex flex-col gap-2">
                    {['bisq2', 'bisq1', 'unknown'].map((version) => (
                      <button
                        key={version}
                        type="button"
                        onClick={() => handleInlineVersionChange(response.id, version, response.detected_version)}
                        className={cn(
                          "flex items-center gap-3 px-4 py-3 rounded-lg border-2 transition-all text-left",
                          "hover:bg-accent/50",
                          currentVersion === version
                            ? "border-primary bg-primary/5 shadow-sm"
                            : "border-border bg-background"
                        )}
                      >
                        {/* Radio Circle */}
                        <div className={cn(
                          "flex items-center justify-center w-5 h-5 rounded-full border-2 flex-shrink-0",
                          currentVersion === version
                            ? "border-primary bg-primary"
                            : "border-muted-foreground/30"
                        )}>
                          {currentVersion === version && (
                            <div className="w-2 h-2 rounded-full bg-primary-foreground" />
                          )}
                        </div>

                        {/* Label */}
                        <div className="flex-1">
                          <span className={cn(
                            "text-sm font-medium",
                            currentVersion === version ? "text-foreground" : "text-muted-foreground"
                          )}>
                            {formatVersionLabel(version)}
                          </span>
                        </div>

                        {/* Checkmark for selected */}
                        {currentVersion === version && (
                          <Check className="w-4 h-4 text-primary" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>

                {/* ALWAYS reserve space for reason input - use opacity transition */}
                <div
                  className={cn(
                    "transition-all duration-200",
                    hasVersionChange ? "opacity-100 h-10" : "opacity-0 h-0 overflow-hidden"
                  )}
                >
                  <Input
                    value={inlineChange?.reason || ''}
                    onChange={(e) => handleInlineReasonChange(response.id, e.target.value)}
                    placeholder="Why is the detected version incorrect? (for ML training)"
                    className="text-sm"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !generatingIds.has(response.id)) {
                        e.preventDefault();
                        handleConfirmWithInlineChanges(response);
                      }
                    }}
                  />
                </div>

                {/* Unknown Version - Training Version Selection */}
                {/* P0: Reserve space for stable layout (no button jumping) */}
                <div
                  className={cn(
                    "transition-all duration-200 overflow-hidden",
                    currentVersion === 'unknown'
                      ? "opacity-100 max-h-96"
                      : "opacity-0 max-h-0"
                  )}
                >
                  <div className="space-y-4 border-t pt-4">
                    <div>
                      <Label className="text-sm font-medium mb-2 block">
                        Training version <span className="text-destructive">*</span>
                      </Label>
                      <p className="text-xs text-muted-foreground mb-3">
                        Generate version-specific response (simulates asking user their version)
                      </p>
                      <Select
                        value={inlineChange?.trainingVersion || ''}
                        onValueChange={(value) => {
                          setInlineVersionChanges(prev => ({
                            ...prev,
                            [response.id]: { ...prev[response.id], trainingVersion: value }
                          }));
                        }}
                      >
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder="Select training version..." />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Bisq 1">Bisq 1</SelectItem>
                          <SelectItem value="Bisq 2">Bisq 2</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    {/* P1: Progressive disclosure - show custom question only after training version selected */}
                    {inlineChange?.trainingVersion && (
                      <div className="animate-in fade-in duration-200">
                        <Label className="text-sm font-medium mb-2 block">
                          Custom clarifying question <span className="text-muted-foreground text-xs">(optional)</span>
                        </Label>
                        <p className="text-xs text-muted-foreground mb-2">
                          Override default question for {inlineChange.trainingVersion}
                        </p>
                        <Input
                          placeholder={`e.g., Are you asking about ${inlineChange.trainingVersion} trading or Bisq Easy?`}
                          value={inlineChange?.customQuestion || ''}
                          onChange={(e) => {
                            setInlineVersionChanges(prev => ({
                              ...prev,
                              [response.id]: { ...prev[response.id], customQuestion: e.target.value }
                            }));
                          }}
                          className="text-sm"
                        />
                      </div>
                    )}
                  </div>
                </div>

                {/* Confirm button - right-aligned and compact */}
                <div className="flex justify-end">
                  <Button
                    onClick={() => handleConfirmWithInlineChanges(response)}
                    size="sm"
                    disabled={generatingIds.has(response.id) || (currentVersion === 'unknown' && !inlineChange?.trainingVersion)}
                  >
                    {generatingIds.has(response.id) ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Generating...
                      </>
                    ) : (
                      "Confirm & Generate"
                    )}
                  </Button>
                </div>

                {/* Skip action with 1-click and progressive disclosure */}
                <div className="flex gap-2 items-start">
                  <Select
                    value={skipReasons[response.id] || ''}
                    onValueChange={(value) => {
                      if (value === 'custom') {
                        setShowCustomSkipInput(prev => ({ ...prev, [response.id]: true }));
                        setSkipReasons(prev => ({ ...prev, [response.id]: '' }));
                      } else {
                        setShowCustomSkipInput(prev => ({ ...prev, [response.id]: false }));
                        setSkipReasons(prev => ({ ...prev, [response.id]: value }));
                        // Auto-skip with predefined reason
                        handleSkip(response.id, value);
                      }
                    }}
                  >
                    <SelectTrigger className="w-[180px] text-sm">
                      <SelectValue placeholder="Skip..." />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="not_a_question">Not a question</SelectItem>
                      <SelectItem value="off_topic">Off-topic</SelectItem>
                      <SelectItem value="spam">Spam</SelectItem>
                      <SelectItem value="duplicate">Duplicate</SelectItem>
                      <SelectItem value="already_answered">Already answered</SelectItem>
                      <SelectItem value="custom">Custom reason...</SelectItem>
                    </SelectContent>
                  </Select>

                  {/* Only show when "Custom reason..." is selected */}
                  {showCustomSkipInput[response.id] && (
                    <>
                      <Input
                        autoFocus
                        value={customSkipText[response.id] || ''}
                        onChange={(e) => setCustomSkipText(prev => ({ ...prev, [response.id]: e.target.value }))}
                        placeholder="Why skip? (for ML training)"
                        className="flex-1 text-sm"
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && customSkipText[response.id]) {
                            handleSkip(response.id, customSkipText[response.id]);
                          }
                        }}
                      />
                      <Button
                        onClick={() => handleSkip(response.id, customSkipText[response.id])}
                        size="sm"
                        disabled={!customSkipText[response.id]}
                      >
                        Skip
                      </Button>
                    </>
                  )}
                </div>
              </div>

              {/* Timestamp Information - Compact with Progressive Disclosure */}
              <div className="pt-2 border-t border-border/40 mt-3">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-help">
                      <Clock className="h-3 w-3" />
                      <span>{formatTimestamp(messageTimestamp)}</span>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" align="start" className="text-xs">
                    <div className="space-y-1">
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-medium opacity-70">Question Created:</span>
                        <span>{formatTimestamp(messageTimestamp)}</span>
                      </div>
                      {response.version_confirmed_at && (
                        <div className="flex items-center justify-between gap-3">
                          <span className="font-medium opacity-70">Version Confirmed:</span>
                          <span>{formatTimestamp(response.version_confirmed_at)}</span>
                        </div>
                      )}
                    </div>
                  </TooltipContent>
                </Tooltip>
              </div>
            </div>

            {/* Delete button on hover */}
            <div className={cn(
              "ml-4 transition-opacity duration-200",
              hoveredCardId === response.id ? "opacity-100" : "opacity-0"
            )}>
              <Button
                onClick={() => setDeleteConfirmId(response.id)}
                variant="ghost"
                size="icon"
              >
                <Trash2 className="h-4 w-4 text-red-500" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  };

  const renderResponseReviewCard = (response: ShadowResponse) => {
    const isEditing = editingResponseId === response.id;
    const sourceTypes = [...new Set(response.sources?.map(s => {
      if (s.type === 'faq') return 'FAQs';
      if (s.type === 'wiki') return 'Wiki';
      return s.type;
    }) || [])];

    return (
      <Card
        key={response.id}
        data-testid="response-review-card"
        data-status={response.status}
        className={cn(
          "transition-all duration-200 hover:shadow-md",
          hoveredCardId === response.id && "shadow-md"
        )}
        onMouseEnter={() => setHoveredCardId(response.id)}
        onMouseLeave={() => setHoveredCardId(null)}
      >
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {/* Status indicator - subtle dot */}
              <div className={cn("w-2 h-2 rounded-full", getStatusDotColor(response.status))} />
              <h3 className="text-sm font-semibold">{getStatusLabel(response.status)}</h3>
            </div>
            <Badge variant="outline" className="text-xs">
              {formatVersionLabel(response.confirmed_version)}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          <div className="flex items-start justify-between">
            <div className="flex-1 space-y-3">

              {/* Confidence and Routing */}
              {response.confidence !== null && (
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-2">
                    <Badge
                      className={cn(
                        "text-xs font-medium px-2 py-1",
                        response.confidence >= 0.8
                          ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
                          : response.confidence >= 0.5
                          ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400"
                          : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400"
                      )}
                    >
                      {getConfidenceLabel(response.confidence)} Confidence
                    </Badge>
                    <div className="flex items-center gap-1">
                      <div className="w-24 h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                        <div
                          className={cn(
                            "h-full rounded-full transition-all",
                            getConfidenceColor(response.confidence)
                          )}
                          style={{ width: `${(response.confidence || 0) * 100}%` }}
                        />
                      </div>
                      <span className={cn(
                        "text-xs font-medium",
                        getConfidenceTextColor(response.confidence)
                      )}>
                        {((response.confidence || 0) * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>
                  {response.routing_action && (
                    <Badge className={getRoutingBadgeStyle(response.routing_action)}>
                      {getRoutingLabel(response.routing_action)}
                    </Badge>
                  )}
                </div>
              )}

              {/* Question */}
              <div>
                <span className="font-medium text-sm text-muted-foreground">Question:</span>
                <p className="text-sm mt-1">{response.synthesized_question || response.messages[0]?.content}</p>
              </div>

              {/* Generated Response - Hide for skipped and rejected cards */}
              {response.status !== 'skipped' && response.status !== 'rejected' && (
                <>
                  {/* Generated Response - Inline editing */}
                  {isEditing ? (
                    <div className="space-y-3">
                      <span className="font-medium text-sm text-muted-foreground">Edit Response:</span>
                      <Textarea
                        value={editedResponses[response.id] || response.generated_response || ''}
                        onChange={(e) => setEditedResponses({...editedResponses, [response.id]: e.target.value})}
                        rows={8}
                        className="mt-1"
                      />

                      {/* Sources in edit mode */}
                      {response.sources && response.sources.length > 0 && (
                        <div className="space-y-2">
                          <Label className="text-xs text-muted-foreground">Sources Used:</Label>
                          <div className="space-y-1">
                            {response.sources.map((source, idx) => {
                              const sourceKey = `${response.id}-${idx}`;
                              const isExpanded = expandedSources.has(sourceKey);

                              return (
                                <Collapsible
                                  key={idx}
                                  open={isExpanded}
                                  onOpenChange={(open) => {
                                    setExpandedSources(prev => {
                                      const next = new Set(prev);
                                      if (open) {
                                        next.add(sourceKey);
                                      } else {
                                        next.delete(sourceKey);
                                      }
                                      return next;
                                    });
                                  }}
                                >
                                  <div className="text-xs p-2 bg-muted/50 rounded border">
                                    <CollapsibleTrigger className="w-full">
                                      <div className="flex items-center gap-2 justify-between">
                                        <div className="flex items-center gap-2">
                                          <Badge variant="outline" className="text-xs">
                                            {source.type === 'faq' ? 'FAQ' : source.type === 'wiki' ? 'Wiki' : source.type}
                                          </Badge>
                                          {source.title && (
                                            <span className="font-medium">{source.title}</span>
                                          )}
                                        </div>
                                        <ChevronDown className={cn(
                                          "h-4 w-4 transition-transform",
                                          isExpanded && "rotate-180"
                                        )} />
                                      </div>
                                    </CollapsibleTrigger>
                                    <CollapsibleContent>
                                      {source.content && (
                                        <p className="text-muted-foreground mt-2 text-left">{source.content}</p>
                                      )}
                                    </CollapsibleContent>
                                  </div>
                                </Collapsible>
                              );
                            })}
                          </div>
                          <p className="text-xs text-muted-foreground italic">
                            Source types: {sourceTypes.join(', ')}
                          </p>
                        </div>
                      )}

                      <div className="flex gap-2 justify-end">
                        <Button
                          onClick={() => {
                            setEditingResponseId(null);
                            setEditedResponses(prev => {
                              const updated = { ...prev };
                              delete updated[response.id];
                              return updated;
                            });
                          }}
                          variant="outline"
                          size="sm"
                          disabled={isSubmitting}
                        >
                          Cancel
                        </Button>
                        <Button
                          onClick={async () => {
                            // Save edits first, then approve
                            await handleSaveEdit(response.id);
                            await handleApprove(response.id);
                          }}
                          size="sm"
                          className="bg-green-600 hover:bg-green-700"
                          disabled={isSubmitting}
                        >
                          {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle className="h-4 w-4 mr-1" />}
                          Save & Approve
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div>
                      <span className="font-medium text-sm text-muted-foreground">Generated Response:</span>
                      <p className="text-sm mt-1">{response.generated_response}</p>

                      {/* Sources */}
                      {sourceTypes.length > 0 && (
                        <p className="text-sm text-muted-foreground mt-2">
                          Sources: {sourceTypes.join(', ')}
                        </p>
                      )}

                      {/* Actions - Only show for pending_response_review status */}
                      {response.status === 'pending_response_review' && (
                        <div className="flex gap-2 mt-3">
                          <Button
                            onClick={() => {
                              setEditingResponseId(response.id);
                              setEditedResponses({...editedResponses, [response.id]: response.generated_response || ''});
                            }}
                            variant="outline"
                            size="sm"
                          >
                            <Edit className="h-4 w-4 mr-1" />
                            Edit
                          </Button>
                          <Button
                            onClick={() => handleApprove(response.id)}
                            size="sm"
                            className="bg-green-600 hover:bg-green-700"
                          >
                            <CheckCircle className="h-4 w-4 mr-1" />
                            Approve
                          </Button>
                          <Button
                            onClick={async () => {
                              setIsSubmitting(true);
                              setResponses(prev => prev.filter(r => r.id !== response.id));

                              try {
                                const res = await makeAuthenticatedRequest(
                                  `/admin/shadow-mode/responses/${response.id}/reject`,
                                  { method: 'POST' }
                                );

                                if (res.ok) {
                                  sonnerToast.success('✓ Response rejected - will not be sent');
                                  fetchStats();
                                } else {
                                  // Extract detailed error message
                                  let errorMessage = 'Failed to reject';
                                  try {
                                    const errorData = await res.json();
                                    errorMessage = errorData.detail || errorData.message || errorMessage;
                                  } catch {
                                    const errorText = await res.text().catch(() => '');
                                    if (errorText) errorMessage = errorText;
                                  }
                                  sonnerToast.error(`⚠️ Failed to reject: ${errorMessage}`);
                                  fetchData();
                                }
                              } catch (err) {
                                console.error('Error rejecting:', err);
                                const errorMessage = err instanceof Error ? err.message : 'Unknown error';
                                sonnerToast.error(`⚠️ Failed to reject: ${errorMessage}`);
                                fetchData();
                              } finally {
                                setIsSubmitting(false);
                              }
                            }}
                            variant="outline"
                            size="sm"
                          >
                            <XCircle className="h-4 w-4 mr-1" />
                            Reject
                          </Button>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}

              {/* Timestamp Information - Compact with Progressive Disclosure */}
              <div className="pt-2 border-t border-border/40 mt-3">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-help">
                      <Clock className="h-3 w-3" />
                      <span>{formatTimestamp(response.response_generated_at || response.version_confirmed_at || response.created_at)}</span>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" align="start" className="text-xs">
                    <div className="space-y-1">
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-medium opacity-70">Question Created:</span>
                        <span>{formatTimestamp(response.messages[0]?.timestamp || response.created_at)}</span>
                      </div>
                      {response.version_confirmed_at && (
                        <div className="flex items-center justify-between gap-3">
                          <span className="font-medium opacity-70">Version Confirmed:</span>
                          <span>{formatTimestamp(response.version_confirmed_at)}</span>
                        </div>
                      )}
                      {response.response_generated_at && (
                        <div className="flex items-center justify-between gap-3">
                          <span className="font-medium opacity-70">Response Generated:</span>
                          <span>{formatTimestamp(response.response_generated_at)}</span>
                        </div>
                      )}
                      {response.status === 'approved' && response.updated_at && (
                        <div className="flex items-center justify-between gap-3">
                          <span className="font-medium opacity-70">Approved:</span>
                          <span>{formatTimestamp(response.updated_at)}</span>
                        </div>
                      )}
                      {response.status === 'rejected' && response.updated_at && (
                        <div className="flex items-center justify-between gap-3">
                          <span className="font-medium opacity-70">Rejected:</span>
                          <span>{formatTimestamp(response.updated_at)}</span>
                        </div>
                      )}
                    </div>
                  </TooltipContent>
                </Tooltip>
              </div>
            </div>

            {/* Delete button on hover */}
            <div className={cn(
              "ml-4 transition-opacity duration-200",
              hoveredCardId === response.id ? "opacity-100" : "opacity-0"
            )}>
              <Button
                onClick={() => setDeleteConfirmId(response.id)}
                variant="ghost"
                size="icon"
              >
                <Trash2 className="h-4 w-4 text-red-500" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  };

  const renderFailedCard = (response: ShadowResponse) => {
    // Enhanced error message mapping
    const getErrorDetails = (error: string | null) => {
      if (!error) return { message: 'Unknown error occurred', guidance: 'Contact support if this persists' };

      const lowerError = error.toLowerCase();
      if (lowerError.includes('timeout') || lowerError.includes('timed out')) {
        return { message: '✕ Request timed out', guidance: 'Try again - the service may be busy' };
      }
      if (lowerError.includes('rate limit')) {
        return { message: '⚠️ Too many requests', guidance: 'Wait 1 minute before retrying' };
      }
      if (lowerError.includes('api') || lowerError.includes('openai')) {
        return { message: '✕ API error', guidance: 'Check API key and try again' };
      }
      return { message: error, guidance: 'Contact support if this persists' };
    };

    const { message, guidance } = getErrorDetails(response.rag_error);
    const isHighRetryCount = response.retry_count >= 3;

    return (
      <Card
        key={response.id}
        data-testid="failed-card"
        data-status={response.status}
        className={cn(
          "transition-all duration-200 hover:shadow-md",
          hoveredCardId === response.id && "shadow-md"
        )}
        onMouseEnter={() => setHoveredCardId(response.id)}
        onMouseLeave={() => setHoveredCardId(null)}
      >
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {/* Status indicator - subtle dot */}
              <div className={cn("w-2 h-2 rounded-full", getStatusDotColor(response.status))} />
              <h3 className="text-sm font-semibold">{getStatusLabel(response.status)}</h3>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-xs">
                Retry #{response.retry_count}
              </Badge>
              {isHighRetryCount && (
                <Badge variant="outline" className="bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-900/30 dark:text-orange-400 text-xs">
                  High Retry Count
                </Badge>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          <div className="flex items-start justify-between">
            <div className="flex-1 space-y-3">

              {/* Error message with guidance */}
              <div className="space-y-2">
                <div className="p-3 bg-red-50 dark:bg-red-900/20 rounded space-y-2">
                  <p className="text-sm font-medium text-red-700 dark:text-red-400">
                    {message}
                  </p>
                  <p className="text-xs text-red-600 dark:text-red-500">
                    {isHighRetryCount
                      ? `Retry #${response.retry_count} - Maximum retries reached. Consider skipping this response.`
                      : `Retry #${response.retry_count} - ${guidance}`
                    }
                  </p>
                </div>
              </div>

              {/* Actions */}
              <div className="flex gap-2 pt-2">
                {!isHighRetryCount ? (
                  <Button
                    onClick={() => handleRetryRag(response.id)}
                    size="sm"
                    variant="outline"
                  >
                    <RefreshCw className="h-4 w-4 mr-1" />
                    Retry
                  </Button>
                ) : (
                  <Button
                    onClick={() => handleRetryRag(response.id)}
                    size="sm"
                    variant="outline"
                    className="opacity-60"
                  >
                    <RefreshCw className="h-4 w-4 mr-1" />
                    Retry Anyway
                  </Button>
                )}
                <Button
                  onClick={() => handleSkip(response.id)}
                  size="sm"
                  variant={isHighRetryCount ? "default" : "outline"}
                >
                  <SkipForward className="h-4 w-4 mr-1" />
                  {isHighRetryCount ? "Skip (Recommended)" : "Skip"}
                </Button>
              </div>
            </div>

            {/* Delete button */}
            <div className={cn(
              "ml-4 transition-opacity duration-200",
              hoveredCardId === response.id ? "opacity-100" : "opacity-0"
            )}>
              <Button
                onClick={() => setDeleteConfirmId(response.id)}
                variant="ghost"
                size="icon"
              >
                <Trash2 className="h-4 w-4 text-red-500" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  };

  const renderResponseCard = (response: ShadowResponse, index: number) => {
    const isSelected = index === selectedIndex;
    let cardContent;

    switch (response.status) {
      case 'pending_version_review':
        cardContent = renderVersionReviewCard(response);
        break;
      case 'pending_response_review':
        cardContent = renderResponseReviewCard(response);
        break;
      case 'rag_failed':
        cardContent = renderFailedCard(response);
        break;
      default:
        cardContent = renderResponseReviewCard(response); // For completed items
    }

    return (
      <div
        key={response.id}
        ref={(el) => {
          if (el) cardRefs.current.set(response.id, el);
          else cardRefs.current.delete(response.id);
        }}
        className={cn(
          "transition-all duration-200",
          isSelected && "ring-2 ring-primary ring-offset-2 rounded-lg"
        )}
        onClick={() => setSelectedIndex(index)}
      >
        {cardContent}
      </div>
    );
  };

  return (
    <TooltipProvider>
      <div className="container mx-auto py-8 px-4 max-w-7xl space-y-8 pt-16 lg:pt-8">
        {/* Header */}
        <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Shadow Mode Queue</h1>
          <p className="text-muted-foreground">Two-phase review workflow for Matrix shadow testing</p>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="bg-red-100 dark:bg-red-900/30 border border-red-400 dark:border-red-800 text-red-700 dark:text-red-400 px-4 py-3 rounded relative">
          <strong className="font-bold">Error: </strong>
          <span>{error}</span>
          <button onClick={() => setError(null)} className="absolute top-0 bottom-0 right-0 px-4 py-3">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4">
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Total</p>
                  <p className="text-2xl font-bold" data-testid="stat-total">{stats.total}</p>
                </div>
                <MessageCircle className="h-6 w-6 text-blue-500" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Version</p>
                  <p className="text-2xl font-bold" data-testid="stat-version-review">{stats.pending_version_review}</p>
                </div>
                <Clock className="h-6 w-6 text-yellow-500" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Response</p>
                  <p className="text-2xl font-bold" data-testid="stat-pending">{stats.pending_response_review}</p>
                </div>
                <Target className="h-6 w-6 text-blue-500" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Failed</p>
                  <p className="text-2xl font-bold">{stats.rag_failed}</p>
                </div>
                <AlertTriangle className="h-6 w-6 text-red-500" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Approved</p>
                  <p className="text-2xl font-bold">{stats.approved}</p>
                </div>
                <CheckCircle className="h-6 w-6 text-green-500" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Edited</p>
                  <p className="text-2xl font-bold">{stats.edited}</p>
                </div>
                <Edit className="h-6 w-6 text-purple-500" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Rejected</p>
                  <p className="text-2xl font-bold">{stats.rejected}</p>
                </div>
                <XCircle className="h-6 w-6 text-red-500" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Confidence</p>
                  <p className="text-2xl font-bold">{(stats.avg_confidence * 100).toFixed(0)}%</p>
                </div>
                <TrendingUp className="h-6 w-6 text-green-500" />
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Filter */}
      <div className="flex items-center gap-4">
        <Label>Filter:</Label>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Items</SelectItem>
            <SelectItem value="pending_version_review">Version Review</SelectItem>
            <SelectItem value="pending_response_review">Response Review</SelectItem>
            <SelectItem value="rag_failed">Failed</SelectItem>
            <SelectItem value="approved">Approved</SelectItem>
            <SelectItem value="edited">Edited</SelectItem>
            <SelectItem value="rejected">Rejected</SelectItem>
            <SelectItem value="skipped">Skipped</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Response List */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>
                Shadow Responses
                <span className="text-sm font-normal text-muted-foreground ml-2">
                  ({responses.length} items)
                </span>
              </CardTitle>
              <CardDescription>
                Review and process shadow mode responses
              </CardDescription>
            </div>
            <div className="text-xs text-muted-foreground space-x-3 hidden md:flex">
              <span><kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px]">j</kbd>/<kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px]">k</kbd> navigate</span>
              <span><kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px]">Enter</kbd> confirm</span>
              <span><kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px]">s</kbd> skip</span>
              <span><kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px]">d</kbd> delete</span>
              <span><kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px]">⌘K</kbd> commands</span>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoadingData ? (
            <div className="space-y-4">
              {[1, 2, 3].map((i) => (
                <Card key={i} className="border-l-4 border-l-gray-200 animate-pulse">
                  <CardContent className="p-4">
                    <div className="space-y-3">
                      <div className="flex items-center gap-2">
                        <div className="h-5 w-24 bg-gray-200 dark:bg-gray-700 rounded"></div>
                        <div className="h-5 w-16 bg-gray-200 dark:bg-gray-700 rounded"></div>
                      </div>
                      <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-full"></div>
                      <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-3/4"></div>
                      <div className="h-20 bg-gray-200 dark:bg-gray-700 rounded w-full"></div>
                      <div className="flex gap-2">
                        <div className="h-8 w-24 bg-gray-200 dark:bg-gray-700 rounded"></div>
                        <div className="h-8 w-24 bg-gray-200 dark:bg-gray-700 rounded"></div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : responses.length === 0 ? (
            <div className="flex flex-col items-center justify-center min-h-[400px] text-center p-8">
              <MessageSquare className="h-16 w-16 text-muted-foreground mb-4" />
              <h3 className="text-xl font-semibold mb-2">No Responses to Review</h3>
              <p className="text-muted-foreground mb-6 max-w-md">
                {statusFilter === 'pending_version_review'
                  ? "All version detections have been reviewed. New questions will appear here automatically."
                  : statusFilter === 'pending_response_review'
                  ? "All responses have been reviewed. Great work!"
                  : statusFilter === 'rag_failed'
                  ? "No failed responses at this time. The system is running smoothly."
                  : statusFilter === 'all'
                  ? "No shadow mode responses yet. Responses will appear here as users interact with the chatbot."
                  : "No responses match this filter. Try a different filter or wait for new responses."}
              </p>
              <Button onClick={fetchData} variant="outline">
                <RefreshCw className="mr-2 h-4 w-4" />
                Refresh
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              {responses.map((response, index) => renderResponseCard(response, index))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Version Confirmation Dialog */}
      <Dialog open={showVersionDialog} onOpenChange={setShowVersionDialog}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Confirm Version</DialogTitle>
            <DialogDescription>
              Confirm the Bisq version to generate a response
            </DialogDescription>
          </DialogHeader>
          {selectedResponse && (
            <div className="space-y-4">
              <div>
                <Label>Select Version</Label>
                <ToggleGroup
                  type="single"
                  value={selectedVersion}
                  onValueChange={(value) => value && setSelectedVersion(value)}
                  className="justify-start mt-2"
                >
                  <ToggleGroupItem value="bisq1" className={cn(
                    "h-8",
                    selectedVersion === 'bisq1' && "bg-blue-100 dark:bg-blue-900/30"
                  )}>
                    Bisq 1
                  </ToggleGroupItem>
                  <ToggleGroupItem value="bisq2" className={cn(
                    "h-8",
                    selectedVersion === 'bisq2' && "bg-emerald-100 dark:bg-emerald-900/30"
                  )}>
                    Bisq 2
                  </ToggleGroupItem>
                  <ToggleGroupItem value="unknown" className={cn(
                    "h-8",
                    selectedVersion === 'unknown' && "bg-gray-100 dark:bg-gray-800"
                  )}>
                    Unknown
                  </ToggleGroupItem>
                </ToggleGroup>
              </div>

              {selectedVersion !== selectedResponse.detected_version && (
                <div>
                  <Label>Change Reason (optional)</Label>
                  <Input
                    value={versionChangeReason}
                    onChange={(e) => setVersionChangeReason(e.target.value)}
                    placeholder="Why is the detected version incorrect?"
                    className="mt-1"
                  />
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowVersionDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleConfirmVersion} disabled={isConfirmingVersion}>
              {isConfirmingVersion && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Confirm & Generate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Response Review Dialog */}
      <Dialog open={showResponseDialog} onOpenChange={setShowResponseDialog}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Review Response</DialogTitle>
            <DialogDescription>
              Approve, edit, or reject this generated response
            </DialogDescription>
          </DialogHeader>
          {selectedResponse && (
            <div className="space-y-4">
              {/* Question */}
              <div>
                <Label>Question:</Label>
                <p className="mt-1 p-2 bg-accent rounded text-sm">
                  {selectedResponse.synthesized_question || selectedResponse.messages[0]?.content}
                </p>
              </div>

              {/* Response */}
              <div>
                <Label>Response:</Label>
                <Textarea
                  rows={8}
                  value={editedResponse}
                  onChange={(e) => setEditedResponse(e.target.value)}
                  className="mt-1"
                />
              </div>

              {/* Sources - simplified to show only types */}
              {selectedResponse.sources && selectedResponse.sources.length > 0 && (
                <div>
                  <Label>Sources:</Label>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {[...new Set(selectedResponse.sources.map(s => {
                      if (s.type === 'faq') return 'FAQs';
                      if (s.type === 'wiki') return 'Wiki';
                      return s.type;
                    }))].join(', ')}
                  </p>
                </div>
              )}
            </div>
          )}
          <DialogFooter className="flex items-center justify-between">
            {/* Left side: Destructive action (separated) */}
            <Button
              onClick={handleReject}
              variant="ghost"
              size="sm"
              className="text-red-600 hover:text-red-700 hover:bg-red-50"
              disabled={isSubmitting}
            >
              {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              <XCircle className="h-4 w-4 mr-1" />
              Reject
            </Button>

            {/* Right side: Primary actions */}
            <div className="flex gap-2">
              {/* Save Edit - only show if text was actually edited */}
              {editedResponse !== selectedResponse?.generated_response && (
                <Button
                  onClick={handleEdit}
                  variant="outline"
                  disabled={isSubmitting}
                >
                  {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  <Edit className="h-4 w-4 mr-1" />
                  Save Edit
                </Button>
              )}

              {/* Approve - PRIMARY action (larger, prominent) */}
              <Button
                onClick={() => selectedResponse && handleApprove(selectedResponse.id)}
                className="bg-green-600 hover:bg-green-700 min-w-[120px]"
                disabled={isSubmitting}
              >
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                <CheckCircle className="h-4 w-4 mr-1" />
                Approve
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={!!deleteConfirmId} onOpenChange={(open) => !open && setDeleteConfirmId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Response</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this shadow response? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteConfirmId && handleDelete(deleteConfirmId)}
              className="bg-red-600 hover:bg-red-700"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Command Palette */}
      <CommandDialog open={showCommandPalette} onOpenChange={setShowCommandPalette}>
        <CommandInput placeholder="Type a command or search..." />
        <CommandList>
          <CommandEmpty>No results found.</CommandEmpty>
          <CommandGroup heading="Actions">
            <CommandItem
              onSelect={() => {
                if (selectedIndex >= 0 && selectedIndex < responses.length) {
                  const response = responses[selectedIndex];
                  if (response.status === 'pending_version_review') {
                    setSelectedResponse(response);
                    setSelectedVersion(response.detected_version || 'bisq2');
                    setVersionChangeReason('');
                    setShowVersionDialog(true);
                  } else if (response.status === 'pending_response_review') {
                    setSelectedResponse(response);
                    setEditedResponse(response.generated_response || '');
                    setShowResponseDialog(true);
                  }
                }
                setShowCommandPalette(false);
              }}
            >
              <CheckCircle className="mr-2 h-4 w-4" />
              Confirm / Review Selected (Enter)
            </CommandItem>
            <CommandItem
              onSelect={() => {
                if (selectedIndex >= 0 && selectedIndex < responses.length) {
                  const response = responses[selectedIndex];
                  handleSkip(response.id);
                }
                setShowCommandPalette(false);
              }}
            >
              <SkipForward className="mr-2 h-4 w-4" />
              Skip Selected (s)
            </CommandItem>
            <CommandItem
              onSelect={() => {
                if (selectedIndex >= 0 && selectedIndex < responses.length) {
                  setDeleteConfirmId(responses[selectedIndex].id);
                }
                setShowCommandPalette(false);
              }}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete Selected (d)
            </CommandItem>
          </CommandGroup>
          <CommandGroup heading="Navigation">
            <CommandItem
              onSelect={() => {
                fetchResponses();
                fetchStats();
                sonnerToast.success('✓ Data refreshed');
                setShowCommandPalette(false);
              }}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh Data (r)
            </CommandItem>
            <CommandItem
              onSelect={() => {
                setSelectedIndex(-1);
                setShowCommandPalette(false);
              }}
            >
              <X className="mr-2 h-4 w-4" />
              Deselect (Escape)
            </CommandItem>
          </CommandGroup>
          <CommandGroup heading="Filters">
            <CommandItem
              onSelect={() => {
                setStatusFilter('all');
                setShowCommandPalette(false);
              }}
            >
              <MessageCircle className="mr-2 h-4 w-4" />
              Show All
            </CommandItem>
            <CommandItem
              onSelect={() => {
                setStatusFilter('pending_version_review');
                setShowCommandPalette(false);
              }}
            >
              <Clock className="mr-2 h-4 w-4" />
              Filter: Version Review
            </CommandItem>
            <CommandItem
              onSelect={() => {
                setStatusFilter('pending_response_review');
                setShowCommandPalette(false);
              }}
            >
              <Target className="mr-2 h-4 w-4" />
              Filter: Response Review
            </CommandItem>
            <CommandItem
              onSelect={() => {
                setStatusFilter('rag_failed');
                setShowCommandPalette(false);
              }}
            >
              <AlertTriangle className="mr-2 h-4 w-4" />
              Filter: Failed
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </CommandDialog>
      </div>
    </TooltipProvider>
  );
}
