import { useState } from 'react'
import {
  Pause,
  Play,
  Rewind,
  FastForward,
  SkipBack,
  Clock,
  Flame,
  Bus,
  ChevronDown,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'

import { Button } from '#/components/ui/button'
import { Badge } from '#/components/ui/badge'
import { Slider } from '#/components/ui/slider'
import { Switch } from '#/components/ui/switch'
import { Card, CardContent } from '#/components/ui/card'
import { Separator } from '#/components/ui/separator'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '#/components/ui/tooltip'
import { SPEEDS, useSimClock } from '#/hooks/useSimClock'
import { lightPresetForHour, minToHHMM } from '#/lib/demand'
import { cn } from '#/lib/utils'

const SKIP_MIN = 15

const PRESET_LABEL: Record<string, string> = {
  dawn: 'Dawn',
  day: 'Day',
  dusk: 'Dusk',
  night: 'Night',
}

export function SimControls({
  showHeatmap,
  onToggleHeatmap,
  showBuses,
  onToggleBuses,
  resetMinute,
}: {
  showHeatmap: boolean
  onToggleHeatmap: (v: boolean) => void
  showBuses: boolean
  onToggleBuses: (v: boolean) => void
  /** minute to jump to on Reset (first event ramp); falls back to clock default */
  resetMinute?: number
}) {
  const { minute, hhmm, playing, speed, toggle, reset, setSpeed, scrubTo, pause } =
    useSimClock()
  const preset = lightPresetForHour(Math.floor(minute / 60))
  const [open, setOpen] = useState(true)

  const jumpToStart = () => {
    if (resetMinute != null) scrubTo(resetMinute)
    else reset()
    pause()
  }
  const skip = (delta: number) => scrubTo(minute + delta)

  return (
    <Card
      size="sm"
      className="absolute top-4 left-4 z-10 w-[440px] max-w-[calc(100vw-2rem)] gap-0 overflow-hidden bg-card/85 backdrop-blur"
    >
      <CardContent className="flex flex-col">
        <div className="flex items-center gap-2">
          <Clock className="size-4 text-muted-foreground" />
          <span className="font-heading text-lg tabular-nums">{hhmm}</span>
          <Badge variant="secondary">{PRESET_LABEL[preset]}</Badge>
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-label={open ? 'Collapse controls' : 'Expand controls'}
            className="ml-auto"
          >
            <ChevronDown
              className={cn(
                'size-4 text-muted-foreground transition-transform duration-200',
                open && 'rotate-180',
              )}
            />
          </Button>
        </div>

        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              key="body"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
              className="overflow-hidden"
            >
              <div className="flex flex-col gap-3 pt-3">
                <div className="flex items-center gap-2">
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button
                          size="icon-sm"
                          variant="outline"
                          onClick={jumpToStart}
                          aria-label="Jump to first event"
                        />
                      }
                    >
                      <SkipBack />
                    </TooltipTrigger>
                    <TooltipContent>Jump to first event</TooltipContent>
                  </Tooltip>

                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button
                          size="icon-sm"
                          variant="outline"
                          onClick={() => skip(-SKIP_MIN)}
                          aria-label={`Skip back ${SKIP_MIN} minutes`}
                        />
                      }
                    >
                      <Rewind />
                    </TooltipTrigger>
                    <TooltipContent>Back {SKIP_MIN} min</TooltipContent>
                  </Tooltip>

                  <Button
                    size="sm"
                    variant={playing ? 'secondary' : 'default'}
                    onClick={toggle}
                    aria-label={playing ? 'Pause simulation' : 'Play simulation'}
                    className="flex-1"
                  >
                    {playing ? (
                      <>
                        <Pause /> Pause
                      </>
                    ) : (
                      <>
                        <Play /> Play
                      </>
                    )}
                  </Button>

                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button
                          size="icon-sm"
                          variant="outline"
                          onClick={() => skip(SKIP_MIN)}
                          aria-label={`Skip forward ${SKIP_MIN} minutes`}
                        />
                      }
                    >
                      <FastForward />
                    </TooltipTrigger>
                    <TooltipContent>Forward {SKIP_MIN} min</TooltipContent>
                  </Tooltip>
                </div>

                <div
                  role="group"
                  aria-label="Playback speed"
                  className="grid grid-cols-6 gap-0.5 rounded-md bg-muted p-0.5"
                >
                  {SPEEDS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setSpeed(s)}
                      aria-pressed={speed === s}
                      className={cn(
                        'rounded-[6px] px-2 py-1 text-xs font-medium tabular-nums transition-colors',
                        speed === s
                          ? 'bg-card text-foreground shadow-sm'
                          : 'text-muted-foreground hover:text-foreground',
                      )}
                    >
                      {s}×
                    </button>
                  ))}
                </div>

                <div className="flex flex-col gap-1">
                  <Slider
                    value={[minute]}
                    onValueChange={(v) =>
                      scrubTo(Array.isArray(v) ? v[0] : v, { scrubbing: true })
                    }
                    onValueCommitted={(v) =>
                      scrubTo(Array.isArray(v) ? v[0] : v, { scrubbing: false })
                    }
                    min={0}
                    max={1439}
                    step={1}
                    aria-label="Scrub time of day"
                  />
                  <div className="flex justify-between text-[10px] text-muted-foreground tabular-nums">
                    <span>00:00</span>
                    <span>{minToHHMM(minute)}</span>
                    <span>23:59</span>
                  </div>
                </div>

                <Separator />

                <label className="flex cursor-pointer items-center justify-between">
                  <span className="flex items-center gap-2 text-sm font-medium">
                    <Flame className="size-4 text-orange-500" />
                    Demand prediction
                  </span>
                  <Switch
                    checked={showHeatmap}
                    onCheckedChange={onToggleHeatmap}
                    aria-label="Toggle demand heatmap"
                  />
                </label>

                <label className="flex cursor-pointer items-center justify-between">
                  <span className="flex items-center gap-2 text-sm font-medium">
                    <Bus className="size-4 text-blue-500" />
                    Buses
                  </span>
                  <Switch
                    checked={showBuses}
                    onCheckedChange={onToggleBuses}
                    aria-label="Toggle bus layer"
                  />
                </label>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </CardContent>
    </Card>
  )
}
