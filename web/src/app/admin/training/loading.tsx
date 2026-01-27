import { Skeleton } from "@/components/ui/skeleton"
import { Card, CardContent, CardHeader } from "@/components/ui/card"

export default function TrainingLoading() {
  return (
    <div className="p-4 md:p-8 space-y-6 pt-16 lg:pt-8">
      {/* Header */}
      <div>
        <Skeleton className="h-9 w-48 mb-2" />
        <Skeleton className="h-5 w-96" />
      </div>

      {/* Calibration Banner Skeleton */}
      <div className="bg-primary/5 border border-primary/20 rounded-lg p-4">
        <div className="flex items-center gap-3">
          <Skeleton className="h-5 w-5 rounded-full" />
          <div className="flex-1">
            <Skeleton className="h-5 w-64 mb-2" />
            <Skeleton className="h-4 w-48" />
          </div>
        </div>
      </div>

      {/* Queue Status Cards */}
      <div className="grid grid-cols-3 gap-4">
        {[1, 2, 3].map((i) => (
          <Card key={i} className="cursor-pointer">
            <CardContent className="pt-6">
              <div className="flex items-center justify-between mb-2">
                <Skeleton className="h-5 w-28" />
                <Skeleton className="h-6 w-8 rounded-full" />
              </div>
              <Skeleton className="h-4 w-40" />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Session Progress */}
      <div className="flex items-center justify-between text-sm bg-muted/30 px-4 py-2 rounded-lg border border-border">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-4 w-48" />
      </div>

      {/* Main Review Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="space-y-2">
              <Skeleton className="h-6 w-48" />
              <Skeleton className="h-4 w-64" />
            </div>
            <div className="flex items-center gap-2">
              <Skeleton className="h-5 w-20 rounded-full" />
              <Skeleton className="h-5 w-16 rounded-full" />
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Question Section */}
          <div className="space-y-2">
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-20 w-full rounded-lg" />
          </div>

          {/* Staff Answer Section */}
          <div className="space-y-2">
            <Skeleton className="h-5 w-28" />
            <Skeleton className="h-32 w-full rounded-lg" />
          </div>

          {/* Generated Answer Section */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Skeleton className="h-5 w-36" />
              <Skeleton className="h-8 w-32" />
            </div>
            <Skeleton className="h-32 w-full rounded-lg" />
          </div>

          {/* Action Buttons */}
          <div className="flex items-center justify-between pt-4 border-t">
            <Skeleton className="h-10 w-24" />
            <div className="flex gap-3">
              <Skeleton className="h-10 w-28" />
              <Skeleton className="h-10 w-28" />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
