import Link from 'next/link';
import { FileQuestion, ChevronLeft, MessageCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function FaqNotFound() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="text-center max-w-md">
        <FileQuestion className="h-16 w-16 mx-auto text-muted-foreground mb-6" />
        <h1 className="text-2xl font-semibold mb-2">FAQ Not Found</h1>
        <p className="text-muted-foreground mb-8">
          The FAQ you&apos;re looking for doesn&apos;t exist or may have been removed.
        </p>
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Link href="/faq">
            <Button variant="outline">
              <ChevronLeft className="h-4 w-4 mr-2" />
              Browse All FAQs
            </Button>
          </Link>
          <Link href="/">
            <Button>
              <MessageCircle className="h-4 w-4 mr-2" />
              Ask the Assistant
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
