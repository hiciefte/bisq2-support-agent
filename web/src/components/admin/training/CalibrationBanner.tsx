"use client"

import { Progress } from "@/components/ui/progress";
import { Card, CardContent } from "@/components/ui/card";
import { CheckCircle2, Loader2 } from "lucide-react";

// Updated for unified pipeline
interface CalibrationStatus {
  samples_collected: number;
  samples_required: number;
  is_complete: boolean;
  auto_approve_threshold: number;
  spot_check_threshold: number;
}

interface CalibrationBannerProps {
  status: CalibrationStatus;
}

export function CalibrationBanner({ status }: CalibrationBannerProps) {
  const progress = Math.min(
    (status.samples_collected / status.samples_required) * 100,
    100
  );

  if (status.is_complete) {
    return (
      <Card className="border-border bg-muted/30">
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-muted-foreground" />
            <div className="flex-1">
              <p className="font-medium text-foreground">
                Calibration Complete
              </p>
              <p className="text-sm text-muted-foreground">
                Auto-approve enabled for scores {"\u2265"} {(status.auto_approve_threshold * 100).toFixed(0)}%.
                Spot-check for {"\u2265"} {(status.spot_check_threshold * 100).toFixed(0)}%.
              </p>
            </div>
            <div className="text-right">
              <div className="text-sm font-medium text-foreground">
                {status.samples_collected} / {status.samples_required}
              </div>
              <div className="text-xs text-muted-foreground">
                samples
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-border bg-muted/30">
      <CardContent className="p-4">
        <div className="flex items-center gap-3">
          <Loader2 className="h-5 w-5 text-muted-foreground animate-spin" />
          <div className="flex-1">
            <p className="font-medium text-foreground">
              Calibration In Progress
            </p>
            <p className="text-sm text-muted-foreground mb-2">
              Human review required until {status.samples_required} samples collected.
            </p>
            <Progress
              value={progress}
              className="h-1.5 bg-muted"
            />
          </div>
          <div className="text-right">
            <div className="text-lg font-bold text-foreground">
              {status.samples_collected}
            </div>
            <div className="text-xs text-muted-foreground">
              of {status.samples_required}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
