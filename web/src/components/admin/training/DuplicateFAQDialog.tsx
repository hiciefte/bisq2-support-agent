"use client"

import { useMemo } from 'react';
import { AlertTriangle, CheckCircle2, FileQuestion } from 'lucide-react';
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
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';

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

  const sortedFaqs = useMemo(
    () => [...similarFaqs].sort((left, right) => right.similarity - left.similarity),
    [similarFaqs],
  );

  const getMatchTone = (similarity: number) => {
    if (similarity >= 0.95) {
      return {
        label: 'Likely duplicate',
        frameClass: 'border-red-500/30 bg-red-500/5',
        matchBadgeClass: 'border-red-500/35 bg-red-500/15 text-red-300',
      };
    }
    if (similarity >= 0.85) {
      return {
        label: 'Very similar',
        frameClass: 'border-amber-500/30 bg-amber-500/5',
        matchBadgeClass: 'border-amber-500/35 bg-amber-500/15 text-amber-300',
      };
    }
    return {
      label: 'Related',
      frameClass: 'border-border/70 bg-background/50',
      matchBadgeClass: 'border-border/70 bg-muted/60 text-muted-foreground',
    };
  };

  return (
    <AlertDialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent className="max-w-3xl gap-0 overflow-hidden border-amber-500/35 p-0">
        <AlertDialogHeader className="space-y-0">
          <div className="border-b border-amber-500/20 bg-amber-500/8 px-6 py-5">
            <AlertDialogTitle className="flex items-center gap-2 text-lg font-semibold text-amber-300">
              <AlertTriangle className="h-5 w-5 shrink-0" />
              Similar FAQ already exists
            </AlertDialogTitle>
            <AlertDialogDescription className="mt-2 text-sm leading-6 text-muted-foreground">
              This candidate appears to overlap with existing knowledge. Reject as duplicate if coverage is sufficient,
              or approve only if this new FAQ materially improves clarity.
            </AlertDialogDescription>
          </div>
        </AlertDialogHeader>

        <div className="space-y-4 px-6 py-5">
          {candidateQuestion ? (
            <section className="rounded-xl border border-border/70 bg-muted/35 p-4">
              <p className="mb-2 inline-flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                <FileQuestion className="h-3.5 w-3.5" />
                Candidate question
              </p>
              <p className="text-sm leading-6 text-foreground">{candidateQuestion}</p>
            </section>
          ) : null}

          <section className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium text-foreground">
                {sortedFaqs.length} matching FAQ{sortedFaqs.length === 1 ? '' : 's'}
              </p>
              <Badge variant="outline" className="border-amber-500/35 bg-amber-500/12 text-xs text-amber-300">
                Highest match {formatSimilarity(sortedFaqs[0]?.similarity ?? 0)}
              </Badge>
            </div>

            <ScrollArea className="max-h-[340px] pr-1">
              <div className="space-y-3">
                {sortedFaqs.map((faq, index) => {
                  const tone = getMatchTone(faq.similarity);
                  return (
                    <article
                      key={faq.id}
                      className={cn('rounded-xl border p-4', tone.frameClass)}
                    >
                      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                        <p className="text-xs font-medium text-muted-foreground">
                          FAQ #{faq.id}
                        </p>
                        <div className="flex flex-wrap items-center gap-1.5">
                          {index === 0 ? (
                            <Badge variant="secondary" className="text-xs">
                              Top match
                            </Badge>
                          ) : null}
                          <Badge variant="outline" className={cn('text-xs', tone.matchBadgeClass)}>
                            {formatSimilarity(faq.similarity)} match
                          </Badge>
                          <Badge variant="outline" className="text-xs">
                            {tone.label}
                          </Badge>
                          {faq.category ? (
                            <Badge variant="secondary" className="text-xs">
                              {faq.category}
                            </Badge>
                          ) : null}
                        </div>
                      </div>

                      <p className="text-sm font-semibold leading-5 text-foreground">
                        {faq.question}
                      </p>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground line-clamp-3">
                        {faq.answer}
                      </p>
                    </article>
                  );
                })}
              </div>
            </ScrollArea>
          </section>
        </div>

        <AlertDialogFooter className="border-t border-border/70 bg-background/80 px-6 py-4 sm:justify-between sm:space-x-0">
          <p className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:inline-flex">
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
            Reject if duplicate. Approve only for net-new value.
          </p>
          <div className="flex w-full flex-col-reverse gap-2 sm:w-auto sm:flex-row sm:items-center">
            <AlertDialogCancel onClick={onClose} className="mt-0">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction asChild onClick={onRejectAsDuplicate}>
              <Button variant="destructive">Reject as Duplicate</Button>
            </AlertDialogAction>
            <AlertDialogAction asChild onClick={onForceApprove}>
              <Button className="bg-amber-600 text-white hover:bg-amber-500">
                Approve Anyway
              </Button>
            </AlertDialogAction>
          </div>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
