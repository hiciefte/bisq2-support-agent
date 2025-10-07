"use client"

import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Loader2, TrendingUp, TrendingDown, Clock, ThumbsDown, Users, PlusCircle, RefreshCw, MessageCircle } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useRouter } from 'next/navigation';
import { makeAuthenticatedRequest } from '@/lib/auth';

interface ConversationMessage {
  role: string;
  content: string;
}

interface FeedbackForFAQ {
  message_id: string;
  question: string;
  answer: string;
  explanation: string;
  issues: string[];
  timestamp: string;
  potential_category: string;
  conversation_history?: ConversationMessage[];
}

interface DashboardData {
  helpful_rate: number;
  helpful_rate_trend: number;
  average_response_time: number;
  response_time_trend: number;
  negative_feedback_count: number;
  negative_feedback_trend: number;
  feedback_items_for_faq: FeedbackForFAQ[];
  feedback_items_for_faq_count: number;
  system_uptime: number;
  total_queries: number;
  total_faqs_created: number;
  total_feedback: number;
  total_faqs: number;
  last_updated: string;
  fallback?: boolean;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function AdminOverview() {
  const [dashboardData, setDashboardData] = useState<DashboardData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Create FAQ dialog state
  const [showCreateFAQ, setShowCreateFAQ] = useState(false);
  const [selectedFeedback, setSelectedFeedback] = useState<FeedbackForFAQ | null>(null);
  const [faqForm, setFaqForm] = useState({
    message_id: '',
    suggested_question: '',
    suggested_answer: '',
    category: '',
    additional_notes: ''
  });
  const [isSubmittingFAQ, setIsSubmittingFAQ] = useState(false);
  const [isCustomCategory, setIsCustomCategory] = useState(false);
  const [customCategory, setCustomCategory] = useState('');

  const router = useRouter();

  useEffect(() => {
    // Authentication is handled by SecureAuth wrapper in layout
    fetchDashboardData();

    // Auto-refresh every 30 seconds
    const intervalId = setInterval(() => {
      fetchDashboardData(true);
    }, 30000);

    // Cleanup interval on unmount
    return () => clearInterval(intervalId);
  }, []);

  const fetchDashboardData = async (isRefresh = false) => {
    if (isRefresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }

    try {
      const response = await makeAuthenticatedRequest('/admin/dashboard/overview');

      if (response.ok) {
        const data = await response.json();
        setDashboardData(data);
        setError(null);
      } else {
        setError(`Failed to fetch dashboard data. Status: ${response.status}`);
      }
    } catch (err) {
      setError('An unexpected error occurred while fetching dashboard data.');
      console.error('Dashboard fetch error:', err);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  const handleRefresh = () => {
    fetchDashboardData(true);
  };

  const handleCreateFAQClick = async (item: FeedbackForFAQ) => {
    try {
      // Fetch full feedback details including conversation history
      const response = await makeAuthenticatedRequest(`/admin/feedback/${item.message_id}`);

      if (response.ok) {
        const fullFeedback = await response.json();
        setSelectedFeedback({
          ...item,
          conversation_history: fullFeedback.conversation_history || []
        });
      } else {
        setSelectedFeedback(item);
      }
    } catch (error) {
      console.error('Error fetching feedback details:', error);
      setSelectedFeedback(item);
    }

    setFaqForm({
      message_id: item.message_id,
      suggested_question: item.question,
      suggested_answer: '',
      category: item.potential_category || 'General',
      additional_notes: item.explanation || ''
    });
    setIsCustomCategory(false);
    setCustomCategory('');
    setShowCreateFAQ(true);
  };

  const handleCreateFAQ = async (e: React.FormEvent) => {
    e.preventDefault();

    setIsSubmittingFAQ(true);
    try {
      const response = await makeAuthenticatedRequest('/admin/feedback/create-faq', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(faqForm),
      });

      if (response.ok) {
        setShowCreateFAQ(false);
        setFaqForm({
          message_id: '',
          suggested_question: '',
          suggested_answer: '',
          category: '',
          additional_notes: ''
        });
        setIsCustomCategory(false);
        setCustomCategory('');
        // Refresh data to reflect changes
        fetchDashboardData();
        setError(null);
      } else {
        const errorText = `Failed to create FAQ. Status: ${response.status}`;
        setError(errorText);
      }
    } catch (err) {
      setError('An unexpected error occurred while creating FAQ.');
      console.error('FAQ creation error:', err);
    } finally {
      setIsSubmittingFAQ(false);
    }
  };

  const formatUptime = (seconds: number) => {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);

    if (days > 0) return `${days}d ${hours}h ${minutes}m`;
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
  };

  const formatResponseTime = (seconds: number) => {
    return seconds < 1 ? `${Math.round(seconds * 1000)}ms` : `${seconds.toFixed(1)}s`;
  };

  const getTrendIcon = (trend: number) => {
    if (Math.abs(trend) < 0.1) return null;
    return trend > 0 ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />;
  };

  const getTrendColor = (trend: number, isGood: 'positive' | 'negative') => {
    if (Math.abs(trend) < 0.1) return 'text-muted-foreground';
    const isPositiveChange = trend > 0;
    const shouldBeGreen = (isGood === 'positive' && isPositiveChange) || (isGood === 'negative' && !isPositiveChange);
    return shouldBeGreen ? 'text-green-600' : 'text-red-600';
  };

  if (isLoading) {
    return (
      <div className="p-8">
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <div className="text-center py-12">
          <p className="text-red-600 mb-4">{error}</p>
          <Button onClick={handleRefresh} variant="outline">
            <RefreshCw className="h-4 w-4 mr-2" />
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (!dashboardData) {
    return <div className="p-8">No data available</div>;
  }

  return (
    <div className="p-4 md:p-8 space-y-8 pt-16 lg:pt-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Admin Overview</h1>
          <p className="text-muted-foreground">
            Monitor system performance and manage support analytics
          </p>
        </div>
        <div className="flex items-center gap-2">
          {dashboardData.fallback && (
            <Badge variant="outline" className="text-yellow-600 border-yellow-600">
              Fallback Data
            </Badge>
          )}
          <Button
            onClick={handleRefresh}
            variant="outline"
            size="sm"
            disabled={isRefreshing}
          >
            {isRefreshing ? (
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
            ) : (
              <RefreshCw className="h-4 w-4 mr-2" />
            )}
            Refresh
          </Button>
        </div>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Helpful Rate Card */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Helpful Rate</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{dashboardData.helpful_rate.toFixed(1)}%</div>
            {Math.abs(dashboardData.helpful_rate_trend) >= 0.1 && (
              <div className={`flex items-center text-xs ${getTrendColor(dashboardData.helpful_rate_trend, 'positive')}`}>
                {getTrendIcon(dashboardData.helpful_rate_trend)}
                <span className="ml-1">
                  {dashboardData.helpful_rate_trend > 0 ? '+' : ''}{dashboardData.helpful_rate_trend.toFixed(1)}% from last period
                </span>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Average Response Time Card */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Average Response Time</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatResponseTime(dashboardData.average_response_time)}</div>
            {Math.abs(dashboardData.response_time_trend) >= 0.1 && (
              <div className={`flex items-center text-xs ${getTrendColor(dashboardData.response_time_trend, 'negative')}`}>
                {getTrendIcon(dashboardData.response_time_trend)}
                <span className="ml-1">
                  {dashboardData.response_time_trend > 0 ? '+' : ''}{formatResponseTime(Math.abs(dashboardData.response_time_trend))} from last period
                </span>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Negative Feedback Card */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Negative Feedback</CardTitle>
            <ThumbsDown className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{dashboardData.negative_feedback_count}</div>
            {Math.abs(dashboardData.negative_feedback_trend) >= 0.1 && (
              <div className={`flex items-center text-xs ${getTrendColor(dashboardData.negative_feedback_trend, 'negative')}`}>
                {getTrendIcon(dashboardData.negative_feedback_trend)}
                <span className="ml-1">
                  {dashboardData.negative_feedback_trend > 0 ? '+' : ''}{dashboardData.negative_feedback_trend.toFixed(1)}% from last period
                </span>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Feedback Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm font-medium text-muted-foreground mb-2">Total FAQs</div>
            <div className="text-xl font-bold">{dashboardData.total_faqs}</div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="text-sm font-medium text-muted-foreground mb-2">Total Feedback</div>
            <div className="text-xl font-bold">{dashboardData.total_feedback}</div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="text-sm font-medium text-muted-foreground mb-2">Negative Feedback</div>
            <div className="text-xl font-bold">{dashboardData.negative_feedback_count}</div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="text-sm font-medium text-muted-foreground mb-2">Needs FAQ</div>
            <div className="text-xl font-bold">{dashboardData.feedback_items_for_faq_count}</div>
          </CardContent>
        </Card>
      </div>

      {/* Feedback Items for FAQ Creation */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Feedback Items for FAQ Creation
            <Badge variant="secondary">{dashboardData.feedback_items_for_faq_count}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {dashboardData.feedback_items_for_faq_count === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <PlusCircle className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>No feedback items currently need FAQ creation</p>
            </div>
          ) : (
            <div className="space-y-4">
              {dashboardData.feedback_items_for_faq.map((item) => (
                <div
                  key={item.message_id}
                  className="border rounded-lg p-4 hover:bg-accent/50 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 space-y-2">
                      <div>
                        <h4 className="font-medium text-sm leading-relaxed">{item.question}</h4>
                      </div>
                      <div>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                          {item.explanation.length > 200
                            ? `${item.explanation.substring(0, 200)}...`
                            : item.explanation}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="outline">{item.potential_category}</Badge>
                        {item.issues.slice(0, 2).map((issue, index) => (
                          <Badge key={index} variant="secondary" className="text-xs">
                            {issue}
                          </Badge>
                        ))}
                        {item.issues.length > 2 && (
                          <Badge variant="secondary" className="text-xs">
                            +{item.issues.length - 2} more
                          </Badge>
                        )}
                      </div>
                    </div>
                    <div className="flex flex-col gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleCreateFAQClick(item)}
                      >
                        <PlusCircle className="h-3 w-3 mr-1" />
                        Create FAQ
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Footer */}
      <div className="text-xs text-muted-foreground text-center">
        Last updated: {new Date(dashboardData.last_updated).toLocaleString()}
      </div>

      {/* Create FAQ Dialog */}
      <Dialog open={showCreateFAQ} onOpenChange={setShowCreateFAQ}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Create FAQ from Feedback</DialogTitle>
            <DialogDescription>
              Create a new FAQ entry based on user feedback
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateFAQ} className="space-y-4">
            <div>
              <Label htmlFor="suggested_question">Question</Label>
              <Input
                id="suggested_question"
                value={faqForm.suggested_question}
                onChange={(e) => setFaqForm({ ...faqForm, suggested_question: e.target.value })}
                placeholder="Enter the FAQ question"
                required
              />
            </div>

            <div>
              <Label htmlFor="suggested_answer">Answer</Label>
              <Textarea
                id="suggested_answer"
                value={faqForm.suggested_answer}
                onChange={(e) => setFaqForm({ ...faqForm, suggested_answer: e.target.value })}
                placeholder="Enter the FAQ answer"
                rows={4}
                required
              />
            </div>

            <div>
              <Label htmlFor="category">Category</Label>
              <Select
                value={isCustomCategory ? 'custom' : faqForm.category}
                onValueChange={(value) => {
                  if (value === 'custom') {
                    setIsCustomCategory(true);
                    setFaqForm({ ...faqForm, category: '' });
                  } else {
                    setIsCustomCategory(false);
                    setCustomCategory('');
                    setFaqForm({ ...faqForm, category: value });
                  }
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select a category" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="General">General</SelectItem>
                  <SelectItem value="Trading">Trading</SelectItem>
                  <SelectItem value="Technical">Technical</SelectItem>
                  <SelectItem value="Account">Account</SelectItem>
                  <SelectItem value="Payment">Payment</SelectItem>
                  <SelectItem value="Security">Security</SelectItem>
                  <SelectItem value="custom">Custom Category</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {isCustomCategory && (
              <div>
                <Label htmlFor="customCategory">Custom Category</Label>
                <Input
                  id="customCategory"
                  value={customCategory}
                  onChange={(e) => {
                    setCustomCategory(e.target.value);
                    setFaqForm({ ...faqForm, category: e.target.value });
                  }}
                  placeholder="Enter custom category"
                  required
                />
              </div>
            )}

            {faqForm.additional_notes && (
              <div>
                <Label>User Feedback</Label>
                <div className="mt-1 p-3 bg-red-50 rounded border border-red-200 text-red-900 text-sm">
                  {faqForm.additional_notes}
                </div>
              </div>
            )}

            {selectedFeedback?.conversation_history && selectedFeedback.conversation_history.length > 1 && (
              <div>
                <Label>Conversation History ({selectedFeedback.conversation_history.length - 1} messages)</Label>
                <div className="mt-2 space-y-3 max-h-64 overflow-y-auto p-3 bg-accent rounded">
                  {selectedFeedback.conversation_history.slice(0, -1).map((message, idx) => (
                    <div key={idx} className={`p-3 rounded ${message.role === 'user' ? 'bg-blue-50 border-l-4 border-blue-400' : 'bg-green-50 border-l-4 border-green-400'}`}>
                      <div className="flex items-center gap-2 mb-1">
                        <MessageCircle className="h-4 w-4 text-gray-700" />
                        <span className="font-semibold text-sm text-gray-900">
                          {message.role === 'user' ? 'User' : 'Assistant'}
                        </span>
                      </div>
                      <p className="text-sm text-gray-800 whitespace-pre-wrap">{message.content}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setShowCreateFAQ(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmittingFAQ}>
                {isSubmittingFAQ ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                    Creating...
                  </>
                ) : (
                  'Create FAQ'
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}