import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="p-4 md:p-8 space-y-6 pt-16 lg:pt-8">
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <Skeleton className="h-7 w-56" />
          <Skeleton className="h-4 w-80" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-9 w-24" />
          <Skeleton className="h-9 w-24" />
        </div>
      </div>

      <div className="bg-card rounded-lg border border-border">
        <div className="flex space-x-1 px-4 pt-3 pb-0">
          <Skeleton className="h-9 w-16 rounded-t-lg" />
          <Skeleton className="h-9 w-24 rounded-t-lg" />
          <Skeleton className="h-9 w-28 rounded-t-lg" />
          <Skeleton className="h-9 w-28 rounded-t-lg" />
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
