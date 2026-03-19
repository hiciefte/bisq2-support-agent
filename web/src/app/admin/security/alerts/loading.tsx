export default function SecurityAlertsLoading() {
  return (
    <div className="p-4 md:p-8 pt-16 lg:pt-8">
      <div className="mx-auto max-w-7xl space-y-4">
        <div className="h-28 animate-pulse rounded-2xl bg-muted/50" />
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
          <div className="h-[520px] animate-pulse rounded-2xl bg-muted/50" />
          <div className="h-[520px] animate-pulse rounded-2xl bg-muted/50" />
        </div>
      </div>
    </div>
  );
}
