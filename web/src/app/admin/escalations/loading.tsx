import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="p-4 md:p-8 space-y-6 pt-16 lg:pt-8">
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-2">
            <Skeleton className="h-7 w-56" />
            <Skeleton className="h-4 w-80" />
          </div>
          <Skeleton className="h-9 w-9" />
        </div>
        <div className="rounded-lg border border-border/70 bg-card/40 p-1.5">
          <div className="grid grid-cols-2 xl:grid-cols-5 gap-1">
            {[1, 2, 3, 4, 5].map((item) => (
              <Skeleton key={item} className="h-11 w-full" />
            ))}
          </div>
        </div>
      </div>

      <div className="sticky top-16 z-20 -mx-4 md:-mx-8 px-4 md:px-8 py-3 border-y border-border/70 bg-background/95">
        <div className="flex flex-wrap items-center gap-2">
          <Skeleton className="h-9 flex-1 min-w-[240px]" />
          <Skeleton className="h-9 w-[130px]" />
          <Skeleton className="h-9 w-[130px]" />
          <Skeleton className="h-9 w-[110px]" />
        </div>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="space-y-2">
            <Skeleton className="h-5 w-44" />
            <Skeleton className="h-4 w-72" />
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="border border-border rounded-lg p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Skeleton className="h-4 w-4 rounded-full" />
                  <Skeleton className="h-3 w-28" />
                  <Skeleton className="h-4 w-14 rounded-full" />
                </div>
                <Skeleton className="h-3 w-3/4 mb-2" />
                <Skeleton className="h-3 w-1/2" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
