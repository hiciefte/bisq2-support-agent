'use client';

import Link from 'next/link';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { PublicFAQ } from '@/lib/faqPublicApi';

interface FaqCardProps {
  faq: PublicFAQ;
}

/**
 * FAQ Card component for displaying FAQ items in a grid/list
 * Links to the individual FAQ detail page
 */
export function FaqCard({ faq }: FaqCardProps) {
  // Truncate answer for preview (first 150 chars)
  const truncatedAnswer = faq.answer.length > 150
    ? faq.answer.substring(0, 150).trim() + '...'
    : faq.answer;

  return (
    <Link href={`/faq/${faq.slug}`} className="block group">
      <Card className="h-full transition-all duration-200 hover:shadow-lg hover:border-primary/50 group-focus:ring-2 group-focus:ring-primary">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="text-base font-medium leading-snug line-clamp-2 group-hover:text-primary transition-colors">
              {faq.question}
            </CardTitle>
          </div>
          {faq.category && (
            <Badge variant="secondary" className="w-fit text-xs mt-2">
              {faq.category}
            </Badge>
          )}
        </CardHeader>
        <CardContent className="pt-0">
          <p className="text-sm text-muted-foreground line-clamp-3">
            {truncatedAnswer}
          </p>
        </CardContent>
      </Card>
    </Link>
  );
}

/**
 * Loading skeleton for FaqCard
 */
export function FaqCardSkeleton() {
  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <div className="h-5 w-3/4 bg-muted animate-pulse rounded" />
        <div className="h-5 w-1/2 bg-muted animate-pulse rounded mt-1" />
        <div className="h-5 w-16 bg-muted animate-pulse rounded mt-2" />
      </CardHeader>
      <CardContent className="pt-0">
        <div className="space-y-2">
          <div className="h-4 w-full bg-muted animate-pulse rounded" />
          <div className="h-4 w-5/6 bg-muted animate-pulse rounded" />
          <div className="h-4 w-4/6 bg-muted animate-pulse rounded" />
        </div>
      </CardContent>
    </Card>
  );
}
