"use client";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export function OverviewSkeleton() {
  return (
    <div className="p-4 md:p-8 pt-16 lg:pt-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <section className="relative overflow-hidden rounded-2xl border border-border/70 bg-card/70 px-5 py-5 md:px-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="space-y-2">
              <Skeleton className="h-9 w-52" />
              <Skeleton className="h-5 w-full max-w-md" />
              <div className="flex items-center gap-2 pt-1">
                <Skeleton className="h-6 w-40 rounded-full" />
                <Skeleton className="h-6 w-28 rounded-full" />
              </div>
            </div>
            <div className="flex flex-col gap-2 sm:items-end">
              <div className="flex items-center gap-2">
                <Skeleton className="h-8 w-12 rounded-md" />
                <Skeleton className="h-8 w-12 rounded-md" />
                <Skeleton className="h-8 w-12 rounded-md" />
              </div>
              <Skeleton className="h-8 w-24" />
            </div>
          </div>
        </section>

        <section>
          <Card className="border-border/70 bg-card/70">
            <CardHeader className="pb-2 space-y-2">
              <Skeleton className="h-6 w-48" />
              <Skeleton className="h-4 w-full max-w-xl" />
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {[1, 2, 3, 4].map((item) => (
                <div key={item} className="rounded-xl border border-border/70 bg-background/40 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-2">
                      <Skeleton className="h-5 w-32" />
                      <Skeleton className="h-9 w-12" />
                    </div>
                    <Skeleton className="h-6 w-20 rounded-full" />
                  </div>
                  <Skeleton className="mt-3 h-4 w-full" />
                  <Skeleton className="mt-2 h-4 w-5/6" />
                  <Skeleton className="mt-4 h-8 w-28" />
                </div>
              ))}
            </CardContent>
          </Card>
        </section>

        <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {[1, 2, 3, 4].map((card) => (
            <Card key={card} className="border-border/70 bg-card/70">
              <CardHeader className="pb-3">
                <Skeleton className="h-4 w-32" />
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center justify-between">
                  <Skeleton className="h-9 w-20" />
                  <Skeleton className="h-5 w-5 rounded-full" />
                </div>
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-4 w-32" />
              </CardContent>
            </Card>
          ))}
        </section>

        <section>
          <Card className="border-border/70 bg-card/70">
            <CardHeader className="pb-3 space-y-2">
              <Skeleton className="h-6 w-56" />
              <Skeleton className="h-4 w-full max-w-lg" />
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="rounded-xl border border-border/70 bg-background/40 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1.5">
                    <Skeleton className="h-4 w-36" />
                    <Skeleton className="h-3 w-52" />
                  </div>
                  <div className="flex items-center gap-2">
                    <Skeleton className="h-6 w-24 rounded-full" />
                    <Skeleton className="h-8 w-20" />
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </section>

        <div className="flex justify-center">
          <Skeleton className="h-4 w-56" />
        </div>
      </div>
    </div>
  );
}
