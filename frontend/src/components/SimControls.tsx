import { Pause, Play, RotateCcw, Clock, Flame, Bus } from 'lucide-react'

import { Button } from '#/components/ui/button'
import { Badge } from '#/components/ui/badge'
import { Slider } from '#/components/ui/slider'
import { Switch } from '#/components/ui/switch'
import { Card, CardContent } from '#/components/ui/card'
import { Separator } from '#/components/ui/separator'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '#/components/ui/select'
import { SPEEDS, useSimClock } from '#/hooks/useSimClock'
import type { Speed } from '#/hooks/useSimClock'
import { lightPresetForHour, minToHHMM } from '#/lib/demand'

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
}: {
  showHeatmap: boolean
  onToggleHeatmap: (v: boolean) => void
  showBuses: boolean
  onToggleBuses: (v: boolean) => void
}) {
  const { minute, hhmm, playing, speed, toggle, reset, setSpeed, scrubTo } =
    useSimClock()
  const preset = lightPresetForHour(Math.floor(minute / 60))

  return (
    <Card
      size="sm"
      className="absolute top-4 left-4 z-10 w-[300px] gap-3 bg-card/85 backdrop-blur"
    >
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="size-4 text-muted-foreground" />
            <span className="font-heading text-lg tabular-nums">{hhmm}</span>
            <Badge variant="secondary">{PRESET_LABEL[preset]}</Badge>
          </div>
          <Badge variant="outline" className="tabular-nums">
            {speed}×
          </Badge>
        </div>

        <div className="flex items-center gap-2">
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

          <Select
            value={String(speed)}
            onValueChange={(v) => setSpeed(Number(v) as Speed)}
          >
            <SelectTrigger size="sm" aria-label="Playback speed">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SPEEDS.map((s) => (
                <SelectItem key={s} value={String(s)}>
                  {s}×
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Button
            size="icon-sm"
            variant="outline"
            onClick={reset}
            aria-label="Reset simulation"
          >
            <RotateCcw />
          </Button>
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
            Demand heatmap
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
            Buses (SUMO replay)
          </span>
          <Switch
            checked={showBuses}
            onCheckedChange={onToggleBuses}
            aria-label="Toggle bus layer"
          />
        </label>
      </CardContent>
    </Card>
  )
}
