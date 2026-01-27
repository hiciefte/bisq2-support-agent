import { Skeleton } from "@/components/ui/skeleton"
import { Card, CardContent, CardHeader } from "@/components/ui/card"

export default function ManageFeedbackLoading() {
  return (
    <div className="p-4 md:p-8 space-y-8 pt-16 lg:pt-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <Skeleton className="h-9 w-56 mb-2" />
          <Skeleton className="h-5 w-96" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-9 w-24" />
          <Skeleton className="h-9 w-24" />
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-card rounded-lg shadow-sm border border-border">
        <div className="flex space-x-1 border-b border-border px-6 pt-4">
          <Skeleton className="h-10 w-28 rounded-t-lg" />
          <Skeleton className="h-10 w-32 rounded-t-lg" />
          <Skeleton className="h-10 w-40 rounded-t-lg" />
        </div>
      </div>

      {/* Feedback List Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Skeleton className="h-6 w-32" />
            <Skeleton className="h-5 w-16" />
          </div>
          <Skeleton className="h-4 w-48" />
        </CardHeader>
        <CardContent className="space-y-4">
          {[1, 2, 3, 4, 5].map((i) => (
            <Card key={i} className="border-l-4 border-l-gray-200">
              <CardContent className="p-4">
                <div className="flex items-start justify-between">
                  <div className="flex-1 space-y-2">
                    <div className="flex items-center space-x-2">
                      <Skeleton className="h-5 w-5 rounded-full" />
                      <Skeleton className="h-4 w-40" />
                    </div>
                    <Skeleton className="h-5 w-full max-w-xl" />
                    <Skeleton className="h-4 w-full max-w-md" />
                    <div className="flex flex-wrap gap-1 mt-2">
                      <Skeleton className="h-5 w-20 rounded-full" />
                      <Skeleton className="h-5 w-24 rounded-full" />
                    </div>
                    <Skeleton className="h-8 w-28 mt-2" />
                  </div>
                  <div className="flex items-center gap-1 ml-4">
                    <Skeleton className="h-8 w-8 rounded" />
                    <Skeleton className="h-8 w-8 rounded" />
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </CardContent>
      </Card>

      {/* Pagination */}
      <div className="flex items-center justify-between px-2 py-4">
        <Skeleton className="h-4 w-48" />
        <div className="flex items-center gap-2">
          <Skeleton className="h-9 w-20" />
          <Skeleton className="h-9 w-9" />
          <Skeleton className="h-9 w-9" />
          <Skeleton className="h-9 w-9" />
          <Skeleton className="h-9 w-20" />
        </div>
      </div>
    </div>
  )
}
