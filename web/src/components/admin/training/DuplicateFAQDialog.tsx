"use client"

import { AlertTriangle } from 'lucide-react';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';

interface SimilarFAQ {
  id: number;
  question: string;
  answer: string;
  similarity: number;
  category?: string | null;
}

interface DuplicateFAQDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onRejectAsDuplicate: () => void;
  onForceApprove: () => void;
  similarFaqs: SimilarFAQ[];
  candidateQuestion?: string;
}

export function DuplicateFAQDialog({
  isOpen,
  onClose,
  onRejectAsDuplicate,
  onForceApprove,
  similarFaqs,
  candidateQuestion,
}: DuplicateFAQDialogProps) {
  const formatSimilarity = (similarity: number) => {
    return `${Math.round(similarity * 100)}%`;
  };

  return (
    <AlertDialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent className="max-w-2xl">
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2 text-amber-600">
            <AlertTriangle className="h-5 w-5" />
            Similar FAQ Already Exists
          </AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-3">
              <p>
                This candidate&apos;s question is very similar to an existing FAQ in the knowledge base.
                You can reject it as a duplicate or approve it anyway if you believe it adds value.
              </p>

              {candidateQuestion && (
                <div className="rounded-md bg-muted p-3">
                  <p className="text-xs font-medium text-muted-foreground mb-1">
                    Candidate Question:
                  </p>
                  <p className="text-sm text-foreground">
                    {candidateQuestion}
                  </p>
                </div>
              )}
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="my-4">
          <p className="text-sm font-medium mb-2">
            Matching FAQ{similarFaqs.length > 1 ? 's' : ''} ({similarFaqs.length}):
          </p>
          <ScrollArea className="max-h-64">
            <div className="space-y-3">
              {similarFaqs.map((faq) => (
                <Card key={faq.id} className="border-amber-200 bg-amber-50/50">
                  <CardContent className="p-3">
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <span className="text-xs text-muted-foreground">
                        FAQ #{faq.id}
                      </span>
                      <div className="flex gap-1">
                        <Badge
                          variant="outline"
                          className="text-xs bg-amber-100 border-amber-300 text-amber-700"
                        >
                          {formatSimilarity(faq.similarity)} match
                        </Badge>
                        {faq.category && (
                          <Badge variant="secondary" className="text-xs">
                            {faq.category}
                          </Badge>
                        )}
                      </div>
                    </div>
                    <p className="text-sm font-medium mb-1">
                      {faq.question}
                    </p>
                    <p className="text-xs text-muted-foreground line-clamp-3">
                      {faq.answer}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </ScrollArea>
        </div>

        <AlertDialogFooter className="flex-col sm:flex-row gap-2">
          <AlertDialogCancel onClick={onClose}>
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={onRejectAsDuplicate}
            className="bg-red-600 hover:bg-red-700 text-white"
          >
            Reject as Duplicate
          </AlertDialogAction>
          <AlertDialogAction
            onClick={onForceApprove}
            className="bg-amber-600 hover:bg-amber-700 text-white"
          >
            Approve Anyway
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
