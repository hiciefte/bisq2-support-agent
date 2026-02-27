"use client"

import { useEffect, useRef, useState } from 'react';
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, Inbox, Trophy, Zap, Target, Clock } from "lucide-react";
import type { QueueCounts, RoutingCategory } from "./types";

interface EmptyQueueStateProps {
  routing: RoutingCategory;
  onSwitchRouting: (routing: RoutingCategory) => void;
  queueCounts: QueueCounts | null;
  sessionReviewCount?: number;
  sessionStartTime?: number;
}

// Achievement definitions
interface Achievement {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  check: (reviewCount: number, sessionMinutes: number) => boolean;
}

const ACHIEVEMENTS: Achievement[] = [
  {
    id: 'first_review',
    name: 'First Steps',
    description: 'Complete your first review',
    icon: <Target className="h-4 w-4" />,
    check: (count) => count >= 1,
  },
  {
    id: 'queue_crusher',
    name: 'Queue Crusher',
    description: 'Review 10+ items in one session',
    icon: <Trophy className="h-4 w-4" />,
    check: (count) => count >= 10,
  },
  {
    id: 'speed_demon',
    name: 'Speed Demon',
    description: 'Review 5+ items in under 5 minutes',
    icon: <Zap className="h-4 w-4" />,
    check: (count, minutes) => count >= 5 && minutes <= 5,
  },
  {
    id: 'marathon_runner',
    name: 'Marathon Runner',
    description: 'Review for 30+ minutes straight',
    icon: <Clock className="h-4 w-4" />,
    check: (_, minutes) => minutes >= 30,
  },
];

// Get achievements from localStorage
function getUnlockedAchievements(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    const stored = localStorage.getItem('training_achievements');
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

// Save achievement to localStorage
function unlockAchievement(id: string): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const unlocked = getUnlockedAchievements();
    if (unlocked.includes(id)) return false;
    unlocked.push(id);
    localStorage.setItem('training_achievements', JSON.stringify(unlocked));
    return true;
  } catch {
    return false;
  }
}

export function EmptyQueueState({
  routing,
  onSwitchRouting,
  queueCounts,
  sessionReviewCount = 0,
  sessionStartTime,
}: EmptyQueueStateProps) {
  const [newAchievements, setNewAchievements] = useState<Achievement[]>([]);
  const [showCelebration, setShowCelebration] = useState(false);
  const confettiTriggered = useRef(false);

  const routingLabels: Record<RoutingCategory, string> = {
    FULL_REVIEW: "Knowledge Gap",
    SPOT_CHECK: "Minor Gap",
    AUTO_APPROVE: "Calibration"
  };

  // Find other queues with items
  const otherQueuesWithItems = queueCounts
    ? (['FULL_REVIEW', 'SPOT_CHECK', 'AUTO_APPROVE'] as RoutingCategory[])
        .filter(r => r !== routing && queueCounts[r] > 0)
    : [];

  // Calculate session duration in minutes
  const sessionMinutes = sessionStartTime
    ? Math.round((Date.now() - sessionStartTime) / 60000)
    : 0;
  const reviewsPerMinute = sessionMinutes > 0
    ? Math.round((sessionReviewCount / sessionMinutes) * 10) / 10
    : null;

  // Check if all queues are empty (celebration trigger)
  const allQueuesEmpty = !queueCounts ||
    (queueCounts.FULL_REVIEW === 0 &&
     queueCounts.SPOT_CHECK === 0 &&
     queueCounts.AUTO_APPROVE === 0);

  // Trigger confetti and check achievements when all queues empty
  useEffect(() => {
    if (allQueuesEmpty && sessionReviewCount > 0 && !confettiTriggered.current) {
      confettiTriggered.current = true;
      setShowCelebration(true);
      let interval: ReturnType<typeof setInterval> | null = null;
      let isCancelled = false;

      const runConfetti = async () => {
        try {
          const confettiModule = await import('canvas-confetti');
          if (isCancelled) return;

          const confetti = confettiModule.default;
          const duration = 2000;
          const animationEnd = Date.now() + duration;
          const defaults = { startVelocity: 30, spread: 360, ticks: 60, zIndex: 9999 };
          const randomInRange = (min: number, max: number) => Math.random() * (max - min) + min;

          interval = setInterval(() => {
            const timeLeft = animationEnd - Date.now();
            if (timeLeft <= 0) {
              if (interval) clearInterval(interval);
              return;
            }
            const particleCount = 50 * (timeLeft / duration);
            confetti({
              ...defaults,
              particleCount,
              origin: { x: randomInRange(0.1, 0.3), y: Math.random() - 0.2 },
            });
            confetti({
              ...defaults,
              particleCount,
              origin: { x: randomInRange(0.7, 0.9), y: Math.random() - 0.2 },
            });
          }, 250);
        } catch {
          // Optional celebratory effect; ignore loading/runtime failures.
        }
      };

      void runConfetti();

      // Check for new achievements
      const unlockedIds = getUnlockedAchievements();
      const newlyUnlocked: Achievement[] = [];

      for (const achievement of ACHIEVEMENTS) {
        if (!unlockedIds.includes(achievement.id) && achievement.check(sessionReviewCount, sessionMinutes)) {
          if (unlockAchievement(achievement.id)) {
            newlyUnlocked.push(achievement);
          }
        }
      }

      setNewAchievements(newlyUnlocked);

      return () => {
        isCancelled = true;
        if (interval) clearInterval(interval);
      };
    }
  }, [allQueuesEmpty, sessionReviewCount, sessionMinutes]);

  // Reset confetti trigger when queues have items again
  useEffect(() => {
    if (!allQueuesEmpty) {
      confettiTriggered.current = false;
      setShowCelebration(false);
      setNewAchievements([]);
    }
  }, [allQueuesEmpty]);

  return (
    <Card>
      <CardContent className="p-12">
        <div className="text-center space-y-4">
          {/* Icon */}
          <div className="flex justify-center">
            {otherQueuesWithItems.length === 0 ? (
              <div className="p-4 bg-green-100 dark:bg-green-900/30 rounded-full">
                <CheckCircle2 className="h-12 w-12 text-green-600 dark:text-green-400" />
              </div>
            ) : (
              <div className="p-4 bg-muted rounded-full">
                <Inbox className="h-12 w-12 text-muted-foreground" />
              </div>
            )}
          </div>

          {/* Title and description */}
          <div>
            <h3 className="text-lg font-semibold">
              {otherQueuesWithItems.length === 0
                ? "All caught up!"
                : `No items in ${routingLabels[routing]}`}
            </h3>
            <p className="text-sm text-muted-foreground mt-1">
              {otherQueuesWithItems.length === 0
                ? "There are no training pairs waiting for review."
                : `The ${routingLabels[routing]} queue is empty.`}
            </p>
          </div>

          {/* Session stats - show when celebration is active */}
          {showCelebration && sessionReviewCount > 0 && (
            <div className="overflow-hidden transition-all duration-200">
              <div className="py-4 px-6 bg-muted/50 rounded-lg space-y-3">
                <p className="text-sm font-medium text-foreground">
                  Session Summary
                </p>
                <div className="flex justify-center gap-6">
                  <div className="text-center">
                    <div className="text-2xl font-bold text-primary">
                      {sessionReviewCount}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      items reviewed
                    </div>
                  </div>
                  {sessionMinutes > 0 && (
                    <div className="text-center">
                      <div className="text-2xl font-bold text-primary">
                        {sessionMinutes}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {sessionMinutes === 1 ? 'minute' : 'minutes'}
                      </div>
                    </div>
                  )}
                  {sessionMinutes > 0 && sessionReviewCount > 0 && (
                    <div className="text-center">
                      <div className="text-2xl font-bold text-primary">
                        {reviewsPerMinute !== null && Number.isFinite(reviewsPerMinute)
                          ? reviewsPerMinute.toFixed(1)
                          : '-'}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        per minute
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* New achievements */}
          {newAchievements.length > 0 && (
            <div className="overflow-hidden transition-all duration-200">
              <div className="space-y-2">
                <p className="text-sm font-medium text-foreground flex items-center justify-center gap-2">
                  <Trophy className="h-4 w-4 text-yellow-500" />
                  Achievement{newAchievements.length > 1 ? 's' : ''} Unlocked!
                </p>
                <div className="flex justify-center gap-2 flex-wrap">
                  {newAchievements.map((achievement) => (
                    <Badge
                      key={achievement.id}
                      variant="outline"
                      className="gap-1.5 py-1 px-3 bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800"
                    >
                      {achievement.icon}
                      <span>{achievement.name}</span>
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Switch queue buttons */}
          {otherQueuesWithItems.length > 0 && (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                Switch to another queue:
              </p>
              <div className="flex justify-center gap-2">
                {otherQueuesWithItems.map((r) => (
                  <Button
                    key={r}
                    variant="outline"
                    onClick={() => onSwitchRouting(r)}
                  >
                    {routingLabels[r]} ({queueCounts?.[r] || 0})
                  </Button>
                ))}
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
